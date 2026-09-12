"""Sample-evaluator tests: self-check must pass 25/25; mutations must fail."""
import unittest
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401

from code.data_loader import load_sample_requests
from code.evaluation.sample_evaluator import (FIELD_LABELS, compare, run_selfcheck,
                                              sample_to_output_row)
from code.schemas import AffordabilityStatus, OutputRow, RecommendedPaymentMethod


class SampleEvaluatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samples = load_sample_requests()
        cls.gold_rows = {s.request.request_id: sample_to_output_row(s) for s in cls.samples}

    def test_selfcheck_is_perfect(self):
        report = run_selfcheck()
        self.assertEqual(report.total, 25)
        for label in FIELD_LABELS:
            self.assertEqual(report.field_matches[label], 25,
                             f"{label} should match 25/25 in self-check")
        self.assertTrue(report.is_perfect())
        self.assertEqual(report.diffs, [])

    def test_mutated_amount_detected(self):
        rows = dict(self.gold_rows)
        victim = self.samples[0].request.request_id
        mutated = rows[victim]
        rows[victim] = OutputRow(
            request_id=mutated.request_id,
            amount_safe_to_pay=mutated.amount_safe_to_pay + Decimal("1"),
            affordability_status=mutated.affordability_status,
            recommended_payment_method=mutated.recommended_payment_method,
            payment_plan=mutated.payment_plan,
            earliest_date_for_full_payment=mutated.earliest_date_for_full_payment,
            spending_changes_needed=mutated.spending_changes_needed,
            decision_explanation=mutated.decision_explanation)
        report = compare(rows, self.samples)
        self.assertEqual(report.field_matches["amount_safe_to_pay"], 24)
        self.assertFalse(report.is_perfect())
        self.assertEqual(len(report.diffs), 1)
        self.assertEqual(report.diffs[0].request_id, victim)

    def test_mutated_status_detected(self):
        rows = dict(self.gold_rows)
        victim = self.samples[0].request.request_id
        mutated = rows[victim]
        other_status = (AffordabilityStatus.NOT_AFFORDABLE
                        if mutated.affordability_status != AffordabilityStatus.NOT_AFFORDABLE
                        else AffordabilityStatus.AFFORDABLE_LATER)
        rows[victim] = OutputRow(
            request_id=mutated.request_id, amount_safe_to_pay=mutated.amount_safe_to_pay,
            affordability_status=other_status,
            recommended_payment_method=mutated.recommended_payment_method,
            payment_plan=mutated.payment_plan,
            earliest_date_for_full_payment=mutated.earliest_date_for_full_payment,
            spending_changes_needed=mutated.spending_changes_needed,
            decision_explanation=mutated.decision_explanation)
        report = compare(rows, self.samples)
        self.assertEqual(report.field_matches["affordability_status"], 24)

    def test_mutated_plan_amount_detected(self):
        rows = dict(self.gold_rows)
        victim = next(s for s in self.samples
                      if s.recommended_payment_method == RecommendedPaymentMethod.PARTIAL_PAYMENT)
        vid = victim.request.request_id
        rows[vid] = OutputRow(
            request_id=vid, amount_safe_to_pay=rows[vid].amount_safe_to_pay,
            affordability_status=rows[vid].affordability_status,
            recommended_payment_method=rows[vid].recommended_payment_method,
            payment_plan=rows[vid].payment_plan + "|2024-09-20:1",  # extra payment
            earliest_date_for_full_payment=rows[vid].earliest_date_for_full_payment,
            spending_changes_needed=rows[vid].spending_changes_needed,
            decision_explanation=rows[vid].decision_explanation)
        report = compare(rows, self.samples)
        self.assertEqual(report.field_matches["payment_plan"], 24)

    def test_missing_row_fails_all_fields_for_that_request(self):
        rows = dict(self.gold_rows)
        victim = self.samples[0].request.request_id
        del rows[victim]
        report = compare(rows, self.samples)
        self.assertEqual(report.total, 25)
        for label in FIELD_LABELS:
            self.assertEqual(report.field_matches[label], 24, label)

    def test_no_production_leak_of_sample_labels(self):
        # Production modules must not import the sample evaluator or read answer
        # columns: assert the decision-path modules have no such imports.
        import ast
        from pathlib import Path
        production = [Path(ROOT) / "code" / name for name in
                      ("config.py", "errors.py", "schemas.py", "parsing.py",
                       "data_loader.py", "indexes.py", "output_validator.py")]
        for path in production:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("sample_evaluator", alias.name, str(path))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertNotIn("sample_evaluator", module, str(path))
                    self.assertNotIn("sample_requests", module, str(path))
        # main.py may reference the evaluator ONLY inside a function body (the
        # --selfcheck CLI flag); a module-level import would be a leak.
        main_tree = ast.parse((Path(ROOT) / "code" / "main.py").read_text(encoding="utf-8"))
        for node in main_tree.body:  # top-level statements only
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn("sample_evaluator", node.module or "", "main.py")


if __name__ == "__main__":
    unittest.main()
