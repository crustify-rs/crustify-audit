---

Fill in every mandatory answer before a headless run. Interactively, the
orchestrator asks for any mandatory answer left blank or in angle brackets.
Optional answers may be left unresolved for the orchestrator to decide.

# Mandatory questions

## Audit

1. **Which repository and revision should this audit cover?**
   - Answer: `mounted at /target`
2. **Should the auditors only report, also repair what they confirm, or only
   repair advisories that are already there?**
   - Answer: `audit`
3. **How many auditors should run at once?**
   - Answer: `4`
4. **What is the wall-clock budget per auditor, in minutes? Spend is roughly
   this times the number of auditors.**
   - Answer: `30 minutes`
5. **Which backend and model should the auditors use? The same one as the
   orchestrator?**
   - Answer: `opus-5`
6. **Which billing mode should agentic stages use?**
   - Answer: `subscription`
7. **Which instruments should the auditors hunt with?**
   - Answer: `borrowsanitizer`

# Optional questions

Unanswered optional questions are decided by the orchestrator.

## Reporting

8. **Where and in what format should results be recorded?**
   - Answer: `examples/results.md`
