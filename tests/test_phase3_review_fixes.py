"""Phase 3 review-fix regression tests (CodeRabbit round: C1, W1, W2, mappings)."""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, profile

from code.finance.simulator import SafetyState  # noqa: F401
from code.finance.timeline import CashFlow
from code.planning.baseline import compute_baseline
from code.planning.candidates import installment_candidates
from code.planning.decision import plan_request
from code.planning.spending_changes import apply_changes_to_flows
from code.schemas import EventDirection


def flow(amount, on_date, category="rent", basis="settled", source=("t",)):
    return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                    category=category,
                    direction_value="debit" if Decimal(amount) < 0 else "credit",
                    basis=basis, source_event_ids=source, essential=False,
                    flexibility="fixed", certainty="actual", event_type="test")


class SeriesKeyedChangesTests(unittest.TestCase):
    """W1: stopping one series must never touch another in the same category."""

    def test_same_category_two_series_isolated(self):
        f_a = CashFlow(amount_home=Decimal("-50"), effective_date=D,
                       category="streaming", direction_value="debit",
                       basis="recurring_projection", source_event_ids=("a1", "a2"),
                       essential=False, flexibility="fixed", certainty="projected",
                       event_type="subscription")
        f_b = CashFlow(amount_home=Decimal("-70"), effective_date=D + timedelta(days=3),
                       category="streaming", direction_value="debit",
                       basis="recurring_projection", source_event_ids=("b1", "b2"),
                       essential=False, flexibility="fixed", certainty="projected",
                       event_type="subscription")
        stop_a = (type("C", (), {"action": "stop", "event_id": "a2", "new_amount": None,
                                 "category": "streaming",
                                 "series_ids": frozenset({"a1", "a2"}),
                                 "monthly_gain": Decimal("50")}),)
        out = apply_changes_to_flows([f_a, f_b], stop_a)
        self.assertEqual([f.source_event_ids for f in out], [("b1", "b2")])


class UncertainBaselinePlanTests(unittest.TestCase):
    """C1: an uncertain baseline can never produce an active recommendation."""

    def test_uncertain_baseline_not_recommended(self):
        p = profile(balance="5000", minimum="90", methods=("full_payment",),
                    max_months=3)
        flows = [flow("-50", D + timedelta(days=3))]
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("2000"),
                             "desired_completion_date": D + timedelta(days=60),
                             "allows_partial_payment": False})()
        unresolved = [type("U", (), {"event_id": "evidence:m1",
                                     "reason": "recurring expense without amount",
                                     "effective_date": D + timedelta(days=3),
                                     "direction": EventDirection.DEBIT,
                                     "category": "childcare"})()]
        decision = plan_request(p, req, flows, [],
                                compute_baseline(p, D, flows, Decimal("2000"),
                                                 unresolved_material=True),
                                [], 3, unresolved=unresolved)
        self.assertEqual(decision.amount_safe_to_pay, Decimal("0"))
        self.assertEqual(decision.recommended_payment_method.value, "not_recommended")
        self.assertIsNone(decision.payment_plan)

    def test_out_of_horizon_unresolved_is_not_material(self):
        # an unresolved debit AFTER the horizon must not force ASP to 0
        p = profile(balance="1000", minimum="90", methods=("full_payment",))
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("500"),
                             "desired_completion_date": D + timedelta(days=60),
                             "allows_partial_payment": False})()
        unresolved = [type("U", (), {"event_id": "evidence:m2",
                                     "reason": "blank amount later",
                                     "effective_date": D + timedelta(days=95),
                                     "direction": EventDirection.DEBIT,
                                     "category": "rent"})()]
        decision = plan_request(p, req, [], [],
                                compute_baseline(p, D, [], Decimal("500"),
                                                 unresolved_material=False),
                                [], None, unresolved=unresolved)
        self.assertEqual(decision.amount_safe_to_pay, Decimal("500"))
        self.assertEqual(decision.recommended_payment_method.value, "full_payment")


