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

    # ---- `unsafe`: the deterministic half
    @property
    def scan(self) -> Path:
        """The scanner's output: counts + a ranked seed list. Reproducible."""
        return self.root / "unsafe.json"

    # ---- `ub`: the agentic half
    @property
    def advisory(self) -> Path:
        """The agent's output, authored by the agent. Existence is the done
        signal. Markdown, not a schema: the harness does not dictate what a
        report should look like."""
        return self.root / "advisory.md"

    @property
    def scratch(self) -> Path:
        """The agent's writable area -- reproductions, miri output, notes.

        Outside the audited crate on purpose: the agent has no reason to write
        there and every reason not to. What goes in it is the agent's business;
        the harness only guarantees the directory exists.
        """
        return self.root / "scratch"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def is_cargo_workspace(self) -> bool:
        return (self.workspace / "Cargo.toml").is_file()
