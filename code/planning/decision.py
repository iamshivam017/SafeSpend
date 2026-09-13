"""Decision assembly: candidates -> internal Decision (Phase 3).

Deterministic status mapping (directive Part 23):
  full_payment today, no changes      -> affordable_now
  partial_payment                     -> affordable_with_plan
  installments                        -> affordable_with_plan
  full_payment today with changes     -> affordable_with_plan
  other immediate plan with changes   -> affordable_with_plan
  wait                                -> affordable_later
  no safe eligible deadline candidate -> not_affordable

Fallback (Part 22): when no provably-safe eligible candidate completes the
request by its deadline, the decision is not_recommended / none / none /
not_affordable while ASP and earliest retain their independent baseline values.
"""
from __future__ import annotations

from decimal import Decimal

from ..finance.simulator import SafetyState
from ..finance.timeline import CashFlow
from ..schemas import FinancialProfile, Request
from .candidates import (full_payment_candidates, installment_candidates,
                         partial_payment_candidate, wait_candidate)
from .models import Affordability, BaselineMetrics, Decision, Method, PaymentCandidate
from .ranker import best_candidate_for_method, rank_candidates
from .spending_changes import ChangeAction, bounded_change_sets


def _contract_changes(actions: tuple[ChangeAction, ...]):
    from ..output_validator import SpendingChange
    return tuple(SpendingChange(action=a.action, event_id=a.event_id,
                                new_amount=a.new_amount) for a in actions)


def plan_request(profile: FinancialProfile, request: Request,
                 baseline_flows: list[CashFlow], options: list,
                 baseline: BaselineMetrics,
                 eligible_actions: list[ChangeAction],
                 max_installment_months: int | None,
                 unresolved: list | None = None) -> Decision:
    all_candidates: list[PaymentCandidate] = []
    evaluated: set[tuple] = set()
    # bounded search: singles -> pairs -> triples; every change-set is
    # simulated exactly once (W3 review fix: no duplicated work, no premature
    # break that could suppress a better deeper rescue)
    for level in (1, 2, 3):
        level_sets = bounded_change_sets(eligible_actions, level)
        new_sets = [s for s in level_sets
                    if tuple(sorted((c.action, c.event_id, str(c.new_amount))
                                    for c in s)) not in evaluated]
        all_candidates.extend(full_payment_candidates(
            profile, request, baseline_flows, new_sets, unresolved=unresolved))
        all_candidates.extend(partial_payment_candidate(
            profile, request, baseline_flows, baseline.amount_safe_to_pay,
            baseline.earliest_date_for_full_payment, new_sets, unresolved=unresolved))
        all_candidates.extend(installment_candidates(
            profile, request, baseline_flows, options, new_sets,
            max_installment_months, unresolved=unresolved))
        for s in new_sets:
            evaluated.add(tuple(sorted((c.action, c.event_id, str(c.new_amount))
                                       for c in s)))
    all_candidates.extend(wait_candidate(profile, request, baseline_flows,
                                         baseline.earliest_date_for_full_payment,
                                         unresolved=unresolved))

    # official ranking across all recommendable candidates
    ranked = rank_candidates(all_candidates)
    selected = ranked[0] if ranked else None

    reason_codes: list[str] = []
    if selected is None:
        for c in all_candidates:
            if c.rejection_reason and c.rejection_reason not in reason_codes:
                reason_codes.append(c.rejection_reason)
        reasons = tuple(reason_codes[:5]) or ("no safe eligible deadline-completing candidate",)
        return Decision(
            request_id=request.request_id,
            amount_safe_to_pay=baseline.amount_safe_to_pay,
            affordability_status=Affordability.NOT_AFFORDABLE,
            recommended_payment_method=Method.NOT_RECOMMENDED,
            payment_plan=None,
            earliest_date_for_full_payment=baseline.earliest_date_for_full_payment,
            spending_changes=(),
            selected_candidate=None,
            baseline=baseline,
            reason_codes=reasons)

    if selected.method is Method.FULL_PAYMENT:
        status = (Affordability.AFFORDABLE_NOW if not selected.uses_spending_changes
                  else Affordability.AFFORDABLE_WITH_PLAN)
    elif selected.method is Method.PARTIAL_PAYMENT:
        status = Affordability.AFFORDABLE_WITH_PLAN
    elif selected.method is Method.INSTALLMENTS:
        status = Affordability.AFFORDABLE_WITH_PLAN
    else:  # wait
        status = Affordability.AFFORDABLE_LATER

    return Decision(
        request_id=request.request_id,
        amount_safe_to_pay=baseline.amount_safe_to_pay,
        affordability_status=status,
        recommended_payment_method=selected.method,
        payment_plan=selected.payments,
        earliest_date_for_full_payment=baseline.earliest_date_for_full_payment,
        spending_changes=_contract_changes(selected.changes),
        selected_candidate=selected,
        baseline=baseline,
        reason_codes=(f"ranked first of {len(ranked)} recommendable candidates",))


def explanation_facts(decision: Decision) -> dict:
    """Deterministic structured explanation facts (no LLM; Phase 5 calibrates wording)."""
    facts: dict = {
        "request_id": decision.request_id,
        "amount_safe_to_pay": str(decision.amount_safe_to_pay),
        "status": decision.affordability_status.value,
        "method": decision.recommended_payment_method.value,
        "plan": None if decision.payment_plan is None else [
            (p.payment_date.isoformat(), str(p.amount)) for p in decision.payment_plan],
        "earliest_date": (decision.earliest_date_for_full_payment.isoformat()
                          if decision.earliest_date_for_full_payment else None),
        "spending_changes": [f"{c.action}:{c.event_id}"
                             + (f":{c.new_amount}" if c.new_amount is not None else "")
                             for c in decision.spending_changes],
        "minimum_balance_protected": str(decision.baseline.minimum_balance_required),
        "baseline_minimum": str(decision.baseline.baseline_minimum),
    }
    if decision.baseline.asp_uncertain:
        facts["uncertainty"] = list(decision.baseline.uncertainty_notes)
    if decision.recommended_payment_method is Method.WAIT:
        facts["why_wait"] = ("full payment is not safe today; it becomes safe on "
                             + (decision.earliest_date_for_full_payment.isoformat() or "n/a"))
    if decision.recommended_payment_method is Method.NOT_RECOMMENDED:
        facts["why_not_recommended"] = list(decision.reason_codes) or \
            ["no safe eligible candidate completes the request by its deadline"]
    if decision.selected_candidate is not None \
            and decision.selected_candidate.payment_option_id:
        facts["payment_option_id"] = decision.selected_candidate.payment_option_id
    return facts
