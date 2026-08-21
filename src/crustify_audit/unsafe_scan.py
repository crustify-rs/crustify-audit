"""unsafe_scan.py — the DETERMINISTIC half, behind `crustify-audit … unsafe`.

Writes ``unsafe.json``: the rustc driver's metrics for the workspace, and the
ratios worth comparing crates on.

WHY THIS IS NOT SOMETHING THE AGENT DOES. Not because an agent could not count
— because a count it produced would be a sample. The composer's output is a
pure function of the source tree, so two runs agree and a diff between them is
a change in the crate rather than a change in the model's mood. That is what
makes a number quotable.

Finding what is WORTH LOOKING AT is the opposite kind of work, and it belongs
to the agent: it reads the code, forms its own suspicions, and defends them.
"""
from __future__ import annotations

import json
from pathlib import Path

from crustify_audit import driver
from crustify_audit.layout import Layout


def compose(layout: Layout) -> dict:
    """Scan the workspace and return the metrics document."""
    if not layout.is_cargo_workspace():
        raise SystemExit(
            f"metrics: no Cargo.toml at {layout.workspace}. crustify-audit "
            f"audits a cargo workspace — point it at the crate root.")
    doc: dict = {"crate_path": str(layout.workspace)}
    try:
        doc["counts"] = driver.measure(layout.workspace)
        doc["counts_unavailable"] = None
    except driver.DriverUnavailable as e:
        # No counts rather than substitute ones: see driver.py.
        doc["counts"] = None
        doc["counts_unavailable"] = str(e)
        print(f"[crustify-audit] no counts: {e}".rstrip())
    doc["derived"] = _derive(doc)
    return doc


def _derive(doc: dict) -> dict:
    """Ratios a reader actually compares crates on.

    Absolute unsafe-block counts are close to meaningless across crates of
    different sizes, and *lower is not automatically better*: a wrapper over C
    must contain unsafe, and folding 600 small audited blocks into 200 large
    ones makes the crate worse while improving the number. So the headline
    figures here are the ones that ARE categorical — how much unsafety the
    crate pushes across its public API boundary, where the caller has to
    discharge it.
    """
    c = doc.get("counts") or {}
    if not c:
        return {}
    loc = c.get("code_lines") or 0
    ub = c.get("unsafe_blocks") or 0
    fns = c.get("unsafe_fns") or 0
    positions = (c.get("raw_ptr_args") or 0) + (c.get("raw_ptr_rets") or 0)
    seam = c.get("raw_ptr_seam") or 0
    return {
        # Categorical: an obligation pushed onto callers, and one the seam does
        # not excuse.
        "unsafe_fn_pub_ratio": round((c.get("unsafe_fns_pub") or 0) / fns, 4) if fns else None,
        "unsafe_fn_smell": fns - (c.get("unsafe_fns_seam") or 0),
        "raw_ptr_smell": positions - seam,
        "raw_ptr_seam_ratio": round(seam / positions, 4) if positions else None,
        # Context, explicitly NOT a quality score. See the docstring.
        "unsafe_loc_ratio": round((c.get("unsafe_block_code_lines") or 0) / loc, 4) if loc else None,
        "loc_per_unsafe_block": round(loc / ub, 1) if ub else None,
    }


def write(layout: Layout) -> Path:
    layout.root.mkdir(parents=True, exist_ok=True)
    doc = compose(layout)
    layout.scan.write_text(json.dumps(doc, indent=2) + "\n")
    return layout.scan


def summarize(doc: dict) -> str:
    c = doc.get("counts") or {}
    d = doc.get("derived", {})
    lines: list[str] = []
    if c:
        lines += [
            f"  code lines           {c.get('code_lines')}",
            f"  unsafe blocks        {c.get('unsafe_blocks')}"
            f"   ({d.get('unsafe_loc_ratio')} of code lines — context, not a score)",
            f"  unsafe fn            {c.get('unsafe_fns')}"
            f"   ({c.get('unsafe_fns_pub')} pub, {c.get('unsafe_fns_seam')} at the seam)",
            f"  raw ptr positions    {(c.get('raw_ptr_args') or 0) + (c.get('raw_ptr_rets') or 0)}"
            f"   ({c.get('raw_ptr_seam')} sanctioned, smell {d.get('raw_ptr_smell')})",
            f"  ref to layout type   {c.get('ref_to_type_wrapper')}"
            f"   of {c.get('wrapper_newtypes')} layout newtypes — target 0",
            f"  ffi calls            {c.get('ffi_calls')}",
        ]
    else:
        lines.append(f"  counts               unavailable — "
                     f"{doc.get('counts_unavailable')}")
    return "\n".join(lines)
