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
    directory. It leaves one lead note per candidate it investigated and one
    advisory per bug it actually crashed. It never edits the audited crate.

    Runs ACCUMULATE. The agent reads what earlier runs left in ``crustify/advisories/``
    and ``crustify/notes/`` before starting, so a second run extends the record instead
    of re-deriving it.
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
        billing: str = "subscription",
    ) -> None:
        self.layout = layout
        self.model = model or self.model
        self.focus = focus
        self.timeout_s = timeout_s
        #: `subscription` | `api` — see the backends, which is where it changes
        #: the argv rather than the environment.
        self.billing = billing

    # ------------------------------------------------------------------ run

    def run(self) -> tuple[int, int]:
        """Drive the hunt. Returns (advisories, leads) counts after the run.

        THERE IS NO DONE SIGNAL AND NO SKIP, deliberately. Runs accumulate:
        each reads what earlier ones left in `crustify/advisories/` and `crustify/notes/` and adds
        to them. Skipping when an artifact exists would make the second run --
        the one that builds on the first -- impossible. The cost is that `ub`
        always spends, so the CLI reports what is already there before starting.
        """
        # The harness guarantees these exist and nothing more. How an advisory
        # is named, what a lead note says, what a reproduction looks like --
        # all the agent's business.
        for d in (self.layout.scratch, self.layout.advisories, self.layout.notes):
            d.mkdir(parents=True, exist_ok=True)

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
                billing=self.billing,
            )
        return self.counts()

    def counts(self) -> tuple[int, int]:
        """(advisories, leads) on disk. The harness counts files; it does not
        parse them."""
        n = lambda d: len(list(d.glob("*.md"))) if d.is_dir() else 0
        return n(self.layout.advisories), n(self.layout.notes)

    # -------------------------------------------------------------- prompt

    def _prompt(self) -> str:
        return (_PKG_ROOT / "prompts" / "ub.md").read_text()

    def _arguments(self) -> dict:
        inst = self.instruments(self.layout)
        have = ", ".join(k for k, v in inst.items() if v) or "none detected"
        missing = ", ".join(k for k, v in inst.items() if not v)
        return {
            "workspace": str(self.layout.workspace),
            # ONE root, not two leaves. `advisories/` and `notes/` are fixed
            # names under it, so injecting each separately would let the prompt
            # and the layout disagree about a structure that is not negotiable.
            "crustify_dir": str(self.layout.root),
            "scratch": str(self.layout.scratch),
            "focus": self.focus or "(none — work the seed in rank order)",
            # The agent cannot see a clock. Without this it cannot budget, and
            # a SIGTERM at the deadline reads to it as an unexplained death.
            "budget": (f"{self.timeout_s // 60} minutes" if self.timeout_s
                       else "no limit"),
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
            "HARD RULE. Inside the audited workspace you may write ONLY under "
            "its `crustify/` directory -- your notes and advisories belong "
            "there and nowhere else. Its source, tests and build files are "
            "read-only to you. Your scratch directory is yours entirely."
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
