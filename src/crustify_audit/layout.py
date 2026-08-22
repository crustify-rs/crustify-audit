"""layout.py — where crustify-audit puts things.

ONE deliberate difference from crustify-cli, and it is the whole reason this is
a separate binary: the subject is an ORDINARY CARGO WORKSPACE. There is no
``crustify/`` directory to find, no ``scope-config.json`` to read, no CodeQL
database, no campaign. The campaign binaries mandate ``<repo_root> <target>``;
the audit that motivated this tool was of a third-party crate with none of
that, and could not have been run through either.

Artifacts land in ``<repo>/crustify/audit/`` -- under the same directory
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


#: Where a crustify campaign puts the Rust it emitted. Checked when the repo
#: root is not itself a crate.
CAMPAIGN_WORKSPACE = "crustify/rust"


class Layout:
    """Paths for one audit, resolved from the REPO.

    The subject is a repository, not a bare cargo workspace, because a wrapper
    is not auditable without the thing it wraps: `ub` requires a reproduction
    that links the audited crate, which for an FFI wrapper means building the C
    library, whose sources are in the repo — beside the Rust, not inside it. A
    run pointed at `crustify/rust` alone had to clone the C project from
    GitHub to get them back.

    So `repo` is the mount and `workspace` is the crate within it: the repo
    root when that is itself a crate, otherwise `crustify/rust`. Artifacts hang
    off the REPO either way, which also puts `crustify/audit/` beside
    `crustify/rust/` rather than nested inside it.
    """

    def __init__(self, repo: Path) -> None:
        self.repo = Path(repo).resolve()
        self.root = self.repo / ARTIFACT_DIR

    @property
    def workspace(self) -> Path:
        """The cargo workspace to measure and build."""
        if (self.repo / "Cargo.toml").is_file():
            return self.repo
        return self.repo / CAMPAIGN_WORKSPACE

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
