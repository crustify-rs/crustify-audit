# crustify-audit

Find soundness bugs and safety trade-offs in Rust code that wraps C.

Two halves, and the split is the point:

| | | |
|---|---|---|
| `unsafe` | **deterministic** | a rustc driver over HIR and typeck: how much unsafety the crate has and where its boundary sits. No LLM, no network. Same tree, same bytes. |
| `ub` | **agentic** | one agent reading the crate to find what is worth looking at, hunting undefined behaviour reachable from safe code, picking its own instruments and authoring the advisories. |

Separate verbs, not one command with a flag, so a caller always knows whether
the answer in front of them is reproducible.

```sh
crustify-audit /path/to/crate unsafe      # deterministic, standalone
crustify-audit /path/to/crate ub          # agentic; runs the pass itself
```

Artifacts land in `<crate>/crustify/audit/` — `advisories/`, `notes/`, `tmp/`,
`logs/`, `unsafe.json`. Under the directory crustify-cli uses, so
auditing a campaign target puts the audit beside the campaign, in its own
subdirectory so the two tools' artifacts stay separable.

The agent authors the advisory itself, in prose, because the judgement it is
there to exercise is the part a filled-in template would flatten.

The subject is an **ordinary repository**. The crate is its root, or
`crustify/rust` if it has been through a campaign — nothing else is required:
no CodeQL database, no scope config, no campaign artifacts. That is what makes
this a separate binary from `crustify-cli` rather than another subcommand,
since both crustify binaries mandate `<repo_root> <target>` and refuse to run
without them.

## Usage

Python >= 3.13. `pip install -e .` puts `crustify-audit` on PATH; without an
install, `PYTHONPATH=src python3 -m crustify_audit.cli` takes the same
arguments.

```sh
crustify-audit <repo> unsafe [--json]
crustify-audit <repo> ub     [--model PROVIDER/MODEL] [--billing B] [--timeout MIN]
```

| flag | verb | default | effect |
|---|---|---|---|
| `<repo>` | both | — | repository to audit; the crate is its root, or `crustify/rust` |
| `--json` | `unsafe` | off | print `unsafe.json` to stdout instead of the human summary. The file is written either way |
| `--model PROVIDER/MODEL` | `ub` | backend default | e.g. `anthropic/claude-opus-5`, `openai/gpt-5.6`; the prefix selects the backend and is mandatory |
| `--billing subscription\|api` | `ub` | `subscription` | how the provider CLI authenticates. `api` adds `--bare` (claude) or an env-key provider block (codex) — neither uses a key in the environment without it; a missing key fails at launch |
| `--timeout MIN` | `ub` | `30` | wall-clock BUDGET for the run. Agents are spawned one after another until it is reached, and are never killed — each finishes on its own, so the run overshoots by however long the last one takes. Each agent reads what the previous wrote. `0` runs exactly one agent |

`unsafe` needs a nightly toolchain with `rustc-dev` and `llvm-tools`, and the
crate to compile; without either there are no counts and the reason is
recorded. `ub` needs `cargo +nightly miri` to check its own reproductions, and
warns without it.

## Container

```sh
docker build -t crustify-audit run/

docker run --rm -it --name audit-ippcp \
    -e ANTHROPIC_API_KEY -e CRUSTIFY_BILLING=api \
    -e CRUSTIFY_TARGET=/src -e CRUSTIFY_TARGET_REF=marvinte/wrap-2026-08-21 \
    -v "$PWD:/opt/crustify-audit" \
    -v /path/to/target-repo:/src:ro \
    -v audit-ippcp-work:/work \
    crustify-audit
```

| mount | mode | holds |
|---|---|---|
| `/opt/crustify-audit` | read-write | this checkout; agents may fix the tool, so give them a reviewable branch |
| `/src` | bind, read-only | the target checkout, when `CRUSTIFY_TARGET` is a path. Cloned into the volume, never audited in place, so it comes back unmodified |
| `/work` | named volume, and `HOME` | everything: the target clone at `/work/target` and its `crustify/audit/` artifacts, the C library the agent builds, the cargo registry, the provider CLI's config at `/work/.claude`. Drop it and the run is throwaway. The Rust toolchain, miri, cmake and nasm need no volume — they are in the image layer |

| var | values | default |
|---|---|---|
| `CRUSTIFY_TARGET` | git URL, or a path to a checkout mounted in the container | — |
| `CRUSTIFY_TARGET_REF` | branch, tag or sha | clone default |
| `CRUSTIFY_VERB` | `ub`, `unsafe` | `ub` |
| `CRUSTIFY_MODEL` | `<provider>/<model>` | `anthropic/claude-opus-5` |
| `CRUSTIFY_BILLING` | `subscription`, `api` | `subscription` |
| `CRUSTIFY_TIMEOUT` | minutes, `0` for one agent | `60` |

The target is cloned into the volume on first run and reused after, so a
second run against the same volume continues the first — the agent reads the
advisories and notes already there.

