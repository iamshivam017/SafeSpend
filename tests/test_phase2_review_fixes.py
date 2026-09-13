"""Regression tests for the CodeRabbit Phase 2 review fixes (C1-C3, W2)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _finance_fixture import D, ev, profile

from code.errors import DataError
from code.finance.lifecycle import resolve_lifecycle
from code.finance.recurrence import (detect_recurring_patterns, project_occurrences,
                                     RecurringPattern)
from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow
from code.schemas import EventDirection, EventStatus


def flow(amount, on_date, category="rent"):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category=category, direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis="settled", source_event_ids=("t",), essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class CycleGuardTests(unittest.TestCase):
    """C1: cyclic/self linked_event_id must fail fast, never hang."""

    def test_self_link_raises(self):
        with self.assertRaises(DataError):
            resolve_lifecycle([ev("self1", amount="10", linked="self1",
                                  event_date=date(2026, 1, 2), settlement=date(2026, 1, 3))], D)

    def test_two_cycle_raises(self):
        a = ev("c_a", amount="10", linked="c_b", event_date=date(2026, 1, 2),
               settlement=date(2026, 1, 3))
        b = ev("c_b", amount="10", linked="c_a", event_date=date(2026, 1, 3),
               settlement=date(2026, 1, 4))
        with self.assertRaises(DataError):
            resolve_lifecycle([a, b], D)


class MedianTests(unittest.TestCase):
    """C2: credit representative amount must be a NUMERIC median of Decimals."""

    def test_numeric_median_not_lexicographic(self):
        # lexicographic median of {"9","10","8"} would be "8"; numeric is 10
        from code.schemas import EventDirection
        es = [ev("m0", category="salary", direction=EventDirection.CREDIT, amount="9",
                 event_date=D - timedelta(days=90), settlement=D - timedelta(days=90)),
              ev("m1", category="salary", direction=EventDirection.CREDIT, amount="10",
                 event_date=D - timedelta(days=60), settlement=D - timedelta(days=60)),
              ev("m2", category="salary", direction=EventDirection.CREDIT, amount="8",
                 event_date=D - timedelta(days=30), settlement=D - timedelta(days=30))]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(patterns[0].amount, Decimal("9"))  # numeric median

    def test_even_window_median_exact(self):
        from code.schemas import EventDirection
        from code.finance.recurrence import RecurrenceParams
        es = [ev(f"e{i}", category="salary", direction=EventDirection.CREDIT,
                 amount=str(1000 + i), event_date=D - timedelta(days=30 * (4 - i)),
                 settlement=D - timedelta(days=30 * (4 - i))) for i in range(4)]
        params = RecurrenceParams(recent_window=4)
        patterns = detect_recurring_patterns(es, params=params)
        self.assertEqual(patterns[0].amount, Decimal("1001.5"))  # median of 1000..1003


class StalenessTests(unittest.TestCase):
    """C3: dead series must not project (no phantom income)."""

    def _salary_pattern(self, last_occurrence):
        return RecurringPattern(
            category="salary", direction=EventDirection.CREDIT, currency="USD",
            cadence_days=30, is_monthly=True, amount=Decimal("4000"),
            flexibility="fixed", source_event_ids=("s",),
            last_occurrence=last_occurrence, classification_reason="test")

    def test_stale_series_does_not_project(self):
        # last salary 80 days before request (~2.7 monthly cadences ago) -> dead
        stale = self._salary_pattern(D - timedelta(days=80))
        projected, diags = project_occurrences([stale], D, D + timedelta(days=90), [])
        self.assertEqual(projected, [])
        self.assertTrue(any("inactive" in d for d in diags))

    def test_recent_series_still_projects(self):
        recent = self._salary_pattern(D - timedelta(days=45))
        projected, _ = project_occurrences([recent], D, D + timedelta(days=90), [])
        self.assertTrue(projected)  # within 2 cadences -> still active

    def test_no_projections_on_or_before_request_date(self):
        p = self._salary_pattern(D)  # last occurrence today
        projected, _ = project_occurrences([p], D, D + timedelta(days=90), [])
        self.assertTrue(all(o.effective_date > D for o in projected))

    def test_monthly_anchor_day_does_not_drift(self):
        # W3: Jan-31 anchor must give Feb-28, Mar-31 (not Mar-28)
        p = RecurringPattern(category="rent", direction=EventDirection.DEBIT,
                             currency="USD", cadence_days=30, is_monthly=True,
                             amount=Decimal("1000"), flexibility="fixed",
                             source_event_ids=("r",), last_occurrence=date(2026, 1, 31),
                             classification_reason="test")
        projected, _ = project_occurrences([p], date(2026, 2, 1), date(2026, 4, 30), [])
        self.assertEqual([o.effective_date for o in projected],
                         [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)])


class TerminalMatchTests(unittest.TestCase):
    """W1: terminal records only suppress matching pending movements."""

    def test_unrelated_cancelled_credit_keeps_pending_debit_reserved(self):
        from decimal import Decimal as Dc
        cancelled_credit = ev("cc", direction=EventDirection.CREDIT, amount="50",
                              status=EventStatus.CANCELLED, event_date=date(2025, 12, 20),
                              settlement=date(2025, 12, 21))
        pending_debit = ev("pd", amount="500", status=EventStatus.PENDING,
                           event_date=date(2025, 12, 19), settlement=date(2026, 1, 5),
                           linked="cc")
        r = resolve_lifecycle([cancelled_credit, pending_debit], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertEqual(r.cash_events[0].amount, Dc("500"))

    def test_matching_cancelled_debit_still_suppresses(self):
        cancelled = ev("cd", amount="500", status=EventStatus.CANCELLED,
                       event_date=date(2025, 12, 20), settlement=date(2025, 12, 21))
        pending = ev("pd2", amount="500", status=EventStatus.PENDING,
                     event_date=date(2025, 12, 19), settlement=date(2026, 1, 5),
                     linked="cd")
        r = resolve_lifecycle([cancelled, pending], D)
        self.assertEqual(r.cash_events, [])


class StatePrecedenceTests(unittest.TestCase):
    """W2: proven UNSAFE must not be masked by UNRESOLVED."""

    def test_unsafe_outranks_unresolved(self):
        p = profile(balance="100", minimum="90")
        u = __import__("code.finance.lifecycle", fromlist=["UnresolvedEvidence"]).UnresolvedEvidence(
            event_id="u1", reason="blank", effective_date=D + timedelta(days=3),
            direction=EventDirection.DEBIT, category="rent")
        r = simulate(p, D, [flow("-50", D)], unresolved_evidence=[u])
        self.assertEqual(r.state, SafetyState.UNSAFE)

    def test_unresolved_alone_still_unresolved(self):
        p = profile(balance="5000", minimum="90")
        u = __import__("code.finance.lifecycle", fromlist=["UnresolvedEvidence"]).UnresolvedEvidence(
            event_id="u2", reason="blank", effective_date=D + timedelta(days=3),
            direction=EventDirection.DEBIT, category="rent")
        r = simulate(p, D, [], unresolved_evidence=[u])
        self.assertEqual(r.state, SafetyState.UNRESOLVED)

    def test_payment_outside_horizon_rejected(self):
        p = profile(balance="1000", minimum="200")
        with self.assertRaises(DataError):
            simulate(p, D, [], hypothetical_payments=[Payment(D + timedelta(days=91),
                                                              Decimal("100"))])
        with self.assertRaises(DataError):
            simulate(p, D, [], hypothetical_payments=[Payment(D - timedelta(days=1),
                                                              Decimal("100"))])

    def test_duplicate_pending_substance_collapsed(self):
        # W6: two identical pending debits (same day/amount/category) reserve once
        a = ev("dp1", amount="50", status=EventStatus.PENDING, event_date=date(2025, 12, 30),
               settlement=date(2026, 1, 2))
        b = ev("dp2", amount="50", status=EventStatus.PENDING, event_date=date(2025, 12, 30),
               settlement=date(2026, 1, 2))
        r = resolve_lifecycle([a, b], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertTrue(any("duplicate substance" in i.reason for i in r.ignored))


if __name__ == "__main__":
    unittest.main()
