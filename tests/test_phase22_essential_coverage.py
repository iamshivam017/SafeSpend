"""Phase 2.2 anti-overfitting tests: the directive-6 case matrix, the
exactly-one-treatment invariant, and the user_01/user_13 regression."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, ev, profile

from code.data_loader import load_all
from code.finance.lifecycle import resolve_lifecycle
from code.finance.recurrence import (classify_pattern, detect_recurring_patterns,
                                     essential_provisions, project_occurrences)
from code.finance.timeline import build_cash_timeline
from code.indexes import Indexes
from code.schemas import EventDirection, EventStatus, EventType


def series(category, offsets, amounts, direction=EventDirection.DEBIT, type_=EventType.EXPENSE):
    return [ev(f"{category}{i}", type=type_, category=category, direction=direction,
               amount=str(amounts[i]), event_date=D - timedelta(days=offsets[i]),
               settlement=D - timedelta(days=offsets[i])) for i in range(len(offsets))]


class DirectiveSixMatrixTests(unittest.TestCase):
    """The seven anti-overfitting cases mandated by Phase 2.2 section 6."""

    def test_1_weekly_protected_groceries_gets_reserve(self):
        # detected sub-monthly pattern, NOT projected as commitment -> the
        # protected category must still receive a variable-essential reserve
        offsets = (7, 14, 21, 28, 35, 42, 49, 56, 63, 70)
        amounts = (620, 960, 700, 930, 640, 950, 660, 910, 680, 920)
        es = series("groceries", offsets, amounts)
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)
        protected = {"groceries"}
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [],
                                           source_events=es, protected_categories=protected)
        self.assertEqual(projected, [])  # variable -> no exact-event projection
        provisions = essential_provisions(es, protected, D, patterns,
                                          projected_fixed_keys={(c.category, "debit") for c in projected})
        self.assertEqual(len(provisions), 1)
        self.assertEqual(provisions[0].category, "groceries")
        # median of the three 30-day window totals (3210, 3160, 1600)
        self.assertEqual(provisions[0].amount, Decimal("3160"))

    def test_2_weekly_discretionary_gets_no_reserve(self):
        es = series("gaming", (7, 14, 21, 28, 35), (626, 964, 755, 881, 700))
        patterns = detect_recurring_patterns(es)
        provisions = essential_provisions(es, {"groceries"}, D, patterns,
                                          projected_fixed_keys=set())
        self.assertEqual(provisions, [])  # not protected -> no reserve

    def test_3_monthly_fixed_rent_projected_no_reserve(self):
        es = series("rent", (30, 60, 90, 120, 150), (800, 800, 800, 800, 800))
        patterns = detect_recurring_patterns(es)
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [],
                                           source_events=es,
                                           protected_categories={"rent"})
        self.assertTrue(projected)
        provisions = essential_provisions(es, {"rent"}, D, patterns,
                                          projected_fixed_keys={(c.category, "debit") for c in projected})
        self.assertEqual(provisions, [])  # no second treatment for same obligation

    def test_4_monthly_variable_protected_exactly_one_treatment(self):
        # monthly cadence with varying amounts = commitment (projected);
        # the provision must not also fire
        es = series("groceries", (30, 60, 90, 120, 150), (600, 750, 690, 810, 705))
        patterns = detect_recurring_patterns(es)
        self.assertTrue(patterns[0].is_monthly)
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [],
                                           source_events=es,
                                           protected_categories={"groceries"})
        self.assertTrue(projected)
        provisions = essential_provisions(es, {"groceries"}, D, patterns,
                                          projected_fixed_keys={(c.category, "debit") for c in projected})
        self.assertEqual(provisions, [])
        treatments = len(projected) + len(provisions)
        self.assertGreaterEqual(treatments, 1)  # exactly one KIND of treatment

    def test_5_irregular_sustained_protected_provisioned(self):
        offsets = (5, 14, 29, 36, 52, 63, 69, 83, 88)  # no dominant gap
        es = series("healthcare", offsets, (40,) * 9)
        self.assertEqual(detect_recurring_patterns(es), [])
        provisions = essential_provisions(es, {"healthcare"}, D, [])
        self.assertEqual(len(provisions), 1)
        self.assertEqual(provisions[0].amount, Decimal("120"))

    def test_6_isolated_protected_purchase_no_hallucination(self):
        es = series("groceries", (3,), (900,))
        self.assertEqual(detect_recurring_patterns(es), [])
        self.assertEqual(essential_provisions(es, {"groceries"}, D, []), [])

    def test_7_submonthly_proven_commitment_not_forbidden(self):
        # weekly identical-amount childcare payment: commitment-like -> projected
        es = series("childcare", (7, 14, 21, 28, 35), (200, 200, 200, 200, 200))
        patterns = detect_recurring_patterns(es)
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [],
                                           source_events=es,
                                           protected_categories={"childcare"})
        self.assertTrue(projected)


class ExactlyOneTreatmentInvariantTests(unittest.TestCase):
    def test_classification_is_total_and_exclusive(self):
        # every detected pattern maps to exactly one of the three classes
        cases = [
            (True, "rent", "expense", {"rent"}, "fixed_commitment"),
            (False, "groceries", "expense", {"groceries"}, "variable_essential"),
            (False, "gaming", "expense", set(), "variable_discretionary"),
        ]
        for is_monthly, category, etype, protected, expected in cases:
            from code.finance.recurrence import RecurringPattern
            pat = RecurringPattern(category=category, direction=EventDirection.DEBIT,
                                   currency="USD", cadence_days=30 if is_monthly else 10,
                                   is_monthly=is_monthly, amount=Decimal("100"),
                                   flexibility="fixed", source_event_ids=("x",),
                                   last_occurrence=D, classification_reason="t")
            src = [ev("x", category=category, type=EventType.EXPENSE, amount="90"),
                   ev("y", category=category, type=EventType.EXPENSE, amount="110")]
            self.assertEqual(classify_pattern(pat, src, protected), expected)


class User01User13RegressionTests(unittest.TestCase):
    """Phase 2.2 gate: request_09/13 stay corrected; user_01's groceries and
    user_13's groceries/transport now appear in the forward forecast."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = load_all()
        cls.indexes = Indexes.build(cls.bundle)

    def _timeline(self, request_id):
        s = next(x for x in self.bundle.samples if x.request.request_id == request_id)
        r = s.request
        p = self.indexes.profiles_by_user_id[r.user_id]
        ue = self.indexes.events_by_user_id.get(r.user_id, [])
        lc = resolve_lifecycle(ue, r.request_date)
        pats = detect_recurring_patterns(ue)
        return p, build_cash_timeline(p, r.request_date, lc, pats, self.indexes)

    def test_user01_groceries_reserve_present(self):
        p, tl = self._timeline("request_01")
        reserves = [f for f in tl.flows if f.basis == "essential_provision"]
        self.assertTrue(any(f.category == "groceries" for f in reserves))
        # single aggregate provision (oracle-calibrated), not per-purchase
        self.assertEqual(len([f for f in reserves if f.category == "groceries"]), 1)

    def test_user13_groceries_and_transport_reserves_present(self):
        _, tl = self._timeline("request_13")
        reserves = {f.category for f in tl.flows if f.basis == "essential_provision"}
        self.assertIn("groceries", reserves)
        self.assertIn("transport", reserves)

    def test_request_09_and_13_plans_still_safe(self):
        from code.evaluation.plan_safety_audit import run_audit
        rows = {row.request_id: row for row in run_audit()}
        self.assertEqual(rows["request_09"].verdict, "PASS")
        self.assertEqual(rows["request_13"].verdict, "PASS")
        self.assertEqual(sum(1 for r in rows.values() if r.verdict == "CONTRADICTION"), 0)


if __name__ == "__main__":
    unittest.main()
