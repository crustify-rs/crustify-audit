"""base.py — the single audit agent.

WHAT THIS BORROWS FROM crustify-cli, AND WHAT IT DELIBERATELY DOES NOT.

Kept, because they earned their place there and the reasons carry over:

  * the ``Backend`` protocol and the one call site that drives it. Running the
    provider CLI out-of-process, one subprocess per agent, is what makes usage
    accounting exact — the provider reports for that invocation and nothing
    else.
  * ``<provider>/<model>`` routing, where the provider selects the backend. A
    bare model id is ambiguous across services that price differently.
  * the system-preamble seam, so the same text reaches claude's append slot and
    codex's replace slot without diverging.
  * an on-disk artifact as the done signal, so a re-run is a no-op rather than
    a second bill.

Dropped, because crustify-audit is one agent over one workspace:

  * the stage/tier/output class hierarchy. There is one role, so there is one
    class and no ``SKILLS`` tuple to vary.
  * worktree isolation. Nothing here writes to the audited crate; the agent's
    scratch space is its own directory, and the audited workspace is mounted
    read-only in spirit (see ``_work_dir``).
  * the DAG, the scope sets, the wave scheduler. There is no ordering problem:
    the composer hands over a ranked list and the agent walks it.

ADDED, and this is the part with no analogue in crustify-cli: a **falsifiable**
output contract. A finding is not a finding because the model says so. Each one
must carry a standalone ``repro.rs`` that miri rejects, or be recorded with
``verified: false``. The agent's own claim is the least trustworthy thing in
the pipeline, so the pipeline is arranged to check it — the same reason the C
side anchors everything on the CodeQL tables rather than on an agent's reading.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from crustify_audit.agentlog import AgentLog, open_agent_log
from crustify_audit.layout import Layout

_PKG_ROOT = Path(__file__).resolve().parent.parent


class AuditAgent:
    """One UB hunt over one workspace.

    The agent is handed the composer's seed (``metrics.json``) and a scratch
    directory, and is asked to produce ``findings.json``. It never edits the
    audited crate.
    """

    name = "crustify-audit"
    stage = "hunt"
    #: Default model. Overridden by ``--model``; the provider prefix selects
    #: the backend, so this is the only place a default is stated.
    model = "anthropic/claude-opus-4-8"

    def __init__(
        self,
        layout: Layout,
        *,
        model: str | None = None,
        focus: str | None = None,
        max_findings: int = 10,
    ) -> None:
        self.layout = layout
        self.model = model or self.model
        self.focus = focus
        self.max_findings = max_findings

    # ------------------------------------------------------------------ run

    def run(self) -> Path | None:
        """Drive the hunt. Returns the findings path, or ``None`` if skipped."""
        out = self.layout.findings
        if out.is_file():
            print(f"[crustify-audit] {self.stage}: {out} already exists, skipping. "
                  f"Delete it to re-run.")
            return out

        seed = self.layout.metrics
        if not seed.is_file():
            raise SystemExit(
                f"{self.stage}: no {seed}. Run `crustify-audit "
                f"{self.layout.workspace} metrics` first — the agent hunts over "
                f"the composer's seed, it does not scan from scratch.")

        self.layout.scratch.mkdir(parents=True, exist_ok=True)
        self._seed_repro_harness()

        from crustify_audit.agents.backends import get_backend
        from crustify_audit.models import resolve as resolve_model

        route = resolve_model(self.model)
        with open_agent_log(self.layout.logs, self.stage) as log:
            get_backend(route.backend).run(
                name=self.name,
                model=route.model,
                prompt_template=self._prompt(),
                arguments=self._arguments(),
                system_preamble=self.system_preamble(),
                work_dir=str(self.layout.scratch),
                log=log,
            )
        return out if out.is_file() else None

    # -------------------------------------------------------------- prompt

    def _prompt(self) -> str:
        return (_PKG_ROOT / "prompts" / "hunt.md").read_text()

    def _arguments(self) -> dict:
        return {
            "workspace": str(self.layout.workspace),
            "metrics_json": str(self.layout.metrics),
            "findings_json": str(self.layout.findings),
            "scratch": str(self.layout.scratch),
            "max_findings": self.max_findings,
            "focus": self.focus or "(no focus given — work the seed in rank order)",
        }

    def system_preamble(self) -> str:
        """The role, the evidence standard, and the one hard rule.

        Short on purpose. Everything procedural lives in the prompt, which is
        editable without touching code; this is only what must be true of the
        agent regardless of which hunt it is running.
        """
        return (
            "You audit Rust code that wraps C, looking for undefined behaviour "
            "reachable from safe code.\n\n"
            "EVIDENCE STANDARD. A finding you cannot demonstrate is a "
            "hypothesis, not a finding. Every entry you record must either "
            "carry a standalone reproduction that miri rejects, or be marked "
            "`verified: false` and explain what stopped you. Reporting three "
            "verified findings beats reporting twenty plausible ones — a "
            "false positive costs a maintainer more than a missed bug costs "
            "you.\n\n"
            "HARD RULE. Never modify the audited workspace. Write only inside "
            "your scratch directory. You are a reader everywhere else."
        )

    # ------------------------------------------------------- repro harness

    def _seed_repro_harness(self) -> None:
        """Put a ready-to-run miri crate in the scratch dir.

        The agent should spend its budget reasoning about aliasing, not
        fighting cargo. It gets a crate that already builds and already has
        miri available, so `cargo +nightly miri run` is one command away.

        Deterministic, so it is done here rather than asked for in the prompt:
        anything the agent does not have to be told is budget it does not spend
        and a step it cannot get wrong.
        """
        crate = self.layout.scratch / "repro"
        (crate / "src").mkdir(parents=True, exist_ok=True)
        (crate / "Cargo.toml").write_text(
            '[package]\nname = "repro"\nversion = "0.1.0"\nedition = "2021"\n\n'
            "[dependencies]\n"
        )
        main = crate / "src" / "main.rs"
        if not main.exists():
            main.write_text(
                "// Replace with a minimal reduction of ONE finding, then:\n"
                "//   cargo +nightly miri run\n"
                "//   MIRIFLAGS=-Zmiri-tree-borrows cargo +nightly miri run\n"
                "// Both models matter: Stacked Borrows is still experimental, "
                "so a\n// finding rejected by Tree Borrows too is much harder to "
                "argue with.\n"
                "fn main() {}\n"
            )

    # ------------------------------------------------------------ verify

    @staticmethod
    def miri_available() -> bool:
        if shutil.which("cargo") is None:
            return False
        r = subprocess.run(
            ["cargo", "+nightly", "miri", "--version"],
            capture_output=True, text=True,
        )
        return r.returncode == 0


def load_findings(path: Path) -> list[dict]:
    """Read a findings file, tolerating the agent having written nothing."""
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text())
    except ValueError as e:
        raise SystemExit(f"findings: {path} is not valid JSON: {e}")
    return doc.get("findings") or []
