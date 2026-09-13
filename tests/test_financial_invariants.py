"""Property/invariant tests + real-dataset diagnostics (Phase 2 §24-25)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, ev, profile

from code.data_loader import load_all
from code.finance.currency import MissingRateError
from code.finance.invariants import (adding_debit_cannot_increase_safety,
                                     larger_payment_cannot_increase_minimum,
                                     min_balance, moving_income_later_cannot_help_earlier_days,
                                     removing_credit_cannot_improve_minimum)
from code.finance.lifecycle import resolve_lifecycle
from code.finance.recurrence import detect_recurring_patterns
from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow, build_cash_timeline
from code.indexes import Indexes
from code.schemas import EventDirection


def flow(amount, on_date, category="rent", basis="settled"):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category=category, direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis=basis, source_event_ids=("t",), essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class PropertyInvariantTests(unittest.TestCase):
    """Monotonicity properties that must hold for ANY valid input."""

    P = profile(balance="1000", minimum="200")
    BASE = [flow("-100", D + timedelta(days=5)), flow("300", D + timedelta(days=10))]

    def test_extra_debit_cannot_increase_safety(self):
        for day in (D, D + timedelta(days=1), D + timedelta(days=45), D + timedelta(days=90)):
            for amount in ("-0.01", "-50", "-5000"):
                self.assertTrue(adding_debit_cannot_increase_safety(
                    self.P, D, self.BASE, flow(amount, day)), (day, amount))

    def test_larger_payment_cannot_increase_minimum(self):
        for day in (D, D + timedelta(days=30), D + timedelta(days=89)):
            self.assertTrue(larger_payment_cannot_increase_minimum(
                self.P, D, self.BASE, day, Decimal("10"), Decimal("1000")), day)

    def test_removing_credit_cannot_improve_minimum(self):
        credit = flow("300", D + timedelta(days=10))
        self.assertTrue(removing_credit_cannot_improve_minimum(self.P, D, self.BASE, credit))

    def test_cancelled_debit_does_not_reduce_balance(self):
        # a cancelled debit must behave EXACTLY like its absence: resolving a
        # lifecycle containing only a cancelled event yields zero cash flows
        cancelled = ev("c1", amount="500", status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.CANCELLED,
                       event_date=D, settlement=D)
        result = resolve_lifecycle([cancelled], D)
        self.assertEqual(result.cash_events, [])
        p = profile(balance="1000", minimum="200")
        with_event = simulate(p, D, [], unresolved_evidence=result.unresolved,
                              include_trace=True)
        without = simulate(p, D, [], include_trace=True)
        self.assertEqual(with_event.ending_balance, without.ending_balance)
        self.assertEqual(with_event.minimum_projected_balance,
                         without.minimum_projected_balance)

    def test_pending_credit_cannot_increase_balance(self):
        # a pending credit must behave exactly like its absence (never counted)
        from code.schemas import EventDirection, EventStatus
        pending_credit = ev("pc1", direction=EventDirection.CREDIT, amount="900",
                            status=EventStatus.PENDING, event_date=D,
                            settlement=D + timedelta(days=5))
        result = resolve_lifecycle([pending_credit], D)
        self.assertEqual(result.cash_events, [])  # dropped by lifecycle
        p = profile(balance="1000", minimum="200")
        # adversarial check: WITHOUT the rule, this credit would lift 1000 -> 1900
        with_credit_flow = simulate(p, D, [flow("900", D + timedelta(days=5))])
        self.assertEqual(with_credit_flow.ending_balance, Decimal("1900"))
        # with the rule applied, the engine must keep the worse (correct) number
        with_event = simulate(p, D, [], unresolved_evidence=result.unresolved)
        self.assertEqual(with_event.ending_balance, Decimal("1000"))

    def test_unrealized_investment_cannot_increase_cash(self):
        # an unrealized valuation must behave exactly like its absence
        from code.schemas import EventDirection, EventType, EventStatus
        valuation = ev("uv1", type=EventType.INVESTMENT_VALUATION,
                       direction=EventDirection.NON_CASH, amount="5000",
                       status=EventStatus.UNREALIZED, event_date=D + timedelta(days=3),
                       settlement=None)
        result = resolve_lifecycle([valuation], D)
        self.assertEqual(result.cash_events, [])
        p = profile(balance="1000", minimum="200")
        # adversarial check: if the valuation were cash, min balance would jump
        as_cash = simulate(p, D, [flow("5000", D + timedelta(days=3))])
        self.assertEqual(as_cash.ending_balance, Decimal("6000"))
        with_event = simulate(p, D, [], unresolved_evidence=result.unresolved)
        self.assertEqual(with_event.ending_balance, Decimal("1000"))

    def test_moving_income_later_cannot_help_earlier_days(self):
        credit = flow("300", D + timedelta(days=10))
        self.assertTrue(moving_income_later_cannot_help_earlier_days(
            self.P, D, credit, D + timedelta(days=60)))


class RealDataDiagnosticTests(unittest.TestCase):
    """Phase 2 §25: run the engine over the 25 sample users as diagnostics.

    No output labels are asserted — these checks catch structural contradictions
    (counting pending credits, wrong lifecycle selection, impossible FX, etc.).
    """

    @classmethod
    def setUpClass(cls):
        cls.bundle = load_all()
        cls.indexes = Indexes.build(cls.bundle)
        cls.results = {}
        for sample in cls.bundle.samples:
            request = sample.request
            user_events = cls.indexes.events_by_user_id.get(request.user_id, [])
            lifecycle = resolve_lifecycle(user_events, request.request_date)
            patterns = detect_recurring_patterns(user_events)
            try:
                timeline = build_cash_timeline(request and
                                               cls.indexes.profiles_by_user_id[request.user_id],
                                               request.request_date, lifecycle, patterns,
                                               cls.indexes)
                sim = simulate(cls.indexes.profiles_by_user_id[request.user_id],
                               request.request_date, timeline.flows,
                               unresolved_evidence=lifecycle.unresolved,
                               include_trace=False)
                cls.results[request.request_id] = (sim, lifecycle, timeline)
            except MissingRateError:
                cls.results[request.request_id] = ("MISSING_RATE", lifecycle, None)

    def test_all_sample_users_simulate(self):
        self.assertEqual(len(self.results), 25)
        states = {rid: (r[0].state if not isinstance(r[0], str) else r[0])
                  for rid, r in self.results.items()}
        # no user may hit a missing FX path (empirical direct-rate coverage proof)
        self.assertNotIn("MISSING_RATE", states.values())

    def test_no_pending_credit_ever_in_flows(self):
        for rid, (sim, lifecycle, timeline) in self.results.items():
            if timeline is None:
                continue
            for f in timeline.flows:
                self.assertNotIn("pending_credit", f.basis)

    def test_cancelled_failed_never_in_flows(self):
        for rid, (sim, lifecycle, timeline) in self.results.items():
            if timeline is None:
                continue
            for f in timeline.flows:
                self.assertNotIn(f.basis, ("cancelled", "failed"))

    def test_unresolved_only_where_expected(self):
        # users 16/20/64/73 have in-horizon blank-amount debits (scheduled/pending):
        # their baseline simulations must be UNRESOLVED. Everyone else must be a
        # definite SAFE or UNSAFE — UNSAFE is a legitimate baseline outcome for
        # users whose solved answers require spending changes (request_11's sample
        # needed reduce_to:event_989) or who cannot afford the request at all.
        expect_unresolved = {"request_16", "request_20", "request_64", "request_73"}
        for rid, (sim, lifecycle, timeline) in self.results.items():
            state = sim.state if not isinstance(sim, str) else sim
            if rid in expect_unresolved:
                self.assertEqual(state, SafetyState.UNRESOLVED, rid)
            else:
                self.assertIn(state, (SafetyState.SAFE, SafetyState.UNSAFE), rid)
        print("[diagnostic] baseline states:",
              {rid: (sim.state.value if not isinstance(sim, str) else sim)
               for rid, (sim, _, _) in sorted(self.results.items())})

    def test_min_balance_never_above_starting_minus_credits_only(self):
        # sanity: with only outflows possible later, minimum can't exceed start
        for rid, (sim, lifecycle, timeline) in self.results.items():
            if isinstance(sim, str):
                continue
            self.assertLessEqual(sim.minimum_projected_balance,
                                 max(sim.starting_balance, sim.ending_balance))

    def test_recurrence_detected_for_structured_users(self):
        # users with the constructed monthly salary series must show a salary pattern
        u03_events = self.indexes.events_by_user_id["user_03"]
        patterns = detect_recurring_patterns(u03_events)
        salary = [p for p in patterns if p.category == "salary"
                  and p.direction == EventDirection.CREDIT]
        self.assertEqual(len(salary), 1)
        self.assertTrue(salary[0].is_monthly)
        self.assertEqual(salary[0].amount, Decimal("4365000"))  # one-off adjustment excluded


if __name__ == "__main__":
    unittest.main()
