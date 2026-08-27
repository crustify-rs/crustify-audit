import unittest

from crustify_audit.agents.base import AuditAgent, INSTRUMENT_SPECS
from crustify_audit.cli import build_parser
from crustify_audit.layout import Layout
from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent


def _agent(objective="audit", workset=None, instruments=None):
    return AuditAgent(Layout(Path("/target")), objective=objective,
                      workset=workset, instruments=instruments)


class UbPromptTests(unittest.TestCase):
    def test_repair_happens_in_a_worktree_and_is_verified(self):
        prompt = AuditAgent._prompt(None)
        normalized = " ".join(prompt.split())

        self.assertIn("## Repair", prompt)
        # A worktree, not the checkout: concurrent agents read that checkout.
        self.assertIn("Work in a git worktree, never in the checkout", normalized)
        self.assertIn("focused regression tests", normalized)
        self.assertIn("rerun the original reproduction", normalized)
        self.assertIn("Do not merge, do not push", normalized)

    def test_advisories_require_an_instrumented_safe_reproducer(self):
        prompt = AuditAgent._prompt(None)
        normalized = " ".join(prompt.split())

        self.assertIn("depends on that crate", normalized)
        self.assertIn("public API without using `unsafe`", normalized)
        self.assertIn("triggers at least one selected instrument", normalized)
        self.assertIn("record the result as a lead, not an advisory", normalized)

    def test_repair_is_gated_on_the_objective(self):
        prompt = AuditAgent._prompt(None)
        normalized = " ".join(prompt.split())

        self.assertIn("Only when your objective includes patching", normalized)
        self.assertIn("Under `audit`, an advisory is finished when it is written",
                      normalized)

    def test_audit_objective_forbids_touching_the_target(self):
        preamble = _agent("audit").system_preamble()

        self.assertIn("you do not modify target source", preamble)
        self.assertNotIn("worktree", preamble)

    def test_patching_objectives_confine_edits_to_a_worktree(self):
        for objective in ("audit+patch", "patch"):
            with self.subTest(objective=objective):
                preamble = _agent(objective).system_preamble()
                self.assertIn("inside a git worktree", preamble)
                self.assertIn(objective, preamble)

    def test_hard_rule_survives_every_objective(self):
        for objective in ("audit", "audit+patch", "patch"):
            with self.subTest(objective=objective):
                preamble = _agent(objective).system_preamble()
                self.assertIn("write ONLY under", preamble)
                self.assertIn("crustify/audit/", preamble)

    def test_an_empty_workset_is_the_whole_crate(self):
        self.assertIn("whole crate", _agent()._arguments()["workset"])

    def test_a_workset_lists_its_files_and_bounds_the_report(self):
        args = _agent(workset=["src/a.rs", "src/b.rs"])._arguments()

        self.assertIn("src/a.rs", args["workset"])
        self.assertIn("src/b.rs", args["workset"])
        self.assertIn("must live in", args["workset"])

    def test_the_prompt_formats_with_exactly_what_the_harness_injects(self):
        # A brace the harness does not supply would blow up at spawn time.
        AuditAgent._prompt(None).format(**_agent()._arguments())

    def test_default_scope_reveals_every_instrument_and_its_bug_classes(self):
        scope = _agent()._arguments()["instruments"]

        for name, spec in INSTRUMENT_SPECS.items():
            with self.subTest(instrument=name):
                self.assertIn(f"{spec.label} (`{name}`)", scope)
                self.assertIn(spec.reach, scope)
                for bug_class in spec.bug_classes:
                    self.assertIn(bug_class, scope)
        self.assertEqual(3, scope.count("Hunt for these bug classes:"))

    def test_selected_scope_is_the_only_scope_in_the_formatted_prompt(self):
        agent = _agent(instruments=["bsan"])
        prompt = agent._prompt().format(**agent._arguments())

        self.assertIn("BorrowSanitizer (BSan)", prompt)
        self.assertIn("writes through raw or foreign pointers", prompt)
        self.assertNotIn("Miri (`miri`)", prompt)
        self.assertNotIn("AddressSanitizer +", prompt)
        self.assertIn("do not spend the run on other classes",
                      " ".join(prompt.split()))

    def test_cli_parses_multiple_instruments(self):
        args = build_parser().parse_args([
            "/target", "ub", "--instruments", "miri", "bsan"
        ])

        self.assertEqual(["miri", "bsan"], args.instruments)

    def test_orchestrator_reveals_and_records_the_resolved_scope(self):
        orchestrator = (
            _REPO / "src/crustify_audit/prompts/orchestrator.md"
        ).read_text()

        self.assertIn("selected instrument and its associated\nbug classes",
                      orchestrator)
        self.assertIn("instrument-to-bug-class scope", orchestrator)
        self.assertIn("mark selected instruments that were unavailable as untested",
                      " ".join(orchestrator.split()))


if __name__ == "__main__":
    unittest.main()
