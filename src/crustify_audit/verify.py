"""verify.py — independently re-derive the agent's evidence.

WHY THIS IS NOT THE SCHEMA MISTAKE AGAIN.

Telling the agent what fields its report must have was the harness doing the
agent's job. This is different, and the line is worth stating precisely:

    The harness does not decide what is a bug.
    The harness does check whether a command the agent says it ran
    produces the output the agent says it produced.

Nothing here parses the advisory into a structure or requires it to have one.
It re-runs whatever reproductions it finds, records what actually happened, and
prints both next to each other. Comparing them is the reader's job — but the
reader now has two independent accounts instead of one self-reported one.

That is the same discipline the C side applies by anchoring scope on the CodeQL
tables rather than on an agent's reading of the source: the agent's claim is the
least trustworthy artifact in the pipeline, so nothing downstream should have to
take it on faith.

WHAT THIS CATCHES, AND WHAT IT CANNOT.

Catches outright:
  * fabricated tool output — an advisory quoting a Miri error nobody produced
  * a reproduction that does not actually fail
  * modification of the audited workspace

Cannot catch, and no amount of harness will:
  * a reproduction that IS unsound but misrepresents the crate — Miri rejects
    it honestly, and only reading the real code tells you the reduction added a
    `transmute_copy` the crate does not have. Citation checking below narrows
    this (a cited line must exist and is printed verbatim for comparison) but
    does not close it.
  * an `unsafe fn` misused in the reduction and reported as a soundness bug
  * UB in the reduction's own scaffolding rather than the pattern under test

Those need an adversary, not a checker. See the note at the end of the module.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from crustify_audit.layout import Layout

#: `path/to/file.rs:123` in prose. Deliberately loose: the point is to find
#: citations wherever the agent chose to put them, not to impose a place.
_CITE = re.compile(r"([\w./\-]+\.rs):(\d+)")


# ------------------------------------------------------------- tamper check

def fingerprint(workspace: Path) -> str:
    """A cheap identity for the audited tree.

    Prefer git: it is exact, instant, and reports staged/unstaged/untracked in
    one shot. Fall back to hashing the source when the subject is not a repo.
    """
    r = subprocess.run(["git", "-C", str(workspace), "status", "--porcelain"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        head = subprocess.run(["git", "-C", str(workspace), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        return f"git:{head}:{hashlib.sha256(r.stdout.encode()).hexdigest()[:16]}"
    h = hashlib.sha256()
    for p in sorted(workspace.rglob("*.rs")):
        if "target/" in str(p):
            continue
        try:
            h.update(p.read_bytes())
        except OSError:
            pass
    return f"hash:{h.hexdigest()[:16]}"


# ------------------------------------------------------ reproduction re-runs

def _repro_crates(scratch: Path) -> list[Path]:
    """Every cargo crate the agent left behind, wherever it chose to put them.

    Discovered, not mandated. The agent decides what a reproduction looks like
    and where it lives; this finds them by their one unavoidable property —
    a cargo crate has a Cargo.toml with a [package] section.
    """
    out = []
    for toml in sorted(scratch.rglob("Cargo.toml")):
        if "target" in toml.parts:
            continue
        try:
            if "[package]" in toml.read_text():
                out.append(toml.parent)
        except OSError:
            pass
    return out


def _run_miri(crate: Path, tree_borrows: bool) -> tuple[bool, str]:
    """Run one reproduction. Returns (miri_rejected_it, combined output)."""
    env_prefix = ["env", "MIRIFLAGS=-Zmiri-tree-borrows"] if tree_borrows else []
    r = subprocess.run(
        [*env_prefix, "cargo", "+nightly", "miri", "run"],
        cwd=crate, capture_output=True, text=True, timeout=600)
    text = (r.stdout or "") + (r.stderr or "")
    return ("Undefined Behavior" in text, text)


def rerun(layout: Layout) -> list[dict]:
    """Re-run every reproduction under scratch, under both borrow models."""
    results = []
    for crate in _repro_crates(layout.scratch):
        rec: dict = {"crate": str(crate.relative_to(layout.scratch))}
        for label, tb in (("stacked_borrows", False), ("tree_borrows", True)):
            try:
                rejected, text = _run_miri(crate, tb)
                rec[label] = {
                    "ub_reported": rejected,
                    # The first UB line is what an advisory would quote, so it
                    # is what a reader wants to diff against the claim.
                    "first_error": next(
                        (l.strip() for l in text.splitlines()
                         if "Undefined Behavior" in l), ""),
                }
            except subprocess.TimeoutExpired:
                rec[label] = {"ub_reported": None, "first_error": "timed out"}
            except OSError as e:
                rec[label] = {"ub_reported": None, "first_error": f"could not run: {e}"}
        results.append(rec)
    return results


# ----------------------------------------------------------- citation check

def citations(layout: Layout) -> list[dict]:
    """Every `file.rs:line` the advisory cites, resolved against the real tree.

    A citation that does not resolve is a hard signal. One that does is printed
    verbatim so a reader can see whether the reduction actually reduces it —
    which is the failure mode a checker cannot decide on its own.
    """
    if not layout.advisory.is_file():
        return []
    text = layout.advisory.read_text()
    seen: set[tuple[str, int]] = set()
    out = []
    for rel, lineno in _CITE.findall(text):
        key = (rel, int(lineno))
        if key in seen:
            continue
        seen.add(key)
        # A citation may be written relative to the crate root or in full.
        cand = [layout.workspace / rel]
        cand += list(layout.workspace.rglob(Path(rel).name))[:1]
        rec = {"cite": f"{rel}:{lineno}", "resolved": False, "source": ""}
        for p in cand:
            if not p.is_file():
                continue
            lines = p.read_text(errors="replace").splitlines()
            if 0 < int(lineno) <= len(lines):
                rec["resolved"] = True
                rec["source"] = lines[int(lineno) - 1].strip()
            break
        out.append(rec)
    return out


# ------------------------------------------------------------------ report

def render(layout: Layout, before: str, after: str, repros: list[dict],
           cites: list[dict]) -> str:
    lines = ["# Harness verification", "",
             "Independently re-derived. The agent did not produce any of the",
             "results below; compare them against what the advisory claims.", ""]

    lines += ["## Audited tree", ""]
    if before == after:
        lines.append(f"Unmodified (`{after}`).")
    else:
        lines += [f"**MODIFIED during the run.** before `{before}`, after `{after}`.",
                  "", "The agent was instructed never to write to the audited",
                  "workspace. Treat every finding as suspect until this is",
                  "explained."]
    lines.append("")

    lines += ["## Reproductions re-run under Miri", ""]
    if not repros:
        lines += ["No cargo crates found under the scratch directory. If the",
                  "advisory claims Miri results, nothing here corroborates them.", ""]
    for r in repros:
        sb, tb = r.get("stacked_borrows", {}), r.get("tree_borrows", {})
        lines += [f"### `{r['crate']}`", "",
                  f"- Stacked Borrows: **{_verdict(sb)}** — {sb.get('first_error') or 'no UB reported'}",
                  f"- Tree Borrows:    **{_verdict(tb)}** — {tb.get('first_error') or 'no UB reported'}",
                  ""]
        if not sb.get("ub_reported") and not tb.get("ub_reported"):
            lines += ["  This reproduction does **not** demonstrate UB. Any finding",
                      "  resting on it is unsupported.", ""]

    lines += ["## Source citations", ""]
    if not cites:
        lines += ["The advisory cites no `file.rs:line` locations, so none could",
                  "be checked.", ""]
    bad = [c for c in cites if not c["resolved"]]
    if bad:
        lines += ["**Unresolvable citations** — these do not exist in the audited tree:", ""]
        lines += [f"- `{c['cite']}`" for c in bad] + [""]
    ok = [c for c in cites if c["resolved"]]
    if ok:
        lines += ["Resolved, printed verbatim. A checker cannot tell whether a",
                  "reduction faithfully reduces these — that is the one thing you",
                  "must read yourself:", ""]
        lines += [f"- `{c['cite']}`  →  `{c['source']}`" for c in ok] + [""]
    return "\n".join(lines)


def _verdict(d: dict) -> str:
    v = d.get("ub_reported")
    return "UB" if v else ("could not run" if v is None else "clean")


def run(layout: Layout, before: str) -> Path:
    after = fingerprint(layout.workspace)
    doc = render(layout, before, after, rerun(layout), citations(layout))
    out = layout.root / "verification.md"
    out.write_text(doc + "\n")
    return out


# WHAT IS STILL MISSING, deliberately recorded rather than papered over.
#
# The failure mode this cannot reach is a reduction that is genuinely unsound
# but does not correspond to the crate. Miri rejects it honestly; the citation
# check shows the cited line; but deciding whether the reduction FAITHFULLY
# reduces that line is reading comprehension, not a check.
#
# The known answer is an adversary: a second agent handed the advisory and the
# crate, rewarded for refuting findings rather than producing them -- show the
# reduction misrepresents the code, or the safe path does not exist, or the
# pattern is guarded upstream. That is a real design and it is not built here,
# because the current tool is deliberately one agent. It is the obvious next
# thing if false positives turn out to be the binding constraint in practice.
