"""The `codex` CLI backend.

Thinner than the claude one for a structural reason: codex has no
append-to-system-prompt slot, only a replace. So the base text and the role text
are concatenated here and handed over as one block -- same content, different
placement, which is exactly what the Backend docstring warns about.
"""
from __future__ import annotations

import shutil
import subprocess

from crustify_audit.agentlog import AgentLog

_BASE = (
    "You are running non-interactively. Work autonomously to completion; "
    "there is nobody to ask."
)


class CodexCliBackend:
    def run(self, *, name, model, prompt_template, arguments,
            system_preamble, work_dir, log: AgentLog) -> None:
        if shutil.which("codex") is None:
            raise SystemExit(
                "the `codex` CLI is not on PATH. Install it, or pick an "
                "anthropic model to drive the claude backend instead.")
        prompt = prompt_template.format(**arguments)
        cmd = [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m", model,
            "-c", f"instructions={_BASE}\n\n{system_preamble}",
            prompt,
        ]
        proc = subprocess.Popen(
            cmd, cwd=work_dir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout or ():
            log.write(line)
        proc.wait()
        log.record_usage([])