class InstallmentGuardTests(unittest.TestCase):
    def _opts(self, **kw):
        from code.schemas import PaymentMethod, PaymentOption
        base = dict(payment_option_id="opt_x", request_id="r",
                    payment_method=PaymentMethod.INSTALLMENTS,
                    payment_amount=Decimal("100"), number_of_payments=3,
                    first_payment_date=D, payment_frequency_days=30,
                    financing_fee=Decimal("0"), total_payable_amount=Decimal("300"))
        base.update(kw)
        return [PaymentOption(**base)]

    def _req(self):
        return type("R", (), {"request_id": "r", "user_id": "u", "request_date": D,
                              "requested_amount": Decimal("300"),
                              "desired_completion_date": D + timedelta(days=120),
                              "allows_partial_payment": False})()

    def _profile(self):
        return profile(balance="5000", minimum="100",
                       methods=("installments", "full_payment"), max_months=12)

    def test_past_dated_option_rejected_not_crash(self):
        cands = installment_candidates(self._profile(), self._req(), [],
                                       self._opts(first_payment_date=D - timedelta(days=10)),
                                       [], 12)
        self.assertTrue(all(c.rejection_reason for c in cands))
        self.assertTrue(any("before request_date" in c.rejection_reason for c in cands))

    def test_non_positive_frequency_rejected(self):
        cands = installment_candidates(self._profile(), self._req(), [],
                                       self._opts(payment_frequency_days=0), [], 12)
        self.assertTrue(any("non-positive frequency" in c.rejection_reason for c in cands))

    def test_exact_limit_and_just_over(self):
        # 3 payments x 30d = 60d span; cap 2 months = 60d -> eligible
        cands = installment_candidates(self._profile(), self._req(), [],
                                       self._opts(), [], 2)
        self.assertTrue(any(c.rejection_reason is None for c in cands))
        # cap 1 month = 30d < 60d span -> all rejected with span reason
        cands = installment_candidates(self._profile(), self._req(), [],
                                       self._opts(), [], 1)
        self.assertTrue(all(c.rejection_reason and "span" in c.rejection_reason
                            for c in cands if c.rejection_reason))


class StatusMappingTests(unittest.TestCase):
    def test_full_with_changes_maps_to_with_plan(self):
        p = profile(balance="600", minimum="90", methods=("full_payment",))
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("450"),
                             "desired_completion_date": D + timedelta(days=30),
                             "allows_partial_payment": False})()
        # baseline: full today unsafe (450 + 100 outflow dips below 90); stopping
        # the 100/month streaming series rescues it -> affordable_with_plan
        flows = [CashFlow(amount_home=Decimal("-100"), effective_date=D + timedelta(days=10),
                          category="streaming", direction_value="debit",
                          basis="recurring_projection",
                          source_event_ids=("st1", "st2"), essential=False,
                          flexibility="fixed", certainty="projected",
                          event_type="subscription")]
        actions = [type("A", (), {"action": "stop", "event_id": "st2", "new_amount": None,
                                  "category": "streaming",
                                  "series_ids": frozenset({"st1", "st2"}),
                                  "monthly_gain": Decimal("350")})()]
        decision = plan_request(p, req, flows, [],
                                compute_baseline(p, D, flows, Decimal("450"), False),
                                actions, None)
        self.assertEqual(decision.recommended_payment_method.value, "full_payment")
        self.assertEqual(decision.affordability_status.value, "affordable_with_plan")
        self.assertTrue(decision.spending_changes)
        # baseline ASP/earliest are NOT rewritten by the rescue
        self.assertEqual(decision.amount_safe_to_pay, decision.baseline.amount_safe_to_pay)
        self.assertEqual(decision.earliest_date_for_full_payment,
                         decision.baseline.earliest_date_for_full_payment)

    def test_wait_maps_to_affordable_later(self):
        p = profile(balance="100", minimum="90", methods=("full_payment",))
        flows = [CashFlow(amount_home=Decimal("2000"), effective_date=D + timedelta(days=30),
                          category="salary", direction_value="credit",
                          basis="scheduled", source_event_ids=("s",), essential=False,
                          flexibility="fixed", certainty="actual", event_type="income")]
        req = type("R", (), {"request_id": "r", "user_id": "u",
                             "request_date": D, "requested_amount": Decimal("1500"),
                             "desired_completion_date": D + timedelta(days=60),
                             "allows_partial_payment": False})()
        decision = plan_request(p, req, flows, [],
                                compute_baseline(p, D, flows, Decimal("1500"), False),
                                [], None)
        self.assertEqual(decision.recommended_payment_method.value, "wait")
        self.assertEqual(decision.affordability_status.value, "affordable_later")
        self.assertEqual(decision.payment_plan[0].payment_date, D + timedelta(days=30))


if __name__ == "__main__":
    unittest.main()
