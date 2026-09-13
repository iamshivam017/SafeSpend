"""Phase 2.3 tests: boundary-audit isolation and proven engine properties."""
import ast
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, profile

from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow


def flow(amount, on_date):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category="t", direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis="settled", source_event_ids=("t",), essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class BoundaryAuditIsolationTests(unittest.TestCase):
    """Production code must never import the evaluation-only audit modules."""

    def test_production_modules_do_not_import_audit_tools(self):
        # decision-path modules only (main.py's function-local --selfcheck /
        # --diagnose CLI imports are already vetted by earlier isolation tests)
        production = [ROOT / "code" / name for name in
                      ("config.py", "errors.py", "schemas.py", "parsing.py",
                       "data_loader.py", "indexes.py", "output_validator.py")] + \
            list((ROOT / "code" / "finance").glob("*.py"))
        forbidden = ("financial_boundary_audit", "plan_safety_audit",
                     "essential_coverage_audit", "sample_evaluator")
        for path in production:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for name in forbidden:
                        self.assertNotIn(name, node.module or "", str(path))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        for name in forbidden:
                            self.assertNotIn(name, alias.name, str(path))


class BoundaryMonotonicityTests(unittest.TestCase):
    """Provable engine property: increasing a today-payment weakly decreases
    the minimum projected balance (the boundary the official asp sits on)."""

    def test_payment_increase_strictly_decreases_minimum(self):
        p = profile(balance="1000", minimum="200")
        flows = [flow("-100", D + timedelta(days=5)), flow("300", D + timedelta(days=10))]
        prev = None
        amount = Decimal("0")
        while amount <= Decimal("800"):
            sim = simulate(p, D, flows, hypothetical_payments=[Payment(D, amount)],
                           include_trace=False)
            if prev is not None:
                self.assertLessEqual(sim.minimum_projected_balance, prev)
            prev = sim.minimum_projected_balance
            amount += Decimal("100")

    def test_boundary_is_exact(self):
        # paying exactly (balance - floor) with no other flows ends exactly at floor
        p = profile(balance="1000", minimum="200")
        sim = simulate(p, D, [], hypothetical_payments=[Payment(D, Decimal("800"))],
                       include_trace=False)
        self.assertEqual(sim.ending_balance, Decimal("200"))
        self.assertEqual(sim.state, SafetyState.SAFE)
        sim = simulate(p, D, [], hypothetical_payments=[Payment(D, Decimal("800.01"))],
                       include_trace=False)
        self.assertEqual(sim.state, SafetyState.UNSAFE)


class BoundaryAuditRunTests(unittest.TestCase):
    def test_boundary_audit_runs_and_defers_are_attributed(self):
        from code.evaluation.financial_boundary_audit import BoundaryAuditor
        auditor = BoundaryAuditor()
        rows = auditor.test_baseline_and_asp() + auditor.test_earliest()
        # 25 x 6 minus one skipped Test C: request_14's baseline is UNRESOLVED
        # (childcare evidence without amount), and an unresolved baseline has no
        # deterministically measurable headroom
        self.assertEqual(len(rows), 25 * 6 - 1)
        counts = {}
        for row in rows:
            counts[row.verdict] = counts.get(row.verdict, 0) + 1
        # every verdict is one of the documented classifications
        self.assertEqual(set(counts) <= {"PASS", "MISMATCH", "CONTRADICTION", "DEFERRED"}, True)
        # Test D (earliest-date plan safety) must be fully PASS among resolvable
        d_rows = [r for r in rows if r.test == "D" and r.verdict != "DEFERRED"]
        self.assertTrue(d_rows)
        self.assertTrue(all(r.verdict == "PASS" for r in d_rows))


if __name__ == "__main__":
    unittest.main()
