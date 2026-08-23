import unittest

from crustify_audit.agents.base import AuditAgent


class UbPromptTests(unittest.TestCase):
    def test_confirmed_findings_require_a_branch_patch_and_verification(self):
        prompt = AuditAgent._prompt(None)
        normalized = " ".join(prompt.split())

        self.assertIn("## Fix confirmed findings", prompt)
        self.assertIn(
            "create a new, descriptively named Git branch in the target repository",
            normalized,
        )
        self.assertIn("focused regression tests", normalized)
        self.assertIn("rerun the original reproduction", normalized)
        self.assertIn("do not merge or push it", normalized)

    def test_system_rule_allows_only_confirmed_branch_remediation(self):
        preamble = AuditAgent.system_preamble(None)

        self.assertIn("only after confirming a finding", preamble)
        self.assertIn("only after creating the dedicated target Git branch", preamble)
        self.assertNotIn("read-only to you", preamble)


if __name__ == "__main__":
    unittest.main()
