"""The `codex` CLI backend.

Thinner than the claude one for a structural reason: codex has no
append-to-system-prompt slot, only a replace. So the base text and the role text
are concatenated here and handed over as one block -- same content, different
placement, which is exactly what the Backend docstring warns about.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from crustify_audit.agentlog import AgentLog

# Codex's *built-in* openai provider authenticates from `auth.json` in
# CODEX_HOME (what `codex login` writes) and ignores OPENAI_API_KEY in the
# environment — it fails 401 "Missing bearer or basic authentication".
# Declaring OpenAI as an explicit env-key provider is what makes a key usable
# without a stored login. `wire_api` must be `responses`: codex removed Chat
# Completions support in Feb 2026 and rejects `chat` at config load.
_OPENAI_APIKEY = [
    "-c", "model_provider=openai_apikey",
    "-c", 'model_providers.openai_apikey.name="OpenAI"',
    "-c", 'model_providers.openai_apikey.base_url="https://api.openai.com/v1"',
    "-c", 'model_providers.openai_apikey.env_key="OPENAI_API_KEY"',
    "-c", 'model_providers.openai_apikey.wire_api="responses"',
]

_BASE = (
    "You are running non-interactively. Work autonomously to completion; "
    "there is nobody to ask."
)


class CodexCliBackend:
    def run(self, *, name, model, prompt_template, arguments,
            system_preamble, work_dir, log: AgentLog,
            timeout_s: int | None = None,
            billing: str = "subscription") -> None:
        if shutil.which("codex") is None:
            raise SystemExit(
                "the `codex` CLI is not on PATH. Install it, or pick an "
                "anthropic model to drive the claude backend instead.")
        prompt = prompt_template.format(**arguments)
        cmd = ["timeout", "--signal=TERM", "--kill-after=30", f"{timeout_s}s"] \
            if timeout_s else []
        cmd += [
            "codex", "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m", model,
            "-c", f"instructions={_BASE}\n\n{system_preamble}",
        ]
        if billing == "api":
            if not os.environ.get("OPENAI_API_KEY"):
                raise SystemExit(
                    "--billing api needs OPENAI_API_KEY in the environment.")
            cmd += _OPENAI_APIKEY
        cmd.append(prompt)
        proc = subprocess.Popen(
            cmd, cwd=work_dir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in proc.stdout or ():
            log.write(line)
        proc.wait()
        log.record_usage([])
