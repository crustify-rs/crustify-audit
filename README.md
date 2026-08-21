# crustify-audit

Find soundness bugs and safety trade-offs in Rust code that wraps C.

Two halves, and the split is the point:

| | | |
|---|---|---|
| `unsafe` | **deterministic** | a `syn` pass over the crate's unsafe surface. Counts, plus a ranked list of sites worth a closer look. No LLM, no network, no build. Same tree, same bytes. |
| `ub` | **agentic** | one agent hunting undefined behaviour reachable from safe code. It runs the `unsafe` pass itself, picks its own instruments, and authors the advisories. |

Separate verbs, not one command with a flag, so a caller always knows whether
the answer in front of them is reproducible.

```sh
crustify-audit /path/to/crate unsafe      # deterministic, standalone
crustify-audit /path/to/crate ub          # agentic; runs the pass itself
```

Artifacts land in `<crate>/crustify/` — `advisories/`, `notes/`, `scratch/`,
`logs/`, `unsafe.json`. Same directory name crustify-cli uses, so auditing a
campaign target puts the audit beside the campaign. `--out` redirects it all
when the subject must stay pristine.

The agent authors the advisory itself, in prose, because the judgement it is
there to exercise is the part a filled-in template would flatten.

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

## Triage

**An empty `crustify/advisories/` means nothing was demonstrated.** The agent
writes an advisory only when it actually crashed something — one file per bug,
named after the bug. `crustify/notes/` holds one note per lead it chased,
whether or not that lead panned out, so a clean audit is distinguishable from an
agent that died halfway.

Runs accumulate: the agent reads both directories before starting, so a second
run extends the record — skipping a cleared lead, adding a route to an existing
advisory — instead of paying to re-derive it.

For each advisory, two questions:

| | who answers | if no |
|---|---|---|
| 1. Does the reproduction actually fail? | `cd` into it and run `cargo +nightly miri run` | discard |
| 2. Does the reproduction match the real code? | read it against the source line it cites | discard |

Survives both → real. Both are a couple of minutes, and you only reach them
when an advisory exists at all.

Question 2 disappears entirely for a **Tier A** finding, where the reproduction
depends on the audited crate and calls its real public API. There is no fidelity
question when the crash happened in their code. Tier A needs the crate to build,
which for an FFI wrapper often it does not — so most findings are **Tier B**, a
reduction mirroring the crate's types, and the advisory is required to say which
it is and to argue the reduction is faithful.

## Instruments

Miri and the sanitizers answer different questions, and the agent picks:

| | role | reaches | needs |
|---|---|---|---|
| **Miri** | verification — rules on a reduction you already have | Rust-side UB: aliasing under Stacked *and* Tree Borrows, invalid values, uninit, alignment | nothing built |
| **ASan / LSan** | discovery — run real code, see what fires | use-after-free, double-free, overflow, leaks **across** the FFI seam | a working build **and** a workload |
| **UBSan** | discovery | integer overflow, misalignment, bad shifts and casts *inside* the C library | the C dep rebuilt with `-fsanitize=undefined` |
| **TSan** | discovery | data races across the boundary | build + concurrent tests |

The split matters because **Miri cannot execute C**. It stops at every
`extern "C"` call — which, for a wrapper crate, is where the interesting
behaviour lives. `-Zmiri-native-lib` partially bridges it but is experimental,
Unix-only and fragile. Sanitizers are how you see the other side of the seam.

The cost is that sanitizers need the crate to *build*, which for an FFI wrapper
means its system dependencies must be present — often the reason a crate is
worth auditing is the reason you cannot build it. And they only report code that
runs, so they need the crate's own tests as a workload. `unsafe` deliberately
needs no build at all; `ub` uses whatever happens to be available and is asked
to say in the advisory what it could not check.

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

`#[cfg(test)]` items are skipped by the walk and subtracted from `code_lines`,
so both sides of a ratio measure the code a normal build compiles. An inline
`mod tests` would otherwise put its lines in the denominator and its `unsafe`
in the numerator.

The figures that *are* categorical are the ones measuring what crosses the
public API boundary, where the caller has to discharge the obligation:

- `pub_unsafe_fns` — each is an invariant pushed onto every user
- `raw_ptr_in_pub_sig` — each is a lifetime the type system is not tracking

Those are the comparisons worth making between two wrappers over the same C
library.

## Status

Working end to end. `ub` has run against git2-rs, rust-openssl and
rust-ffmpeg, each producing an advisory and a set of notes.

- The scanner is **syntactic**, and reads the source as written: it sees no
  macro-generated code, and resolves no types or crate boundaries. The
  motivating bug is a syntactic shape, and `syn` finds it without needing the
  crate to compile — which is what lets the pass run against a wrapper whose C
  dependencies are absent. `crustify-cli audit` carries a rustc driver over
  HIR and typeck for the cases that need resolution; the two measure different
  populations and their numbers are not comparable.
- One agent, by design. Splitting the hunt across parallel agents is worth it
  once a single one is demonstrably good.
- The agent both produces findings and checks them.

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
