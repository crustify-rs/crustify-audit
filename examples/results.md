# crustify-audit — `<target repo>`

Copy this template into the audited checkout, then fill it as work lands. All
prose belongs in Notes.

## Run

- **target repo** — `<repo>` @ `<commit>`
- **crate** — `<name>` `<version>`
- **objective** — `<audit | audit+patch | patch>`
- **agent backend** — `<claude | codex>`
- **model** — `<provider>/<model>`
- **`--billing`** — `<api | subscription>`
- **`--timeout`** — `<n>` min per auditor — a wall BUDGET, not a kill switch
- **`--instruments`** — `<miri | asan/ubsan | bsan | combination>`
- **deps** — crustify-audit `<sha>` (`<branch>`)

## Advisories

One row per CONFIRMED bug: an instrument reported UB on a reproduction that
links the real crate.

| advisory | site | agent run | miri | asan/ubsan | bsan | patch |
|---|---|---|:-:|:-:|:-:|---|
| `<name>` | `<file>:<line>` | `<tag>` | ✓ | — | n/a | `<branch>` @ `<sha>` |
| `<name>` | `<file>:<line>` | `<tag>` | n/a | ✓ | ✓ | — |
| **Σ `<n>` advisories** | | | **`<n>`** | **`<n>`** | **`<n>`** | **`<n>` patched** |

## Leads

- **investigated** — `<n>` at `crustify/audit/leads/`
- **ruled out** — `<n>`, with the reason recorded, so the next run does not
  re-derive the same "no"
- **open** — `<n>`, promising but out of budget

Reproduced findings are not here — they are advisories, counted above.

## Scope

Files the auditors were given. The per-agent split is in the table below.

```
<file>
<file>
```

- **files scanned** — `<n>` of `<n>` in the crate
- **not scanned** — `<dirs / globs, and why>`

## Agent runs

One row per auditor. `wall` is `ended_at − started_at` from that agent's own
`usage.json`, so it includes whatever it spent building the C library. Under
subscription billing `$` is an API-equivalent comparison value, not a charged
amount.

| run | workset | files | wall | $ | advisories | leads |
|---|---|---:|---|---:|---:|---:|
| `<tag>` | `<module / paths>` | `<n>` | `<n>h<n>m<n>s` | `$<n>` | `<n>` | `<n>` |
| `<tag>` | `<module / paths>` | `<n>` | `<n>h<n>m<n>s` | `$<n>` | `<n>` | `<n>` |
| orchestrator | — | — | — | `$<n>`+ | — | — |
| **Σ `<n>` agents** | | **`<n>`** | **`<n>`h`<n>`m** | **`$<n>`** | **`<n>`** | **`<n>`** |

## Legend

- **miri / asan/ubsan / bsan** — `✓` fired on this finding, `—` ran and did
  not, `n/a` could not run it. Miri is `n/a` wherever the faulting access is
  inside C; bsan is the one that answers aliasing across that seam
- **agent run** — tag of the run that produced the finding, matching the Agent
  runs table
- **site** — where the bug is, not where the reproduction is
- **patch** — the worktree branch carrying the fix, `—` under `audit`
- **files** — size of that agent's `--workset`; blank for a single agent, which
  gets the whole crate

## Notes

`<what the numbers do not say>`
