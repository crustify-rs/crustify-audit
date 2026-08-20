"""The `claude` CLI backend."""
from __future__ import annotations

import json
import shutil
import subprocess

from crustify_audit.agentlog import AgentLog

#: Appended to, not replacing, the CLI's own system prompt -- claude offers an
#: append slot, so crustify-audit's role text sits beneath the CLI's defaults
#: rather than discarding them.
_BASE = (
    "You are running non-interactively. Work autonomously to completion; "
    "there is nobody to ask. Prefer reading and reasoning over guessing."
)


class ClaudeCliBackend:
    def run(self, *, name, model, prompt_template, arguments,
            system_preamble, work_dir, log: AgentLog,
            timeout_s: int | None = None) -> None:
        if shutil.which("claude") is None:
            raise SystemExit(
                "the `claude` CLI is not on PATH. Install it, or pick an "
                "openai/openrouter model to drive the codex backend instead.")
        prompt = prompt_template.format(**arguments)
        # `timeout` rather than a watchdog thread: the streaming read below
        # blocks, so killing from Python means racing our own loop. Letting the
        # coreutil own the deadline closes the pipe, which ends the loop
        # naturally. TERM first so the CLI can flush; KILL 30s later if it does
        # not.
        cmd = ["timeout", "--signal=TERM", "--kill-after=30", f"{timeout_s}s"] \
            if timeout_s else []
        cmd += [
            "claude",
            "--dangerously-skip-permissions",
            "--model", model,
            "--append-system-prompt", f"{_BASE}\n\n{system_preamble}",
            "--output-format", "stream-json", "--verbose",
            "-p", prompt,
        ]
        proc = subprocess.Popen(
            cmd, cwd=work_dir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        usage: list[dict] = []
        session = ""
        for line in proc.stdout or ():
            log.write(line)
            try:
                evt = json.loads(line)
            except ValueError:
                continue
            session = evt.get("session_id") or session
            if evt.get("type") == "result" and "usage" in evt:
                usage.append(evt["usage"])
        rc = proc.wait()
        log.record_usage(usage, session)
        # 124 is `timeout`'s signal that it fired.
        if rc == 124:
            log.write("\n[crustify-audit] agent hit its wall-clock cap and was "
                      "terminated.\n")
            print(f"[crustify-audit] {name}: hit the wall-clock cap "
                  f"({timeout_s}s) and was terminated.")
