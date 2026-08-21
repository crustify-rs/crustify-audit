"""cli.py — `crustify-audit`.

    crustify-audit <workspace> unsafe [--json] [--out DIR]
    crustify-audit <workspace> ub     [--model M] [--focus F]

TWO VERBS, AND THE SPLIT IS THE POINT.

`unsafe` is deterministic: a `syn` pass over the crate's unsafe surface. No LLM,
no network, no build. Two runs over one tree agree exactly, so a diff between
them is a change in the crate.

`ub` is agentic: one agent, seeded by `unsafe`, hunting undefined behaviour
reachable from safe code and authoring the advisory itself.

Separate verbs rather than one command with a flag, because a caller must always
know whether the answer in front of them is reproducible. Hiding that behind a
flag makes "did an LLM decide this?" unanswerable from the command line.

There is no `report` verb. Writing the advisory is the agent's job, not a
formatter's -- a template the harness fills in would flatten exactly the
judgement the agent is there to exercise.

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
                    "`unsafe` is deterministic; `ub` drives one LLM agent over "
                    "its output.")
    p.add_argument("workspace",
                   help="Path to the cargo workspace to audit. An ORDINARY crate — "
                        "no crustify/ directory, campaign or CodeQL database needed.")
    p.add_argument("--out", default=None, metavar="DIR",
                   help="Where artifacts go (default: <workspace>/crustify/). "
                        "Point elsewhere to leave the audited tree untouched.")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser(
        "unsafe",
        help="DETERMINISTIC unsafe-surface scan. No LLM.",
        description="Parse every .rs file and emit counts plus a ranked list of "
                    "sites worth a closer look. Reproducible: same tree, same "
                    "bytes. The ranking is ORDERING ONLY — the scanner cannot "
                    "tell a sound transmute from an unsound one, and a low score "
                    "is not a clearance.")
    m.add_argument("--json", action="store_true",
                   help="Print the document instead of a summary.")

    h = sub.add_parser(
        "ub",
        help="AGENTIC hunt for undefined behaviour. Costs money.",
        description="Drive ONE agent hunting UB reachable from safe code. It "
                    "runs the `unsafe` static pass itself, as often and as "
                    "narrowly as it wants — no prior run is required. The agent builds its own "
                    "reproductions, checks them under miri, and writes the "
                    "advisory itself — the harness supplies a seed and a "
                    "scratch directory and nothing else. It never writes to the "
                    "audited workspace outside its `crustify/` directory. It "
                    "writes one note per lead investigated into crustify/notes/ "
                    "and one advisory per CONFIRMED bug into "
                    "crustify/advisories/ — an advisory means something actually "
                    "crashed. Runs ACCUMULATE: there is no skip, and the agent "
                    "reads what earlier runs left before starting, so a second "
                    "run extends the record instead of re-deriving it.")
    h.add_argument("--model", default=None, metavar="PROVIDER/MODEL",
                   help="e.g. anthropic/claude-opus-5, openai/gpt-5.6. The "
                        "provider prefix selects the backend and is mandatory.")
    h.add_argument("--focus", default=None, metavar="TEXT",
                   help="Narrow the hunt, e.g. 'the format module' or 'iterators'.")
    h.add_argument("--timeout", type=int, default=30, metavar="MINUTES",
                   dest="timeout",
                   help="Wall-clock ceiling for ONE agent (default 30, 0 "
                        "disables). Set it to the whole budget you intend to "
                        "spend — do NOT chunk a budget into several shorter "
                        "runs, which just terminates a working agent early. "
                        "Successive runs are for ACCUMULATING over time, not "
                        "for splitting one sitting. This is the only cap that "
                        "works under subscription auth — `--max-budget-usd` "
                        "meters API-call spend, of which there is none, and the "
                        "CLI has no turn limit. A terminated agent may have "
                        "written a partial advisory or none: absence of an "
                        "advisory after a timeout does NOT mean it found "
                        "nothing.")
    return p


def _cmd_unsafe(layout: Layout, args) -> int:
    from crustify_audit import unsafe_scan as M
    path = M.write(layout)
    doc = json.loads(path.read_text())
    if args.json:
        print(json.dumps(doc, indent=2))
    else:
        print(f"[crustify-audit] unsafe -> {path}\n")
        print(M.summarize(doc))
        print("\n  Ranking is ordering only. A low score is not a clearance.")
        print(f"  Next: crustify-audit {layout.workspace} ub")
    return 0


def _cmd_ub(layout: Layout, args) -> int:
    from crustify_audit.agents.base import AuditAgent

    # A warning, not a gate: whether miri is installed is mechanism, and the
    # agent may still have something useful to say without it. But it should be
    # said out loud, because an advisory written without miri is a different
    # kind of document.
    if not AuditAgent.miri_available():
        print("[crustify-audit] warning: `cargo +nightly miri` is not available, "
              "so the agent cannot check its own reproductions. Install with: "
              "rustup component add miri --toolchain nightly",
              file=sys.stderr)
    agent = AuditAgent(layout, model=args.model, focus=args.focus,
                       timeout_s=(args.timeout * 60) or None)

    # There is no skip: runs accumulate. Say what is already on disk so the
    # caller knows this run is adding to a record rather than starting one --
    # and knows it is about to spend either way.
    was = agent.counts()
    if any(was):
        print(f"[crustify-audit] existing record: {was[0]} advisor"
              f"{'y' if was[0] == 1 else 'ies'}, {was[1]} lead note(s). "
              f"The agent reads these before it starts.")

    now = agent.run()
    new_adv, new_leads = now[0] - was[0], now[1] - was[1]

    print(f"[crustify-audit] advisories : {now[0]} ({new_adv:+d})  {layout.advisories}")
    print(f"[crustify-audit] lead notes : {now[1]} ({new_leads:+d})  {layout.notes}")
    print(f"[crustify-audit] repros     : {layout.scratch}")
    if now[0] == 0:
        print("\n  No advisories: nothing was demonstrated. That is a result, "
              "not a failure —\n  read the lead notes to see what was judged.")
    else:
        print("\n  Triage each advisory: run its reproduction yourself, then "
              "check it matches\n  the source line it cites. Both hold -> real.")
    return 0


def main() -> None:
    args = build_parser().parse_args()
    ws = Path(args.workspace).resolve()
    if not ws.is_dir():
        print(f"error: workspace does not exist: {ws}", file=sys.stderr)
        raise SystemExit(2)
    layout = Layout(ws, out=args.out)
    fn = {"unsafe": _cmd_unsafe, "ub": _cmd_ub}
    raise SystemExit(fn[args.command](layout, args))


if __name__ == "__main__":
    main()
