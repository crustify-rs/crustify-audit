---

Fill in every mandatory answer before a headless run. Interactively, the
orchestrator asks for any mandatory answer left blank or in angle brackets.
Optional answers may be left unresolved for the orchestrator to decide.

The target checkout is mounted at `/target`, so the questionnaire does not ask
which repository to audit.

Campaign target: zstd-rs (`zstd`, `zstd-safe`, `zstd-sys`, vendored libzstd
submodule at `zstd-safe/zstd-sys/zstd`). The default build compiles the
vendored C, so it is instrumented.

# Mandatory questions

## Audit

1. **Should the auditors only report, also repair what they confirm, or only
   repair advisories that are already there?**
   - Answer: `audit`
2. **How many auditors should run at once?**
   - Answer: `4`
3. **What is the wall-clock budget per auditor, in minutes? Spend is roughly
   this times the number of auditors.**
   - Answer: `60 minutes`
4. **Which backend and model should the auditors use? The same one as the
   orchestrator?**
   - Answer: `same as orchestrator`
5. **Which billing mode should agentic stages use?**
   - Answer: `api`
6. **Which instruments should the auditors hunt with?**
   - Answer: `asan/ubsan bsan`
   - `miri`: Rust-side memory, value-validity, alignment, aliasing, intrinsic,
     and data-race UB in code Miri can execute.
   - `asan/ubsan`: native out-of-bounds, lifetime/free, pointer/alignment,
     integer/shift, and invalid runtime-value UB in executed instrumented code.
   - `bsan`: Tree Borrows aliasing and pointer invalidation across Rust and
     foreign code.

# Optional questions

Unanswered optional questions are decided by the orchestrator.

## Reporting

7. **Where and in what format should results be recorded?**
   - Answer: `crustify/audit/`, `examples/results.md`
