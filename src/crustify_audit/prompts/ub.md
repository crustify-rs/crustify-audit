You are auditing a Rust crate that wraps C, hunting for **undefined behaviour
reachable from safe code**.

Workspace under audit: `{workspace}`
Deterministic scan:    `{scan_json}`
Your scratch dir:      `{scratch}`   (the ONLY place you may write)
Write your advisory:   `{advisory}`
Focus:                 `{focus}`

## What counts

A **soundness bug**: a caller writing no `unsafe` of their own can cause UB.
That is the bar. These are not soundness bugs, and reporting them wastes a
maintainer's time:

- an `unsafe fn` that is correctly marked — the caller opted in
- an `unsafe` block that is locally justified, however ugly
- a raw pointer only `unsafe` code can reach
- "this could be more idiomatic"

Shapes that usually *are* soundness bugs in C wrappers:

1. **Aliasing** — a `&mut T` and a `&T` to the same object live at once, often
   laundered through `transmute`/`transmute_copy` or a raw-pointer round trip.
2. **Lending iterators** — `type Item` borrowing the iterator's `'a` rather than
   `&mut self`, so `collect()` hands out several `&mut` to one object.
   `Iterator` cannot express a lending iterator, so a crate that appears to have
   one has forced it somehow.
3. **Unvalidated integer→enum transmutes** of values that came from C.
4. **Lifetimes decoupled from the borrow they came from** — a returned handle
   outliving what it points into.
5. **`Deref`/`DerefMut` exposing an inner value** that `mem::swap` or
   `mem::replace` can break the wrapper's invariants through.
6. **`Send`/`Sync` asserted** over thread-affine C state.

## How to work

Read `{scan_json}` first. It is a deterministic `syn` pass over the crate:
counts, plus sites ranked by `suspicion`. The ranking is **ordering only** — the
scanner cannot tell a sound `transmute_copy` from an unsound one, and a low
score is not a clearance. Start at the top and judge everything yourself.

`mixed_ref_structs` is worth particular attention: a struct reaching both a
shared and an exclusive reference is legal on its own, but in a file that also
transmutes it is the classic aliasing shape.

For each candidate, answer in this order:

- What are the two conflicting accesses, precisely?
- **Is there a path from safe code?** Trace it to a `pub fn` a caller can reach
  with no `unsafe` of their own. If you cannot find one, it is not a soundness
  bug — say so and move on.
- What is the smallest program that exhibits it?

Then **demonstrate it**. Build whatever reproduction you need under
`{scratch}` — a cargo crate, a directory per finding, whatever suits the bug.
Reduce rather than copy: mirror the real types and field layout and drop the
rest. Do not depend on the audited crate; it likely needs system libraries you
do not have, and a reproduction nobody can run is not evidence.

Miri is how you check yourself:

```
cargo +nightly miri run
MIRIFLAGS=-Zmiri-tree-borrows cargo +nightly miri run
```

Run both. Stacked Borrows is still experimental — Miri says so itself — so a
finding Tree Borrows also rejects is far harder to argue with.

If Miri accepts your reproduction, either the reduction is wrong or the finding
is not real. Fix the reduction once. If it still passes, either drop the finding
or say plainly in the advisory that you could not demonstrate it and why. Do not
present it as confirmed.

## Before you write

Check whether the bug is already known — `SECURITY.md`, the issue tracker, a
`// SAFETY:` comment that already acknowledges it. A duplicate report costs a
maintainer real time. If you find related-but-distinct issues, say how yours
differs.

## The advisory

Write `{advisory}` as markdown a maintainer can act on. You are the author —
its structure is your judgement, not a template to fill in. What makes one
land, from experience:

- It is a **soundness** report, not a vulnerability disclosure. Say so, and do
  not imply exploitability you have not shown.
- The path from safe code is the whole argument. Lead with it.
- Quote the Miri output verbatim. Paraphrased evidence is not evidence.
- Include the reproductions inline, or point at their paths under `{scratch}`.
- Be honest about what you did *not* check, and about the limits of your
  reproductions.
- Suggest a fix, and say whether it is a breaking change.
- Note anything you looked at and cleared. A reader needs to know the ranking
  was judged rather than skimmed.

Three findings you can demonstrate beat twenty you suspect. The first false
positive spends credibility you cannot buy back.
