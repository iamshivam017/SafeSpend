"""Candidate generation and evaluation (Phase 3).

Candidate families (official semantics):
- full_payment today (baseline; affordable_now when no changes needed)
- full_payment today rescued by spending changes (affordable_with_plan;
  canonical samples: request_06 / request_11 / request_21)
- partial_payment: EXACTLY two payments (ASP on request_date, remainder on
  the official earliest date), summing exactly to requested_amount
- installments: one candidate per eligible SUPPLIED option, reproduced
  exactly (dates = first_payment_date + k*frequency_days, amounts =
  payment_amount, fees included via total_payable_amount)
- wait: single payment of requested_amount on the official earliest date

Every candidate is independently simulated with its complete schedule. Only
SafetyState.SAFE candidates are financially eligible; UNRESOLVED and UNSAFE
candidates can never win. ASP and earliest remain baseline values regardless
of which candidate wins.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from ..finance.simulator import Payment, SafetyState, simulate
from ..finance.timeline import CashFlow, horizon_end
from ..output_validator import PlanEntry
from ..schemas import FinancialProfile, Request
from .models import ChangeAction, Method, PaymentCandidate
from .spending_changes import apply_changes_to_flows


def _evaluate(profile: FinancialProfile, request: Request, flows: list[CashFlow],
              payments: list[Payment], method: Method, changes: tuple = (),
              payment_option_id: str | None = None,
              diagnostics: tuple[str, ...] = (),
              unresolved: list | None = None) -> PaymentCandidate:
    # C1 (review fix): material unresolved evidence MUST reach every candidate
    # simulation - UNRESOLVED can never silently count as SAFE.
    sim = simulate(profile, request.request_date, flows,
                   hypothetical_payments=payments,
                   unresolved_evidence=unresolved or None, include_trace=False)
    entries = tuple(PlanEntry(payment_date=p.payment_date, amount=p.amount)
                    for p in payments)
    last = max((p.payment_date for p in payments), default=None)
    return PaymentCandidate(
        method=method, payments=entries, changes=tuple(changes),
        total_paid=sum((p.amount for p in payments), Decimal("0")),
        first_payment_date=min((p.payment_date for p in payments), default=None),
        last_payment_date=last,
        completes_by_deadline=(last is not None
                               and last <= request.desired_completion_date),
        payment_option_id=payment_option_id,
        sim_state=sim.state, sim_minimum=sim.minimum_projected_balance,
        rejection_reason=(None if sim.state is SafetyState.SAFE
                          else f"simulator state {sim.state.value}"),
        diagnostics=diagnostics)


def _with_changes(baseline_flows: list[CashFlow],
                  changes: tuple[ChangeAction, ...]) -> list[CashFlow]:
    return apply_changes_to_flows(baseline_flows, changes)


def full_payment_candidates(profile: FinancialProfile, request: Request,
                            baseline_flows: list[CashFlow],
                            change_sets: list[tuple[ChangeAction, ...]],
                            unresolved: list | None = None) -> list[PaymentCandidate]:
    """Full payment today: baseline candidate + spending-change rescues."""
    out = []
    if Method.FULL_PAYMENT.value not in profile.payment_methods_user_will_consider:
        return [PaymentCandidate(method=Method.FULL_PAYMENT,
                                 payments=(PlanEntry(request.request_date, request.requested_amount),),
                                 total_paid=request.requested_amount,
                                 first_payment_date=request.request_date,
                                 last_payment_date=request.request_date,
                                 rejection_reason="user does not consider full_payment")]
    # baseline (no changes)
    out.append(_evaluate(profile, request, baseline_flows,
                         [Payment(request.request_date, request.requested_amount)],
                         Method.FULL_PAYMENT, (), unresolved=unresolved))
    # rescued by spending changes (baseline full-today is expected unsafe here)
    for changes in change_sets:
        if not changes:
            continue
        out.append(_evaluate(profile, request, _with_changes(baseline_flows, changes),
                             [Payment(request.request_date, request.requested_amount)],
                             Method.FULL_PAYMENT, changes, unresolved=unresolved))
    return out


def partial_payment_candidate(profile: FinancialProfile, request: Request,
                              baseline_flows: list[CashFlow], asp: Decimal,
                              earliest: date | None,
                              change_sets: list[tuple[ChangeAction, ...]],
                              unresolved: list | None = None) -> list[PaymentCandidate]:
    """Partial payment: exactly two payments (official formula), no option match."""
    if Method.PARTIAL_PAYMENT.value not in profile.payment_methods_user_will_consider:
        return [PaymentCandidate(method=Method.PARTIAL_PAYMENT, payments=(),
                                 rejection_reason="user does not consider partial_payment")]
    if not request.allows_partial_payment:
        return [PaymentCandidate(method=Method.PARTIAL_PAYMENT, payments=(),
                                 rejection_reason="request does not allow partial payment")]
    if not (Decimal("0") < asp < request.requested_amount):
        return [PaymentCandidate(method=Method.PARTIAL_PAYMENT, payments=(),
                                 rejection_reason="requires 0 < ASP < requested_amount")]
    if earliest is None:
        return [PaymentCandidate(method=Method.PARTIAL_PAYMENT, payments=(),
                                 rejection_reason="full amount never safe within horizon")]
    if earliest > request.desired_completion_date:
        return [PaymentCandidate(method=Method.PARTIAL_PAYMENT, payments=(),
                                 rejection_reason="earliest_date is after desired_completion_date")]
    remainder = request.requested_amount - asp
    payments = [Payment(request.request_date, asp),
                Payment(earliest, remainder)]
    out = [_evaluate(profile, request, baseline_flows, payments,
                     Method.PARTIAL_PAYMENT, (), unresolved=unresolved)]
    # spending-change rescue when the unchanged partial schedule is not safe
    if out[0].sim_state is not SafetyState.SAFE:
        for changes in change_sets:
            if not changes:
                continue
            out.append(_evaluate(profile, request, _with_changes(baseline_flows, changes),
                                 payments, Method.PARTIAL_PAYMENT, changes,
                                 unresolved=unresolved))
    return out


def installment_candidates(profile: FinancialProfile, request: Request,
                           baseline_flows: list[CashFlow],
                           options: list,
                           change_sets: list[tuple[ChangeAction, ...]],
                           max_installment_months: int | None,
                           unresolved: list | None = None) -> list[PaymentCandidate]:
    """One candidate per eligible SUPPLIED installment option (exact reproduction)."""
    out = []
    if Method.INSTALLMENTS.value not in profile.payment_methods_user_will_consider:
        return [PaymentCandidate(method=Method.INSTALLMENTS, payments=(),
                                 rejection_reason="user does not consider installments")]
    if max_installment_months is None:
        return [PaymentCandidate(method=Method.INSTALLMENTS, payments=(),
                                 rejection_reason="max_installment_months blank: "
                                                  "user will not consider installments")]
    cap_days = max_installment_months * 30  # D8: 30-day month convention
    for option in options:
        if option.payment_method.value != "installments":
            continue
        freq = option.payment_frequency_days
        if freq is not None and freq <= 0:
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: non-positive frequency"))
            continue
        if option.payment_amount is None or option.payment_amount <= 0:
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: non-positive payment amount"))
            continue
        if option.first_payment_date < request.request_date:
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: first_payment_date before "
                                 f"request_date"))
            continue
        if freq is None or option.number_of_payments < 2:
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: malformed installment option"))
            continue
        dates = [option.first_payment_date + timedelta(days=freq * k)
                 for k in range(option.number_of_payments)]
        if dates[-1] > request.request_date + timedelta(days=90):
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: schedule extends beyond "
                                 f"the 90-day forecast horizon"))
            continue
        span_days = (dates[-1] - dates[0]).days
        if span_days > cap_days:
            out.append(PaymentCandidate(
                method=Method.INSTALLMENTS, payments=(),
                rejection_reason=f"{option.payment_option_id}: span {span_days}d exceeds "
                                 f"max_installment_months {max_installment_months} "
                                 f"(D8: {cap_days}d cap)"))
            continue
        payments = [Payment(d, option.payment_amount) for d in dates]
        candidates = [_evaluate(profile, request, baseline_flows, payments,
                                Method.INSTALLMENTS, (), option.payment_option_id,
                                unresolved=unresolved)]
        if candidates[0].sim_state is not SafetyState.SAFE:
            for changes in change_sets:
                if not changes:
                    continue
                candidates.append(_evaluate(
                    profile, request, _with_changes(baseline_flows, changes),
                    payments, Method.INSTALLMENTS, changes, option.payment_option_id,
                    unresolved=unresolved))
        out.extend(candidates)
    if not out:
        out = [PaymentCandidate(method=Method.INSTALLMENTS, payments=(),
                                rejection_reason="no installment options supplied")]
    return out


def wait_candidate(profile: FinancialProfile, request: Request,
                   baseline_flows: list[CashFlow], earliest: date | None,
                   unresolved: list | None = None) -> list[PaymentCandidate]:
    """Wait: single payment of the full amount on the official earliest date."""
    if Method.FULL_PAYMENT.value not in profile.payment_methods_user_will_consider:
        return [PaymentCandidate(method=Method.WAIT, payments=(),
                                 rejection_reason="wait requires the user to accept full_payment")]
    if earliest is None:
        return [PaymentCandidate(method=Method.WAIT, payments=(),
                                 rejection_reason="full amount never safe within horizon")]
    if earliest <= request.request_date:
        return [PaymentCandidate(method=Method.WAIT, payments=(),
                                 rejection_reason="earliest is today; wait is meaningless")]
    payments = [Payment(earliest, request.requested_amount)]
    return [_evaluate(profile, request, baseline_flows, payments, Method.WAIT, (),
                      unresolved=unresolved)]
