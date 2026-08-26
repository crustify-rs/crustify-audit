---

Fill in every mandatory answer before a headless run. Interactively, the
orchestrator asks for any mandatory answer left blank or in angle brackets.
Optional answers may be left unresolved for the orchestrator to decide.

# Mandatory questions

## Audit

1. **Which repository and revision should this audit cover?**
   - Answer: `<mounted at /target | repository URL, commit or tag>`
2. **Should the auditors only report, also repair what they confirm, or only
   repair advisories that are already there?**
   - Answer: `<audit | audit+patch | patch>`
3. **How many auditors should run at once?**
   - Answer: `<N>`
4. **What is the wall-clock budget per auditor, in minutes? Spend is roughly
   this times the number of auditors.**
   - Answer: `<minutes>`
5. **Which backend and model should the auditors use? The same one as the
   orchestrator?**
   - Answer: `<provider/model | same as orchestrator>`
6. **Which billing mode should agentic stages use?**
   - Answer: `<api | subscription>`
7. **Which instruments should the auditors hunt with?**
   - Answer: `<miri | asan/ubsan | bsan | space-separated combination>`
   - `miri`: Rust-side memory, value-validity, alignment, aliasing, intrinsic,
     and data-race UB in code Miri can execute.
   - `asan/ubsan`: native out-of-bounds, lifetime/free, pointer/alignment,
     integer/shift, and invalid runtime-value UB in executed instrumented code.
   - `bsan`: Tree Borrows aliasing and pointer invalidation across Rust and
     foreign code.

# Optional questions

Unanswered optional questions are decided by the orchestrator.

## Reporting

8. **Where and in what format should results be recorded?**
   - Answer: `<results path>, <examples/results.md | custom template>`
