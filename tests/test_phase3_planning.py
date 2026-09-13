"""Phase 3 planner tests: ASP, earliest, candidates, changes, ranking."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, ev, profile

from code.errors import DataError
from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow, horizon_end
from code.planning.baseline import compute_baseline
from code.planning.candidates import (full_payment_candidates, installment_candidates,
                                      partial_payment_candidate, wait_candidate)
from code.planning.decision import explanation_facts, plan_request
from code.planning.models import Method
from code.planning.ranker import rank_candidates, rank_key
from code.planning.spending_changes import (ChangeAction, apply_changes_to_flows,
                                            bounded_change_sets, validate_change_set)
from code.schemas import Flexibility


def flow(amount, on_date, category="rent", basis="settled"):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category=category,
                    direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis=basis, source_event_ids=("t",), essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class AspTests(unittest.TestCase):
    def test_asp_zero_when_baseline_exactly_at_floor(self):
        p = profile(balance="1000", minimum="200")
        flows = [flow("-800", D)]
        m = compute_baseline(p, D, flows, Decimal("500"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("0"))

    def test_asp_exact_headroom(self):
        p = profile(balance="1000", minimum="200")
        flows = [flow("-300", D + timedelta(days=5))]
        m = compute_baseline(p, D, flows, Decimal("10000"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("500"))
        sim = simulate(p, D, flows, hypothetical_payments=[Payment(D, m.amount_safe_to_pay)])
        self.assertEqual(sim.state, SafetyState.SAFE)

    def test_asp_plus_quantum_unsafe(self):
        p = profile(balance="1000", minimum="200")
        flows = [flow("-300", D + timedelta(days=5))]
        m = compute_baseline(p, D, flows, Decimal("10000"), False)
        sim = simulate(p, D, flows,
                       hypothetical_payments=[Payment(D, m.amount_safe_to_pay + Decimal("0.01"))])
        self.assertEqual(sim.state, SafetyState.UNSAFE)

    def test_asp_capped_at_requested(self):
        p = profile(balance="100000", minimum="200")
        m = compute_baseline(p, D, [], Decimal("500"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("500"))

    def test_asp_requested_below_headroom(self):
        p = profile(balance="1000", minimum="200")
        m = compute_baseline(p, D, [], Decimal("300"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("300"))

    def test_asp_unresolved_baseline_falls_back_to_zero(self):
        p = profile(balance="1000", minimum="200")
        m = compute_baseline(p, D, [flow("-100", D)], Decimal("500"),
                             unresolved_material=True)
        self.assertEqual(m.amount_safe_to_pay, Decimal("0"))
        self.assertTrue(m.asp_uncertain)

    def test_asp_unsafe_baseline_falls_back_to_zero(self):
        p = profile(balance="100", minimum="200")
        flows = [flow("-500", D + timedelta(days=3))]
        m = compute_baseline(p, D, flows, Decimal("500"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("0"))

    def test_asp_fx_fractional_floor(self):
        p = profile(balance="1000.005", minimum="200")
        m = compute_baseline(p, D, [], Decimal("5000"), False)
        self.assertEqual(m.amount_safe_to_pay, Decimal("800.00"))


class EarliestTests(unittest.TestCase):
    def test_earliest_today_when_headroom_covers_request(self):
        p = profile(balance="1000", minimum="200")
        m = compute_baseline(p, D, [], Decimal("500"), False)
        self.assertEqual(m.earliest_date_for_full_payment, D)

    def test_earliest_future_on_payday_shape(self):
        p = profile(balance="100", minimum="90")
        flows = [flow("2000", D + timedelta(days=30), category="salary")]
        m = compute_baseline(p, D, flows, Decimal("1500"), False)
        self.assertEqual(m.earliest_date_for_full_payment, D + timedelta(days=30))

    def test_earliest_none_when_never_safe(self):
        p = profile(balance="100", minimum="90")
        flows = [flow("-50", D + timedelta(days=1))]
        m = compute_baseline(p, D, flows, Decimal("1500"), False)
        self.assertIsNone(m.earliest_date_for_full_payment)

    def test_earliest_none_when_unresolved(self):
        p = profile(balance="1000", minimum="90")
        m = compute_baseline(p, D, [flow("-1", D)], Decimal("500"),
                             unresolved_material=True)
        self.assertIsNone(m.earliest_date_for_full_payment)

    def test_earliest_invariants(self):
        p = profile(balance="100", minimum="90")
        flows = [flow("2000", D + timedelta(days=30), category="salary")]
        requested = Decimal("1500")
        m = compute_baseline(p, D, flows, requested, False)
        earliest = m.earliest_date_for_full_payment
        sim = simulate(p, D, flows, hypothetical_payments=[Payment(earliest, requested)])
        self.assertEqual(sim.state, SafetyState.SAFE)
        sim_before = simulate(p, D, flows,
                              hypothetical_payments=[Payment(earliest - timedelta(days=1), requested)])
        self.assertEqual(sim_before.state, SafetyState.UNSAFE)
        sim_today = simulate(p, D, flows, hypothetical_payments=[Payment(D, requested)])
        self.assertEqual(sim_today.state is SafetyState.SAFE, earliest == D)


class SpendingChangeTests(unittest.TestCase):
    def test_max_three_and_conflict(self):
        acts = [ChangeAction("stop", f"e{i}", None, "c", frozenset({f"e{i}"}), Decimal("0"))
                for i in range(4)]
        self.assertIsNotNone(validate_change_set(tuple(acts)))
        pair = (ChangeAction("stop", "e1", None, "c", frozenset({"e1"}), Decimal("0")),
                ChangeAction("reduce_to", "e1", Decimal("5"), "c", frozenset({"e1"}), Decimal("0")))
        self.assertIsNotNone(validate_change_set(pair))

    def test_bounded_levels(self):
        acts = [ChangeAction("stop", f"e{i}", None, "c", ("c", "debit"), Decimal("1"))
                for i in range(4)]
        self.assertEqual(len(bounded_change_sets(acts, 1)), 4)
        self.assertEqual(len(bounded_change_sets(acts, 2)), 6)
        self.assertEqual(len(bounded_change_sets(acts, 3)), 4)

    def test_stop_removes_projected_flows_only(self):
        f_proj = CashFlow(amount_home=Decimal("-50"), effective_date=D,
                          category="streaming", direction_value="debit",
                          basis="recurring_projection", source_event_ids=("s1",),
                          essential=False, flexibility="fixed", certainty="projected",
                          event_type="subscription")
        f_hist = CashFlow(amount_home=Decimal("-50"), effective_date=D,
                          category="streaming", direction_value="debit",
                          basis="settled", source_event_ids=("s1",),
                          essential=False, flexibility="fixed", certainty="actual",
                          event_type="expense")
        changes = (ChangeAction("stop", "s1", None, "streaming", frozenset({"s1"}),
                                Decimal("50")),)
        out = apply_changes_to_flows([f_proj, f_hist], changes)
        self.assertEqual([f for f in out if f.basis == "settled"], [f_hist])
        self.assertEqual([f for f in out if f.basis == "recurring_projection"], [])


class RankerTests(unittest.TestCase):
    def _cand(self, method, total, changes=(), deadline=True, option=None, count=1):
        payments = tuple(type("P", (), {"payment_date": D, "amount": Decimal("0")})()
                         for _ in range(count))
        return type("C", (), {
            "method": method, "payments": payments, "changes": changes,
            "total_paid": total, "first_payment_date": D,
            "last_payment_date": D + timedelta(days=30) if deadline else D + timedelta(days=200),
            "completes_by_deadline": deadline, "payment_option_id": option,
            "sim_state": SafetyState.SAFE, "sim_minimum": Decimal("0"),
            "rejection_reason": None, "uses_spending_changes": bool(changes),
            "payment_count": count, "diagnostics": ()})()

    def test_official_order(self):
        full = self._cand(Method.FULL_PAYMENT, Decimal("100"))
        inst = self._cand(Method.INSTALLMENTS, Decimal("110"), option="payment_option_02")
        ranked = rank_candidates([inst, full])
        self.assertIs(ranked[0], full)

    def test_changes_lose_without_contradiction(self):
        clean = self._cand(Method.FULL_PAYMENT, Decimal("100"))
        changed = self._cand(Method.FULL_PAYMENT, Decimal("100"),
                             changes=(ChangeAction("stop", "e1", None, "c",
                                                   ("c", "debit"), Decimal("1")),))
        ranked = rank_candidates([changed, clean])
        self.assertIs(ranked[0], clean)

    def test_internal_tie_break_only_after_official(self):
        ch_a = (ChangeAction("stop", "a1", None, "c", frozenset({"a1"}), Decimal("1")),)
        ch_b = (ChangeAction("stop", "b1", None, "c", frozenset({"b1"}), Decimal("1")),)
        cand_a = self._cand(Method.FULL_PAYMENT, Decimal("100"), changes=ch_a)
        cand_b = self._cand(Method.FULL_PAYMENT, Decimal("100"), changes=ch_b)
        ranked = rank_candidates([cand_b, cand_a])
        self.assertIs(ranked[0], cand_a)


class PlanRequestTests(unittest.TestCase):
    def test_full_payment_affordable_now(self):
        p = profile(balance="5000", minimum="1000", methods=("full_payment",))
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("2000"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        decision = plan_request(p, req, [], [], compute_baseline(p, D, [], Decimal("2000"), False), [], None)
        self.assertEqual(decision.affordability_status.value, "affordable_now")
        self.assertEqual(decision.recommended_payment_method.value, "full_payment")
        self.assertEqual(decision.amount_safe_to_pay, Decimal("2000"))

    def test_fallback_not_recommended(self):
        p = profile(balance="100", minimum="90", methods=("full_payment",))
        flows = [flow("-1", D + timedelta(days=1))]
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("5000"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        decision = plan_request(p, req, flows, [],
                                compute_baseline(p, D, flows, Decimal("5000"), False), [], None)
        self.assertEqual(decision.recommended_payment_method.value, "not_recommended")
        self.assertIsNone(decision.payment_plan)
        self.assertEqual(decision.affordability_status.value, "not_affordable")
        self.assertGreaterEqual(decision.amount_safe_to_pay, Decimal("0"))

    def test_disallowed_method_never_wins(self):
        p = profile(balance="5000", minimum="1000",
                    methods=("installments",), max_months=3)
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("2000"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        decision = plan_request(p, req, [], [], compute_baseline(p, D, [], Decimal("2000"), False), [], 3)
        self.assertNotEqual(decision.recommended_payment_method.value, "full_payment")

    def test_unresolved_asp_fallback(self):
        p = profile(balance="1000", minimum="90", methods=("full_payment",))
        flows = [flow("-50", D + timedelta(days=3))]
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("2000"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        decision = plan_request(p, req, flows, [],
                                compute_baseline(p, D, flows, Decimal("2000"),
                                                 unresolved_material=True), [], None)
        self.assertEqual(decision.amount_safe_to_pay, Decimal("0"))
        self.assertTrue(decision.baseline.asp_uncertain)

    def test_explanation_facts_deterministic(self):
        p = profile(balance="5000", minimum="1000", methods=("full_payment",))
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("2000"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        d1 = plan_request(p, req, [], [], compute_baseline(p, D, [], Decimal("2000"), False), [], None)
        d2 = plan_request(p, req, [], [], compute_baseline(p, D, [], Decimal("2000"), False), [], None)
        self.assertEqual(explanation_facts(d1), explanation_facts(d2))


if __name__ == "__main__":
    unittest.main()
