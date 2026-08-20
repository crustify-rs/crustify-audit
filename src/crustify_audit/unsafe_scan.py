"""unsafe_scan.py — the DETERMINISTIC half, behind `crustify-audit … unsafe`.

Drives the `syn`-based scanner over a workspace and writes ``unsafe.json``.

WHY THIS IS A SEPARATE PHASE, AND NOT SOMETHING THE AGENT DOES.

The agent could grep. It should not. Three reasons, all learned from the C side
of crustify:

  1. **Reproducibility.** The composer's output is a pure function of the source
     tree. Two runs agree, and a diff between them is a real change in the
     crate, not a change in the model's mood. Anything an agent produces is a
     sample; anything the composer produces is a fact.
  2. **Budget.** Enumeration is the cheap half and reasoning is the expensive
     half. Handing the agent a ranked list of 40 sites instead of a 20k-line
     crate spends its context on the part only it can do.
  3. **Falsifiability.** A finding cites a seed site. If the seed list is
     deterministic, a reviewer can check that the agent looked where it claims
     to have looked.

WHAT THE SEED IS NOT. Every site carries a ``suspicion`` score, and it is
ordering only. The composer has no idea whether a `transmute_copy` is sound --
plenty are. Ranking exists so the agent starts at the most likely end of the
list, not so it can skip the rest.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from crustify_audit.layout import Layout

_SCANNER_CRATE = Path(__file__).resolve().parents[2] / "scanner"


def _scanner_bin() -> Path:
    """Build the scanner on first use and return its path.

    Built rather than vendored as a binary: it is a few hundred lines and one
    `syn` dependency, and a checked-in binary is a supply-chain object nobody
    wants to audit.
    """
    bin_path = _SCANNER_CRATE / "target" / "release" / "crustify-audit-scanner"
    # cargo is only needed to BUILD it. Checking first would refuse to run on a
    # machine that already has the binary, which is the common case after the
    # first run and the whole case in a prebuilt container.
    if not bin_path.is_file():
        if shutil.which("cargo") is None:
            raise SystemExit(
                "metrics: the scanner is not built and `cargo` is not on PATH. "
                "Install a Rust toolchain, or build it elsewhere and copy it to "
                f"{bin_path}.")
        print("[crustify-audit] building the scanner (first run only)…")
        r = subprocess.run(
            ["cargo", "build", "--release"], cwd=_SCANNER_CRATE,
            capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"metrics: scanner build failed:\n{r.stdout}\n{r.stderr}")
    return bin_path


def compose(layout: Layout) -> dict:
    """Scan the workspace and return the metrics document."""
    if not layout.is_cargo_workspace():
        raise SystemExit(
            f"metrics: no Cargo.toml at {layout.workspace}. crustify-audit "
            f"audits a cargo workspace — point it at the crate root.")
    out = subprocess.run(
        [str(_scanner_bin()), str(layout.workspace)],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"metrics: scanner failed:\n{out.stderr}")
    doc = json.loads(out.stdout)
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
    c = doc.get("counts", {})
    pub = c.get("pub_fns") or 0
    loc = c.get("code_lines") or 0
    ub = c.get("unsafe_blocks") or 0
    return {
        # The two that matter, and the two the README makes claims about.
        "pub_unsafe_fn_ratio": round((c.get("pub_unsafe_fns") or 0) / pub, 4) if pub else None,
        "raw_ptr_pub_sig_ratio": round((c.get("raw_ptr_in_pub_sig") or 0) / pub, 4) if pub else None,
        # Context, explicitly NOT a quality score. See the docstring.
        "loc_per_unsafe_block": round(loc / ub, 1) if ub else None,
    }


def write(layout: Layout) -> Path:
    layout.root.mkdir(parents=True, exist_ok=True)
    doc = compose(layout)
    layout.scan.write_text(json.dumps(doc, indent=2) + "\n")
    return layout.scan


def summarize(doc: dict) -> str:
    c = doc.get("counts", {})
    d = doc.get("derived", {})
    sites = doc.get("sites", [])
    top = [s for s in sites if s.get("suspicion", 0) >= 70]
    lines = [
        f"  files {c.get('files')}   code lines {c.get('code_lines')}",
        f"  unsafe blocks        {c.get('unsafe_blocks')}"
        f"   (1 per {d.get('loc_per_unsafe_block')} lines — context, not a score)",
        f"  pub unsafe fn        {c.get('pub_unsafe_fns')} of {c.get('pub_fns')} pub fns"
        f"   ({d.get('pub_unsafe_fn_ratio')})",
        f"  raw ptr in pub sig   {c.get('raw_ptr_in_pub_sig')}"
        f"   ({d.get('raw_ptr_pub_sig_ratio')})",
        f"  transmute sites      {c.get('transmutes')}",
        f"  Deref / DerefMut     {c.get('deref_impls')} / {c.get('deref_mut_impls')}",
        f"  mixed-ref structs    {len(doc.get('mixed_ref_structs') or [])}",
        "",
        f"  {len(sites)} seed sites, {len(top)} at suspicion >= 70",
    ]
    for s in sites[:8]:
        lines.append(f"    [{s['suspicion']:>2}] {s['file']}:{s['line']}  "
                     f"{s['kind']}  ({s['item']})")
    if len(sites) > 8:
        lines.append(f"    … {len(sites) - 8} more")
    return "\n".join(lines)
