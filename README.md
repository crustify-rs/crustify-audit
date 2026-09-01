# crustify-audit

**Moved to [crustify](https://github.com/crustify-rs/crustify).**

The audit tool is now one of two in that repository, beside the translation
CLI it always shared a harness with. Nothing about using it changed: the
package is still `crustify_audit` and the binary is still `crustify-audit`.
What changed is that model routing, run pricing, the agent log and the
provider usage readers come from `crustify.core` instead of being maintained
twice.

- documentation: [`docs/audit.md`](https://github.com/crustify-rs/crustify/blob/main/docs/audit.md)
- examples and container: [`examples/crustify_audit/`](https://github.com/crustify-rs/crustify/tree/main/examples/crustify_audit)
- campaign results: [crustify-audit-tracker](https://github.com/crustify-rs/crustify-audit-tracker)

This repository is archived. Its history stays here.
