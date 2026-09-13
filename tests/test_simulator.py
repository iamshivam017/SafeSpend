import unittest
from datetime import date, timedelta
from decimal import Decimal

from _finance_fixture import D, profile

from code.finance.lifecycle import UnresolvedEvidence
from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow
from code.schemas import EventDirection


def flow(amount, on_date, category="rent", basis="settled"):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category=category, direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis=basis, source_event_ids=("t",), essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class BasicSimulationTests(unittest.TestCase):
    def test_starting_balance_only(self):
        r = simulate(profile(balance="1000", minimum="200"), D, [])
        self.assertEqual(r.state, SafetyState.SAFE)
        self.assertEqual(r.ending_balance, Decimal("1000"))
        self.assertEqual(r.minimum_projected_balance, Decimal("1000"))

    def test_single_settled_debit(self):
        r = simulate(profile(balance="1000", minimum="200"), D, [flow("-300", D)])
        self.assertEqual(r.ending_balance, Decimal("700"))

    def test_single_settled_credit(self):
        r = simulate(profile(balance="1000", minimum="200"), D, [flow("300", D)])
        self.assertEqual(r.ending_balance, Decimal("1300"))

    def test_min_balance_exactly_met_is_safe(self):
        r = simulate(profile(balance="500", minimum="200"), D, [flow("-300", D)])
        self.assertEqual(r.minimum_projected_balance, Decimal("200"))
        self.assertEqual(r.state, SafetyState.SAFE)

    def test_min_balance_violated_by_0_01_is_unsafe(self):
        r = simulate(profile(balance="500", minimum="200"), D, [flow("-300.01", D)])
        self.assertEqual(r.state, SafetyState.UNSAFE)
        self.assertEqual(r.first_floor_violation_date, D)

    def test_temporary_violation_with_late_recovery_is_unsafe(self):
        # balance 60, min 50: debit 20 today, salary 100 tomorrow -> 40 < 50 today
        p = profile(balance="60", minimum="50")
        r = simulate(p, D, [flow("-20", D), flow("100", D + timedelta(days=1))])
        self.assertEqual(r.state, SafetyState.UNSAFE)
        self.assertEqual(r.first_floor_violation_date, D)

    def test_confirmed_salary_tomorrow_does_not_sanction_today(self):
        p = profile(balance="100", minimum="90")
        r = simulate(p, D, [flow("-50", D), flow("500", D + timedelta(days=1))])
        self.assertEqual(r.state, SafetyState.UNSAFE)

    def test_violation_after_recovery_still_detected(self):
        p = profile(balance="1000", minimum="200")
        r = simulate(p, D, [flow("-700", D), flow("500", D + timedelta(days=5)),
                            flow("-700", D + timedelta(days=10))])
        self.assertEqual(r.state, SafetyState.UNSAFE)
        self.assertEqual(r.first_floor_violation_date, D + timedelta(days=10))


class SameDayOrderingTests(unittest.TestCase):
    def test_same_day_salary_and_debit_netted(self):
        # D6 rev. 2 (Phase 2.1, sample evidence: requests 18/23 pay on payday):
        # the floor is checked on the END-OF-DAY balance, so a same-day salary
        # and debit net before the check. 100 - 50 + 50 = 100 >= 90 -> SAFE.
        p = profile(balance="100", minimum="90")
        r = simulate(p, D, [flow("50", D, category="salary"), flow("-50", D)])
        self.assertEqual(r.state, SafetyState.SAFE)

    def test_same_day_net_below_floor_is_unsafe(self):
        # netting is not leniency: if the day's NET drops below the floor it is
        # still a violation (100 - 50 - 50 = 0 < 90)
        p = profile(balance="100", minimum="90")
        r = simulate(p, D, [flow("50", D, category="salary"), flow("-100", D)])
        self.assertEqual(r.state, SafetyState.UNSAFE)

    def test_movement_order_does_not_affect_outcome(self):
        # EOD balance is order-independent; only trace presentation is ordered
        p = profile(balance="1000", minimum="200")
        flows = [flow(f"{'-' if i % 2 else '+'}{50 + i}", D + timedelta(days=i % 3))
                 for i in range(6)]
        r1 = simulate(p, D, flows, include_trace=True)
        r2 = simulate(p, D, list(reversed(flows)), include_trace=True)
        self.assertEqual(r1.ending_balance, r2.ending_balance)
        self.assertEqual(r1.minimum_projected_balance, r2.minimum_projected_balance)
        self.assertEqual([(e.date, e.ending_balance) for e in r1.timeline],
                         [(e.date, e.ending_balance) for e in r2.timeline])
        # trace presentation is still deterministic: debits before credits
        day0 = [e for e in r1.timeline if e.date == D][0]
        signs = [m[1] for m in day0.movements]
        debits = [s for s in signs if s < 0]
        credits = [s for s in signs if s >= 0]
        self.assertEqual(signs, debits + credits)
        self.assertEqual(debits, sorted(debits))


