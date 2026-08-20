"""layout.py — where crustify-audit puts things.

ONE deliberate difference from crustify-cli, and it is the whole reason this is
a separate binary: the subject is an ORDINARY CARGO WORKSPACE. There is no
``crustify/`` directory to find, no ``scope-config.json`` to read, no CodeQL
database, no campaign. Both crustify binaries mandate ``<repo_root> <target>``
and bail with "no crustify/ under repo_root"; the audit that motivated this
tool was of a third-party crate with none of that, and could not have been run
through either.

Artifacts land in ``<workspace>/.crustify-audit/`` -- inside the audited tree so
they travel with it, and named so a single ``.gitignore`` line covers them. Pass
``--out`` to keep the audited tree pristine.
"""
from __future__ import annotations

from pathlib import Path

ARTIFACT_DIR = ".crustify-audit"


class Layout:
    def __init__(self, workspace: Path, out: Path | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = Path(out).resolve() if out else self.workspace / ARTIFACT_DIR

    # ---- deterministic half
    @property
    def metrics(self) -> Path:
        """The composer's output: counts + a ranked seed list. Reproducible."""
        return self.root / "metrics.json"

    # ---- agentic half
    @property
    def findings(self) -> Path:
        """The agent's output. Existence is the done signal."""
        return self.root / "findings.json"

    @property
    def scratch(self) -> Path:
        """The agent's writable area -- repro crates, miri output, notes.

        Outside the audited crate on purpose: the agent has no reason to write
        there and every reason not to.
        """
        return self.root / "scratch"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def is_cargo_workspace(self) -> bool:
        return (self.workspace / "Cargo.toml").is_file()
