"""Pluggable agent backends.

The contract is crustify-cli's, deliberately: render a prompt, run an agent
confined to a shell tool in a work dir, stream its output to a log. Keeping the
two identical means a backend improvement -- better usage parsing, a new
provider -- ports between the projects as a file copy rather than a rewrite.

Each backend shells out to a provider CLI, one subprocess per agent. Running
out-of-process is what makes usage accounting exact: the provider reports for
that invocation and nothing else.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from crustify_audit.agentlog import AgentLog


@runtime_checkable
class Backend(Protocol):
    def run(
        self,
        *,
        name: str,
        model: str,
        prompt_template: str,
        arguments: dict,
        system_preamble: str,
        work_dir: str,
        log: AgentLog,
        timeout_s: int | None = None,
    ) -> None:
        """Drive one agent to completion.

        The prompt is ``prompt_template.format(**arguments)`` and arrives as the
        agent's first user message. ``system_preamble`` goes to the CLI's
        system-instruction slot -- claude appends to its own, codex can only
        replace, so each backend places the same string its own way and the
        content never diverges.

        ``timeout_s`` is a WALL-CLOCK ceiling. It is the only cap that works
        under subscription auth: `--max-budget-usd` meters API-call spend, of
        which there is none, and this CLI has no turn limit. A killed agent may
        have written a partial advisory or none at all, which the caller has to
        report honestly rather than treat as "found nothing".

        The return value is intentionally unused: success is judged by what is
        on disk, not by an exit code the agent controls.
        """
        ...


def get_backend(name: str) -> Backend:
    if name == "claude_cli":
        from crustify_audit.agents.backends.claude_cli import ClaudeCliBackend
        return ClaudeCliBackend()
    if name == "codex_cli":
        from crustify_audit.agents.backends.codex_cli import CodexCliBackend
        return CodexCliBackend()
    raise SystemExit(
        f"Unknown backend {name!r}; expected one of: claude_cli, codex_cli.")
