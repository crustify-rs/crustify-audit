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
    working directory IS its scratch space, so the audited tree is somewhere it
    only ever reads.
  * the DAG, the scope sets, the wave scheduler. There is no ordering problem:
    the scan hands over a ranked list and the agent walks it.

WHERE THE LINE SITS. The harness runs the scan, hands over a seed and a
writable directory, and starts the agent. Everything after that — what to
investigate, how to reduce it, what a reproduction looks like, how to structure
the advisory — is the agent's job. An earlier cut of this file pre-built a repro
crate and specified a findings JSON schema field by field; both were the harness
doing work it has no business doing, and a schema is a poor substitute for
telling an author what makes a report land. The prompt says what good looks
like; it does not hand over a form.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from crustify_audit.agentlog import AgentLog, open_agent_log
from crustify_audit.layout import Layout

_PKG_ROOT = Path(__file__).resolve().parent.parent


class AuditAgent:
    """One UB hunt over one workspace.

    The agent is handed the deterministic seed (``unsafe.json``) and a scratch
    directory. It always leaves a record of what it examined; it writes an
    advisory only when it actually crashed something. It never edits the
    audited crate.
    """

    name = "crustify-audit"
    stage = "ub"
    #: Default model. Overridden by ``--model``; the provider prefix selects
    #: the backend, so this is the only place a default is stated.
    model = "anthropic/claude-opus-5"

    def __init__(
        self,
        layout: Layout,
        *,
        model: str | None = None,
        focus: str | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.layout = layout
        self.model = model or self.model
        self.focus = focus
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------ run

    def run(self) -> Path | None:
        """Drive the hunt. Returns the notes path once the agent has run.

        The DONE signal is the notes, not the advisory: a clean audit writes no
        advisory, and gating on a file that a successful run may legitimately
        never create would re-run the agent forever.
        """
        out = self.layout.notes
        if out.is_file():
            print(f"[crustify-audit] {self.stage}: {out} already exists, skipping. "
                  f"Delete it to re-run.")
            return out

        seed = self.layout.scan
        if not seed.is_file():
            raise SystemExit(
                f"{self.stage}: no {seed}. Run `crustify-audit "
                f"{self.layout.workspace} unsafe` first — the agent hunts over "
                f"the deterministic seed, it does not scan from scratch.")

        # The only thing the harness guarantees about the scratch dir is that
        # it exists. What the agent builds in it is the agent's business.
        self.layout.scratch.mkdir(parents=True, exist_ok=True)

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
                timeout_s=self.timeout_s,
            )
        return out if out.is_file() else None

    # -------------------------------------------------------------- prompt

    def _prompt(self) -> str:
        return (_PKG_ROOT / "prompts" / "ub.md").read_text()

    def _arguments(self) -> dict:
        inst = self.instruments(self.layout)
        have = ", ".join(k for k, v in inst.items() if v) or "none detected"
        missing = ", ".join(k for k, v in inst.items() if not v)
        return {
            "workspace": str(self.layout.workspace),
            "scan_json": str(self.layout.scan),
            "advisory": str(self.layout.advisory),
            "notes": str(self.layout.notes),
            "scratch": str(self.layout.scratch),
            "focus": self.focus or "(none — work the seed in rank order)",
            "instruments": have + (f"    (not detected: {missing})" if missing else ""),
        }

    def system_preamble(self) -> str:
        """The role and the one hard rule.

        Short on purpose. Everything procedural lives in the prompt, which is
        editable without touching code; this is only what must hold whatever
        the agent is hunting.
        """
        return (
            "You audit Rust code that wraps C, looking for undefined behaviour "
            "reachable from safe code.\n\n"
            "A finding you cannot demonstrate is a hypothesis. Say which you "
            "are reporting.\n\n"
            "HARD RULE. Never modify the audited workspace. Write only inside "
            "your scratch directory. You are a reader everywhere else."
        )

    # ------------------------------------------------------- instruments

    @staticmethod
    def _ok(cmd: list[str]) -> bool:
        try:
            return subprocess.run(cmd, capture_output=True, text=True).returncode == 0
        except OSError:
            return False

    @classmethod
    def miri_available(cls) -> bool:
        return shutil.which("cargo") is not None and cls._ok(
            ["cargo", "+nightly", "miri", "--version"])

    @classmethod
    def instruments(cls, layout: Layout) -> dict[str, bool]:
        """What is actually installed, so the prompt can say so.

        Mechanism, not judgement: this reports availability and stops there.
        WHICH instrument suits a given candidate is the agent's call, and the
        prompt describes what each one is good for rather than prescribing an
        order. Telling an agent "miri is not installed" is useful; telling it
        "therefore use ASan" would be the harness deciding again.
        """
        cargo = shutil.which("cargo") is not None
        nightly = cargo and cls._ok(["cargo", "+nightly", "--version"])
        return {
            "cargo": cargo,
            "nightly": nightly,
            "miri": cls.miri_available(),
            # Sanitizers are nightly + an explicit --target (so build scripts and
            # proc macros are not instrumented). Presence of nightly is the best
            # cheap proxy; whether the crate actually LINKS under them depends on
            # its C dependencies and can only be found out by trying.
            "sanitizers": nightly,
            # The one that decides whether sanitizers are usable at all: they
            # instrument code that RUNS, so without a build there is nothing to
            # instrument. Deliberately not a hard check -- `cargo build` on a
            # crate needing system libraries can take minutes and fail for
            # reasons that are not the agent's problem.
            "builds": (layout.workspace / "Cargo.lock").is_file(),
        }
