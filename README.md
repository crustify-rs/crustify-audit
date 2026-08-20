# crustify-audit

Find soundness bugs and safety trade-offs in Rust code that wraps C.

Two halves, and the split is the point:

| | | |
|---|---|---|
| `metrics` | **deterministic** | a `syn` pass over the crate. Counts, plus a ranked list of sites worth a closer look. No LLM, no network, no build. Same tree, same bytes. |
| `hunt` | **agentic** | one agent over that seed, hunting undefined behaviour reachable from safe code. Every finding must carry a reproduction Miri rejects. |
| `report` | deterministic | renders findings as a sendable advisory. A formatter, not a second opinion. |

They are separate verbs, not one command with a flag, so a caller always knows
whether the answer in front of them is reproducible.

```sh
crustify-audit /path/to/crate metrics
crustify-audit /path/to/crate hunt --model anthropic/claude-opus-4-8
crustify-audit /path/to/crate report > advisory.md
```

The subject is an **ordinary cargo workspace**. No `crustify/` directory, no
campaign, no CodeQL database — that is what makes this a separate binary from
`crustify-cli` rather than another subcommand, since both crustify binaries
mandate `<repo_root> <target>` and refuse to run without campaign artifacts.

## Why the deterministic half exists

The agent could grep. It should not:

- **Reproducibility.** The composer's output is a pure function of the source
  tree. A diff between two runs is a change in the crate, not a change in the
  model's mood.
- **Budget.** Enumeration is cheap and reasoning is expensive. Handing the agent
  a ranked list spends its context on the part only it can do.
- **Falsifiability.** A finding cites a seed site, so a reviewer can check the
  agent looked where it says it looked.

The `suspicion` score is **ordering only**. The scanner cannot tell a sound
`transmute_copy` from an unsound one — plenty are fine. A low score is not a
clearance.

## What it looks for

The shapes that are usually soundness bugs in C wrappers:

1. **Aliasing** — a `&mut T` and a `&T` to the same object live at once, usually
   laundered through `transmute_copy`.
2. **Lending iterators** — `Item` borrowing the iterator's `'a` rather than
   `&mut self`, so `collect()` yields several `&mut` to one object.
3. **Unvalidated integer→enum transmutes** of values that came from C.
4. **Lifetimes decoupled** from the borrow they came from.
5. **`Deref`/`DerefMut` exposure** that `mem::swap` can break invariants through.
6. **`Send`/`Sync` asserted** over thread-affine C state.

Mixed-reference structs are resolved **transitively**, which is load-bearing.
The bug this tool was built after holds its exclusive reference directly and
reaches its shared one a level down through another struct; a direct-fields-only
check misses it entirely.

## Evidence standard

A finding you cannot demonstrate is a hypothesis. Every entry must carry a
standalone reproduction that Miri rejects under **both** Stacked Borrows and
Tree Borrows, or be recorded `verified: false` with an explanation.

Both models matter: Miri itself flags Stacked Borrows as experimental, so a
finding Tree Borrows also rejects is much harder to argue with.

Reproductions *reduce* the pattern rather than building the crate — the crates
most worth auditing need system libraries the auditor may not have.

Three verified findings beat twenty plausible ones. A false positive costs a
maintainer more than a missed bug costs you.

## What the numbers mean, and don't

`metrics` reports unsafe-block counts because they are context, **not a quality
score**. A wrapper over C must contain unsafe, and folding 600 small audited
blocks into 200 large ones improves the number while making the crate worse.

The figures that *are* categorical are the ones measuring what crosses the
public API boundary, where the caller has to discharge the obligation:

- `pub_unsafe_fns` — each is an invariant pushed onto every user
- `raw_ptr_in_pub_sig` — each is a lifetime the type system is not tracking

Those are the comparisons worth making between two wrappers over the same C
library.

## Status

Draft. Working end to end; the pieces that need the most attention next:

- The scanner is **syntactic**. A rustc driver would be more precise and should
  come later — but the motivating bug is a syntactic shape, and `syn` finds it
  without needing the crate to compile.
- Miri verification is the agent's job today. A deterministic `verify` stage
  that re-runs every recorded repro and refuses to report unconfirmed findings
  is the obvious next step.
- One agent, by design. Splitting the hunt across parallel agents is only worth
  it once a single one is demonstrably good.

## Layout

```
scanner/                 the deterministic pass (Rust, syn)
src/crustify_audit/
  cli.py                 metrics / hunt / report
  layout.py              artifact paths; the plain-cargo-workspace contract
  metrics.py             composer: drives the scanner, derives ratios
  report.py              findings -> markdown advisory
  models.py              <provider>/<model> -> backend
  agentlog.py            per-agent transcript + usage
  agents/base.py         the single audit agent
  agents/backends/       claude / codex CLI drivers
  prompts/hunt.md        the hunt prompt
```
