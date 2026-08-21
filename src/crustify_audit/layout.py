"""layout.py — where crustify-audit puts things.

ONE deliberate difference from crustify-cli, and it is the whole reason this is
a separate binary: the subject is an ORDINARY CARGO WORKSPACE. There is no
``crustify/`` directory to find, no ``scope-config.json`` to read, no CodeQL
database, no campaign. Both crustify binaries mandate ``<repo_root> <target>``
and bail with "no crustify/ under repo_root"; the audit that motivated this
tool was of a third-party crate with none of that, and could not have been run
through either.

Artifacts land in ``<workspace>/crustify/`` -- the same directory name
crustify-cli uses at a repo root, so auditing a crate that IS a crustify
campaign target puts the audit beside the campaign rather than in a second
place. Inside the audited tree on purpose: notes and advisories are about that
crate and should travel with it, and accumulate across runs.

"""
from __future__ import annotations

from pathlib import Path

#: Under `crustify/`, not beside it: auditing a campaign target should put the
#: audit next to the campaign. In its OWN subdirectory, because a target that
#: has been through crustify-cli already has `codeql/`, `rust/`, `crates.json`
#: and the rest at that level, and interleaving two tools' artifacts in one
#: listing makes neither readable — and leaves the next name either side adds
#: free to collide.
ARTIFACT_DIR = "crustify/audit"


class Layout:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ARTIFACT_DIR

    # ---- `unsafe`: the deterministic half
    @property
    def scan(self) -> Path:
        """The deterministic pass's output: the unsafe metrics. Reproducible."""
        return self.root / "unsafe.json"

    # ---- `ub`: the agentic half
    #
    # ONE FILE PER THING, and the directories are the memory. A later run reads
    # what earlier runs left rather than being handed it by a flag: no plumbing,
    # and the record is the same artifact a human reads. It also makes the two
    # populations separately greppable -- confirmed bugs are not mixed in with
    # candidates that did not pan out.

    @property
    def advisories(self) -> Path:
        """One advisory per CONFIRMED bug. A file here means something crashed.

        Per-bug rather than one document, because bugs are reported, fixed and
        argued about one at a time -- a maintainer wants the file about THEIR
        bug, not a chapter of a combined report.
        """
        return self.root / "advisories"

    @property
    def notes(self) -> Path:
        """One note per LEAD investigated, whether or not it panned out.

        This is the audit trail and the anti-duplication record at once. A lead
        that was chased and cleared is a result: it stops the next run spending
        its budget re-deriving the same "no".
        """
        return self.root / "notes"

    @property
    def scratch(self) -> Path:
        """`tmp/` -- the agent's writable area: reproductions, miri output.

        Named for what it is, and kept under the artifact root beside the
        advisories that cite it, so a reproduction stays findable from the
        finding it backs. What goes in it is the agent's business; the harness
        only guarantees the directory exists.
        """
        return self.root / "tmp"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def is_cargo_workspace(self) -> bool:
        return (self.workspace / "Cargo.toml").is_file()
