---

Fill in every mandatory answer before a headless run.
Optional answers may be left unresolved for the orchestrator to decide.

# Mandatory questions

## Audit

1. **Should the auditors only report, also repair what they confirm, or only
   repair advisories that are already there?**
   - Answer: `audit`
2. **How many auditors should run at once?**
   - Answer: `4`
3. **What is the wall-clock budget per auditor, in minutes? Spend is roughly
   this times the number of auditors.**
   - Answer: `30`
4. **Which backend and model should the auditors use?**
   - Answer: `codex, gpt-5.6-sol`
5. **Which billing mode should agentic stages use?**
   - Answer: `api`
6. **Which instruments should the auditors hunt with?**
   - Answer: `bsan`

# Optional questions

Unanswered optional questions are decided by the orchestrator.

## Reporting

7. **Where and in what format should results be recorded?**
   - Answer: use the canonical template from `examples/results.md`
   and author it in `crustify/audit/`.

## Additional instructions

Unless otherwise stated, match the structure of the given results table exactly.
