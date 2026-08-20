"""cli.py — `crustify-audit`.

    crustify-audit <workspace> metrics [--json] [--out DIR]
    crustify-audit <workspace> hunt    [--model M] [--focus F] [--max-findings N]
    crustify-audit <workspace> report  [--format md|json]

THE SPLIT, AND WHY IT IS VISIBLE IN THE VERB.

`metrics` is deterministic: a `syn` pass, no LLM, no network. Two runs over one
tree agree exactly, and a diff between them is a change in the crate.

`hunt` is agentic: one agent, seeded by `metrics`, producing findings each
carrying a miri-verified reproduction.

They are separate verbs rather than one `audit` command with a flag, because a
caller must always know whether the answer they are holding is reproducible.
crustify-cli's `audit` conflates nothing today because it has no agent; the
moment one exists, hiding the distinction behind a flag makes "did an LLM
decide this?" unanswerable from the command line.

`report` renders what `hunt` produced into something sendable. Deterministic
again -- it is a formatter, not a second opinion.

WHY A SEPARATE BINARY FROM crustify-cli. Both crustify binaries mandate
``<repo_root> <target>`` and refuse to run without a ``crustify/`` directory.
This tool's most valuable use is auditing a crate that has never heard of
crustify. That is a different CLI contract, not a new subcommand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crustify_audit.layout import Layout


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crustify-audit",
        description="Find soundness bugs and safety trade-offs in Rust that wraps C. "
                    "`metrics` is deterministic; `hunt` drives one LLM agent over its "
                    "output; `report` renders the result.")
    p.add_argument("workspace",
                   help="Path to the cargo workspace to audit. An ORDINARY crate — "
                        "no crustify/ directory, campaign or CodeQL database needed.")
    p.add_argument("--out", default=None, metavar="DIR",
                   help="Where artifacts go (default: <workspace>/.crustify-audit/). "
                        "Point elsewhere to leave the audited tree untouched.")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser(
        "metrics",
        help="DETERMINISTIC unsafe-surface scan. No LLM.",
        description="Parse every .rs file and emit counts plus a ranked list of "
                    "sites worth a closer look. Reproducible: same tree, same "
                    "bytes. The ranking is ORDERING ONLY — the scanner cannot "
                    "tell a sound transmute from an unsound one, and a low score "
                    "is not a clearance.")
    m.add_argument("--json", action="store_true",
                   help="Print the document instead of a summary.")

    h = sub.add_parser(
        "hunt",
        help="AGENTIC UB hunt over the metrics seed. Costs money.",
        description="Drive ONE agent over the seed from `metrics`. Every finding "
                    "it reports must carry a standalone reproduction that miri "
                    "rejects under both Stacked and Tree Borrows, or be marked "
                    "unverified. The agent never writes to the audited "
                    "workspace. Existence of findings.json is the done signal, "
                    "so a re-run is a no-op — delete it to hunt again.")
    h.add_argument("--model", default=None, metavar="PROVIDER/MODEL",
                   help="e.g. anthropic/claude-opus-4-8, openai/gpt-5.6. The "
                        "provider prefix selects the backend and is mandatory.")
    h.add_argument("--focus", default=None, metavar="TEXT",
                   help="Narrow the hunt, e.g. 'the format module' or 'iterators'.")
    h.add_argument("--max-findings", type=int, default=10, dest="max_findings",
                   help="Ceiling, not a target (default 10).")

    r = sub.add_parser(
        "report",
        help="Render findings.json as a sendable advisory.",
        description="Deterministic formatter over what `hunt` produced. Does not "
                    "re-judge anything.")
    r.add_argument("--format", default="md", choices=("md", "json"),
                   dest="fmt")
    return p


def _cmd_metrics(layout: Layout, args) -> int:
    from crustify_audit import metrics as M
    path = M.write(layout)
    doc = json.loads(path.read_text())
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(f"[crustify-audit] metrics -> {path}\n")
        print(M.summarize(doc))
        print("\n  Ranking is ordering only. A low score is not a clearance.")
        print(f"  Next: crustify-audit {layout.workspace} hunt")
    return 0


def _cmd_hunt(layout: Layout, args) -> int:
    from crustify_audit.agents.base import AuditAgent, load_findings

    if not AuditAgent.miri_available():
        print("[crustify-audit] warning: `cargo +nightly miri` is not available. "
              "The agent cannot verify its findings, so everything it reports "
              "will be unverified. Install with: rustup component add miri "
              "--toolchain nightly", file=sys.stderr)
    agent = AuditAgent(layout, model=args.model, focus=args.focus,
                       max_findings=args.max_findings)
    out = agent.run()
    if out is None:
        print("[crustify-audit] the agent wrote no findings file. Check "
              f"{layout.logs} for its transcript.", file=sys.stderr)
        return 1
    found = load_findings(out)
    verified = sum(1 for f in found if f.get("verified"))
    print(f"[crustify-audit] {len(found)} finding(s), {verified} verified -> {out}")
    return 0


def _cmd_report(layout: Layout, args) -> int:
    from crustify_audit.agents.base import load_findings
    from crustify_audit.report import render_markdown

    found = load_findings(layout.findings)
    if not found:
        print(f"[crustify-audit] no findings at {layout.findings}.", file=sys.stderr)
        return 1
    if args.fmt == "json":
        print(json.dumps(found, indent=2))
    else:
        print(render_markdown(layout, found))
    return 0


def main() -> None:
    args = build_parser().parse_args()
    ws = Path(args.workspace).resolve()
    if not ws.is_dir():
        print(f"error: workspace does not exist: {ws}", file=sys.stderr)
        raise SystemExit(2)
    layout = Layout(ws, out=args.out)
    fn = {"metrics": _cmd_metrics, "hunt": _cmd_hunt, "report": _cmd_report}
    raise SystemExit(fn[args.command](layout, args))


if __name__ == "__main__":
    main()
