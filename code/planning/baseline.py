"""Baseline financial fields: amount_safe_to_pay and earliest_date_for_full_payment.

Both are computed ONCE per request from the evidence-aware baseline (no
optional spending changes, no payment preferences) and never altered by any
candidate (directive Part 6).

ASP algorithm (exact derivation, no search):
  Paying p on request_date shifts EVERY end-of-day balance in the horizon
  down by exactly p (EOD netting, D6 rev. 2). Therefore with baseline
  minimum EOD balance M (computed without any payment):

      safe(p)  <=>  M - p >= minimum_balance_to_keep
      ASP      =  clamp(M - minimum_balance_to_keep, 0, requested_amount)

  floored to the planning quantum (D27) and verified by one simulator run.
  If the baseline is UNSAFE (even p=0 violates the floor) or UNRESOLVED
  (material unknown amounts could lower M), no positive amount is provably
  safe: ASP = 0 with an uncertainty flag (directive Part 4) — never invented.

Earliest algorithm (exact derivation + verification):
  Paying the full requested amount on day d shifts every EOD balance from d
  onward down by requested_amount. With prefix/suffix minima of the baseline
  EOD path:

      safe(d)  <=>  prefix_min[d-1] >= floor  and  suffix_min[d] - requested >= floor

  earliest = the first such d in [request_date, horizon_end] (D22 semantics).
  If no date qualifies, or material unresolved evidence affects the horizon,
  earliest = None (official: leave empty when the full amount is never safe).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from ..finance.simulator import Payment, SafetyState, simulate
from ..finance.timeline import CashFlow, horizon_end
from ..schemas import FinancialProfile
from .models import PLANNING_QUANTUM, BaselineMetrics


def _floor_quantum(value: Decimal) -> Decimal:
    """Floor to the planning quantum (D27: never round up — safety first)."""
    if value >= 0:
        return (value / PLANNING_QUANTUM).to_integral_value(
            rounding="ROUND_FLOOR") * PLANNING_QUANTUM
    return Decimal("0")


def _eod_path(profile: FinancialProfile, request_date: date,
              flows: list[CashFlow], end: date) -> list[Decimal]:
    """End-of-day balance path over the horizon (baseline, no payment)."""
    by_day: dict[date, Decimal] = {}
    for f in flows:
        by_day[f.effective_date] = by_day.get(f.effective_date, Decimal("0")) + f.amount_home
    path = []
    balance = profile.current_available_balance
    day = request_date
    while day <= end:
        balance += by_day.get(day, Decimal("0"))
        path.append(balance)
        day += timedelta(days=1)
    return path


def compute_baseline(profile: FinancialProfile, request_date: date,
                     flows: list[CashFlow], requested_amount: Decimal,
                     unresolved_material: bool,
                     uncertainty_notes: tuple[str, ...] = ()) -> BaselineMetrics:
    end = horizon_end(request_date)
    path = _eod_path(profile, request_date, flows, end)
    baseline_min = min(path)
    floor = profile.minimum_balance_to_keep

    notes = list(uncertainty_notes)
    if unresolved_material:
        # material unknown amounts could lower the true minimum: no positive
        # amount is provably safe -> conservative ASP fallback (Part 4)
        asp = Decimal("0")
        asp_uncertain = True
        notes = list(notes) + ["ASP uncertainty-constrained: unresolved material "
                               "evidence in horizon (conservative fallback ASP=0)"]
    else:
        asp = _floor_quantum(min(baseline_min - floor, requested_amount))
        asp = max(Decimal("0"), min(asp, requested_amount))
        asp_uncertain = False
        # verification: the derived ASP must be safe in the simulator
        state = simulate(profile, request_date, flows,
                         hypothetical_payments=[Payment(request_date, asp)],
                         include_trace=False).state
        if state is not SafetyState.SAFE:
            asp = Decimal("0")
            asp_uncertain = True
            notes = list(notes) + ["ASP verification failed; conservative fallback ASP=0"]

    # earliest: prefix/suffix minima over the baseline EOD path
    earliest = None
    earliest_uncertain = unresolved_material
    if not unresolved_material:
        n = len(path)
        prefix_min = [Decimal("0")] * n
        running = Decimal("Infinity")
        for i, v in enumerate(path):
            running = min(running, v)
            prefix_min[i] = running
        suffix_min = [Decimal("0")] * n
        running = Decimal("Infinity")
        for i in range(n - 1, -1, -1):
            running = min(running, path[i])
            suffix_min[i] = running
        for offset in range(n):
            d = request_date + timedelta(days=offset)
            prefix_ok = prefix_min[offset - 1] >= floor if offset > 0 else True
            if prefix_ok and suffix_min[offset] - requested_amount >= floor:
                earliest = d
                break

    state = (SafetyState.UNRESOLVED if unresolved_material else
             (SafetyState.SAFE if baseline_min >= floor else SafetyState.UNSAFE))
    return BaselineMetrics(
        request_id="",
        amount_safe_to_pay=asp,
        earliest_date_for_full_payment=earliest,
        baseline_state=state,
        baseline_minimum=baseline_min,
        minimum_balance_required=floor,
        asp_uncertain=asp_uncertain,
        earliest_uncertain=earliest_uncertain or earliest is None,
        uncertainty_notes=tuple(notes),
    )