The image carries cmake, ninja, nasm, yasm, autotools and clang, and nothing
target-specific. The C library the crate wraps, a campaign tree's `ffibox`,
anything else it needs — the agent installs itself, which `ub` requires anyway,
since an advisory has to link the audited crate.

## Why the deterministic half exists

Not because an agent could not count. Because a count it produced would be a
sample: the measure is a pure function of the source tree, so two runs agree
and a diff between them is a change in the crate rather than a change in the
model's mood. That is what makes a number quotable.

It also runs the same driver as `crustify-cli audit`, so a hand-written wrapper
and a crustify-generated one are measured by one instrument and their numbers
compare.

What it does not do is decide what is worth looking at. That is the judgement
`ub` exists for, and handing the agent a ranked list would make it in advance,
on evidence a syntax pass cannot weigh.

## What the agent looks for

The shapes that are usually soundness bugs in C wrappers:

1. **Aliasing** — a `&mut T` and a `&T` to the same object live at once, usually
   laundered through `transmute_copy`.
2. **Lending iterators** — `Item` borrowing the iterator's `'a` rather than
   `&mut self`, so `collect()` yields several `&mut` to one object.
3. **Unvalidated integer→enum transmutes** of values that came from C.
4. **Lifetimes decoupled** from the borrow they came from.
5. **`Deref`/`DerefMut` exposure** that `mem::swap` can break invariants through.
6. **`Send`/`Sync` asserted** over thread-affine C state.

Resolving these **transitively** is load-bearing. The bug this tool was built
after holds its exclusive reference directly and reaches its shared one a level
down through another struct; looking only at direct fields misses it entirely.

## Triage

**An empty `crustify/audit/advisories/` means nothing was demonstrated.** The agent
writes an advisory only when it actually crashed something — one file per bug,
named after the bug. `crustify/audit/notes/` holds one note per lead it chased,
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

Question 2 rarely bites, because an advisory requires the reproduction to
depend on the audited crate and call its real public API — there is no fidelity
question when the crash happened in their code. A reduction that merely mirrors
the crate's types is a **note**, not an advisory: it shows that a program
nobody wrote is unsound, and the claim that it models the real one is the one
thing a reader cannot check.

The cost is that an instrument which cannot run the real crate cannot produce
an advisory. Miri stops at every `extern "C"` call, so Rust-side aliasing in a
wrapper usually ends as a note — deliberately, since the alternative is
advisories nobody can verify.

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

The harness hands the agent the repository path and starts it. Everything after that — what to investigate, how to reduce it, what a
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

The measure covers the code a normal build compiles: `cfg` stripping happens
before HIR, so an inline `mod tests` puts neither its lines in the denominator
of a ratio nor its `unsafe` in the numerator.

The figures that *are* categorical are the ones measuring an obligation the
seam does not excuse:

- `unsafe_fns` minus `unsafe_fns_seam` — an `unsafe fn` outside a conversion
  routine or the C-ABI gateway pushes its invariant onto every caller, and
  `unsafe_fns_pub` says how many leave the crate
- `raw_ptr_args + raw_ptr_rets` minus `raw_ptr_seam` — each remaining position
  is a lifetime the type system is not tracking
- `ref_to_type_wrapper` — a reference over memory C writes through a pointer it
  retains. Target 0, and **vacuously** 0 wherever `wrapper_newtypes` is 0, so
  read the pair

Those are the comparisons worth making between two wrappers over the same C
library.

## Status

Working end to end. `ub` has run against git2-rs, rust-openssl and
rust-ffmpeg, each producing an advisory and a set of notes.

- The counts come from the driver vendored in `src/driver/`, which is
  `crustify-cli`'s `utils/unsafe_metrics` copied verbatim, so `crustify-audit
  unsafe` and `crustify-cli audit` report the same numbers for the same tree.
  It is a copy, not a shared crate: an edit made here and not there makes the
  two disagree while both claim the same metric names.
- The driver compiles the crate, which an FFI wrapper often cannot do without
  its system libraries. Then `counts` is `null`, `counts_unavailable` says
  why, and the seed half still runs — no substitute numbers under the same
  field names.
- Finding what is worth investigating is the agent's, not a scanner's. It
  reads the crate, forms its own suspicions and defends them; `unsafe` gives it
  the numbers and nothing else.
- One agent, by design. Splitting the hunt across parallel agents is worth it
  once a single one is demonstrably good.
- The agent both produces findings and checks them.

## Layout

```
src/driver/              the unsafe metrics (Rust, rustc driver over HIR)
src/crustify_audit/
  cli.py                 unsafe / ub
  layout.py              artifact paths; repo -> crate resolution
  unsafe_scan.py         writes unsafe.json, derives ratios
  driver.py              builds and runs the rustc driver
  models.py              <provider>/<model> -> backend
  agentlog.py            per-agent transcript + usage
  agents/base.py         the single audit agent
  agents/backends/       claude / codex CLI drivers
  prompts/ub.md          the hunt prompt
```
