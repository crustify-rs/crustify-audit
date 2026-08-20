# crustify-audit

Find soundness bugs and safety trade-offs in Rust code that wraps C.

Two halves, and the split is the point:

| | | |
|---|---|---|
| `unsafe` | **deterministic** | a `syn` pass over the crate's unsafe surface. Counts, plus a ranked list of sites worth a closer look. No LLM, no network, no build. Same tree, same bytes. |
| `ub` | **agentic** | one agent over that seed, hunting undefined behaviour reachable from safe code — and authoring the advisory itself. |

Separate verbs, not one command with a flag, so a caller always knows whether
the answer in front of them is reproducible.

```sh
crustify-audit /path/to/crate unsafe
crustify-audit /path/to/crate ub --model anthropic/claude-opus-4-8
```

There is no `report` verb. The agent writes the advisory; a template the
harness fills in would flatten exactly the judgement the agent is there to
exercise.

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
- **Traceability.** A finding cites a seed site, so a reviewer can check the
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

## Where the line sits

The harness runs the scan, hands the agent a seed and a writable directory, and
starts it. Everything after that — what to investigate, how to reduce it, what a
reproduction looks like, how to structure the advisory — is the agent's.

The prompt says what a good report looks like and why Miri under both borrow
models is worth more than Miri under one. It does not hand over a form to fill
in. A schema is a poor substitute for telling an author what makes a report
land, and the parts of this job worth paying a model for are exactly the parts a
schema cannot express.

## What the numbers mean, and don't

`unsafe` reports unsafe-block counts because they are context, **not a quality
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
- No `ub` run has happened yet, so the prompt is untested against real agent
  output. That is the next thing to find out.
- One agent, by design. Splitting the hunt across parallel agents is only worth
  it once a single one is demonstrably good.
- The agent both produces findings and checks them. A deterministic re-run of
  whatever reproductions it left behind would be worth having — but it has to
  discover their shape rather than mandate it, or we are back to a schema.

## Layout

```
scanner/                 the deterministic pass (Rust, syn)
src/crustify_audit/
  cli.py                 unsafe / ub
  layout.py              artifact paths; the plain-cargo-workspace contract
  unsafe_scan.py         drives the scanner, derives ratios
  models.py              <provider>/<model> -> backend
  agentlog.py            per-agent transcript + usage
  agents/base.py         the single audit agent
  agents/backends/       claude / codex CLI drivers
  prompts/ub.md          the hunt prompt
```
