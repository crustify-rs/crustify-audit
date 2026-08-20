"""report.py — render findings as a sendable advisory.

Deterministic: a formatter, never a second opinion. It reorders and renders
what `hunt` produced and adds nothing.

The template is the shape that worked on a real report: what it is, where, the
path from SAFE code (the part that makes it a soundness bug rather than a
style complaint), the miri output under BOTH borrow models, and a concrete fix.
Unverified findings are segregated at the bottom under their own heading rather
than mixed in -- a maintainer must be able to tell at a glance which claims are
backed by a repro they can run.
"""
from __future__ import annotations

from crustify_audit.layout import Layout

_SEV = {"high": 0, "medium": 1, "low": 2}


def render_markdown(layout: Layout, findings: list[dict]) -> str:
    ok = [f for f in findings if f.get("verified")]
    unverified = [f for f in findings if not f.get("verified")]
    ok.sort(key=lambda f: _SEV.get(f.get("severity", "low"), 3))

    out: list[str] = [
        f"# Soundness findings — `{layout.workspace.name}`",
        "",
        f"**Workspace:** `{layout.workspace}`",
        f"**Findings:** {len(ok)} verified, {len(unverified)} unverified",
        "",
        "Each verified finding below carries a standalone reproduction that "
        "Miri rejects under **both** Stacked Borrows and Tree Borrows. The "
        "reproductions reduce the pattern rather than building the crate, so "
        "they run without the crate's system dependencies.",
        "",
        "---",
        "",
    ]
    for f in ok:
        out += _one(f)
    if unverified:
        out += [
            "## Unverified",
            "",
            "Reported for completeness. These are **hypotheses** — no "
            "reproduction was produced, so treat them as leads rather than "
            "findings.",
            "",
        ]
        for f in unverified:
            out += _one(f, brief=True)
    return "\n".join(out)


def _one(f: dict, *, brief: bool = False) -> list[str]:
    sev = f.get("severity", "?")
    out = [f"## {f.get('id', '?')} — {f.get('title', 'untitled')}", "",
           f"**Severity:** {sev}  |  **Class:** {f.get('class', '?')}", ""]
    if f.get("already_reported"):
        out += [f"> Possibly already reported: {f['already_reported']}", ""]
    out += [f.get("explanation", ""), ""]

    if f.get("sites"):
        out += ["**Sites**", ""]
        out += [f"- `{s.get('file')}:{s.get('line')}` — {s.get('what', '')}"
                for s in f["sites"]] + [""]
    if f.get("safe_path"):
        out += ["**Reachable from safe code**", ""]
        out += [f"- `{s.get('fn')}` — `{s.get('file')}:{s.get('line')}`"
                + (f" ({s['note']})" if s.get("note") else "")
                for s in f["safe_path"]] + [""]
    if brief:
        return out + ["---", ""]

    miri = f.get("miri") or {}
    if miri:
        out += ["**Miri**", ""]
        for label, key in (("Stacked Borrows", "stacked_borrows"),
                           ("Tree Borrows", "tree_borrows")):
            if miri.get(key):
                out += [f"{label}:", "", "```", miri[key].strip(), "```", ""]
    if f.get("suggested_fix"):
        out += ["**Suggested fix**", "", f["suggested_fix"], ""]
    return out + ["---", ""]