class HypotheticalPaymentTests(unittest.TestCase):
    def test_single_hypothetical_payment(self):
        p = profile(balance="1000", minimum="200")
        r = simulate(p, D, [flow("-100", D)], hypothetical_payments=[Payment(D, Decimal("600"))])
        self.assertEqual(r.ending_balance, Decimal("300"))
        self.assertEqual(r.state, SafetyState.SAFE)

    def test_multiple_hypothetical_payments(self):
        p = profile(balance="1000", minimum="200")
        payments = [Payment(D, Decimal("500")), Payment(D + timedelta(days=30), Decimal("400"))]
        r = simulate(p, D, [], hypothetical_payments=payments)
        self.assertEqual(r.ending_balance, Decimal("100"))
        self.assertEqual(r.state, SafetyState.UNSAFE)  # 100 < 200

    def test_payment_on_day90_is_inside_horizon(self):
        p = profile(balance="1000", minimum="200")
        r = simulate(p, D, [], hypothetical_payments=[Payment(D + timedelta(days=90),
                                                              Decimal("900"))])
        self.assertEqual(r.state, SafetyState.UNSAFE)  # 1000-900=100 < 200

    def test_payment_after_day90_rejected(self):
        # review fix: out-of-window payments raise instead of being silently
        # ignored (silent skipping would fake feasibility)
        p = profile(balance="1000", minimum="200")
        from code.errors import DataError
        with self.assertRaises(DataError):
            simulate(p, D, [], hypothetical_payments=[Payment(D + timedelta(days=91),
                                                              Decimal("900"))])
        with self.assertRaises(DataError):
            simulate(p, D, [], hypothetical_payments=[Payment(D - timedelta(days=1),
                                                              Decimal("900"))])


class UnresolvedEvidenceTests(unittest.TestCase):
    def test_unresolved_debit_makes_state_unresolved(self):
        p = profile(balance="5000", minimum="200")
        u = UnresolvedEvidence(event_id="e_blank", reason="blank amount",
                               effective_date=D + timedelta(days=3),
                               direction=EventDirection.DEBIT, category="rent")
        r = simulate(p, D, [], unresolved_evidence=[u])
        self.assertEqual(r.state, SafetyState.UNRESOLVED)

    def test_unresolved_outside_horizon_does_not_matter(self):
        p = profile(balance="5000", minimum="200")
        u = UnresolvedEvidence(event_id="e_blank", reason="blank amount",
                               effective_date=D + timedelta(days=91),
                               direction=EventDirection.DEBIT, category="rent")
        r = simulate(p, D, [], unresolved_evidence=[u])
        self.assertEqual(r.state, SafetyState.SAFE)

    def test_unresolved_credit_ignored(self):
        p = profile(balance="5000", minimum="200")
        u = UnresolvedEvidence(event_id="e_blank", reason="blank amount",
                               effective_date=D + timedelta(days=3),
                               direction=EventDirection.CREDIT, category="refund")
        r = simulate(p, D, [], unresolved_evidence=[u])
        self.assertEqual(r.state, SafetyState.SAFE)

    def test_trace_deterministic_and_complete(self):
        p = profile(balance="1000", minimum="200")
        flows = [flow("-100", D), flow("50", D + timedelta(days=1))]
        r1 = simulate(p, D, flows)
        r2 = simulate(p, D, list(flows))
        self.assertEqual([(e.date, e.ending_balance) for e in r1.timeline],
                         [(e.date, e.ending_balance) for e in r2.timeline])
        self.assertEqual(len(r1.timeline), 91)  # day 0..90 inclusive


if __name__ == "__main__":
    unittest.main()
