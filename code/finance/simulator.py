"""90-day cash-flow simulator with the minimum-balance invariant.

Same-day ordering (D6, resolved): within a day all DEBITS are applied before
CREDITS, debits sorted by magnitude descending (largest first), credits
ascending. The floor is checked after every debit and at end-of-day, so a
same-day credit can never mask an intraday floor violation. This is the
financially safer deterministic interpretation; the official material does
not specify intra-day order.

Horizon: [request_date, request_date + 90] inclusive (docs/finance/timeline).

Safety states (internal, NOT the HackerRank affordability_status):
- SAFE       : floor never violated and no unresolved material evidence
- UNSAFE     : floor violated at some point (temporary recovery does not repair it)
- UNRESOLVED : an in-horizon cash-material debit has a blank amount awaiting
               Phase 4 evidence resolution — no falsely precise claims

Hypothetical payment schedules (Phase 3 input) are injected as debits on their
dates; the simulator only answers "does this schedule preserve the floor?".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..schemas import FinancialProfile
from .lifecycle import UnresolvedEvidence
from .timeline import CashFlow, horizon_end


class SafetyState(Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Payment:
    payment_date: date
    amount: Decimal

    def as_cash_flow(self) -> CashFlow:
        return CashFlow(amount_home=-self.amount, effective_date=self.payment_date,
                        category="_hypothetical_payment", direction_value="debit",
                        basis="hypothetical_payment", source_event_ids=("_hypothetical",),
                        essential=False, flexibility="fixed", certainty="actual",
                        event_type="hypothetical_payment")


@dataclass
class TimelineEntry:
    date: date
    starting_balance: Decimal
    movements: list[tuple[str, Decimal, str]] = field(default_factory=list)  # (label, signed delta, category)
    ending_balance: Decimal | None = None
    minimum_required: Decimal | None = None
    safe_after_step: bool = True


@dataclass
class SimulationResult:
    starting_balance: Decimal
    ending_balance: Decimal
    minimum_projected_balance: Decimal
    minimum_balance_required: Decimal
    state: SafetyState
    first_floor_violation_date: date | None
    timeline: list[TimelineEntry] = field(default_factory=list)
    unresolved_evidence: list[UnresolvedEvidence] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _apply_day(day_start: Decimal, flows: list[CashFlow], floor: Decimal,
               day: date, trace: list[TimelineEntry]) -> tuple[Decimal, date | None, list[str]]:
    """Apply one day's flows in the D6 order; return (end_balance, first_violation, notes)."""
    debits = sorted([f for f in flows if f.amount_home < 0],
                    key=lambda f: (f.amount_home, f.category))  # most negative first
    credits = sorted([f for f in flows if f.amount_home >= 0],
                     key=lambda f: (f.amount_home, f.category))
    balance = day_start
    first_violation: date | None = None
    entry = TimelineEntry(date=day, starting_balance=day_start, minimum_required=floor)
    for f in debits:
        balance += f.amount_home
        entry.movements.append((f.basis, f.amount_home, f.category))
        if balance < floor and first_violation is None:
            first_violation = day
            entry.safe_after_step = False
    for f in credits:
        balance += f.amount_home
        entry.movements.append((f.basis, f.amount_home, f.category))
    if balance < floor and first_violation is None:
        first_violation = day
        entry.safe_after_step = False
    entry.ending_balance = balance
    trace.append(entry)
    return balance, first_violation, []


def simulate(profile: FinancialProfile, request_date: date,
             cash_flows: list[CashFlow], *,
             hypothetical_payments: list[Payment] | None = None,
             unresolved_evidence: list[UnresolvedEvidence] | None = None,
             include_trace: bool = True) -> SimulationResult:
    """Run the [request_date, request_date+90] simulation.

    The starting balance is `profile.current_available_balance` as of
    request_date (engineering interpretation D19: settled events before
    request_date are already inside it and are never re-applied).
    """
    floor = profile.minimum_balance_to_keep
    balance = profile.current_available_balance
    flows_by_day: dict[date, list[CashFlow]] = {}
    for f in cash_flows:
        flows_by_day.setdefault(f.effective_date, []).append(f)
    for p in hypothetical_payments or []:
        flows_by_day.setdefault(p.payment_date, []).append(p.as_cash_flow())

    unresolved_material = [u for u in (unresolved_evidence or [])
                           if u.direction.value == "debit"
                           and request_date <= u.effective_date <= horizon_end(request_date)]

    trace: list[TimelineEntry] = []
    first_violation: date | None = None
    min_balance = balance
    day = request_date
    end = horizon_end(request_date)
    while day <= end:
        balance, violation, _ = _apply_day(balance, flows_by_day.get(day, []), floor,
                                           day, trace if include_trace else [])
        min_balance = min(min_balance, balance)
        if violation is not None and first_violation is None:
            first_violation = violation
        day += timedelta(days=1)

    if unresolved_material:
        state = SafetyState.UNRESOLVED
    elif first_violation is not None:
        state = SafetyState.UNSAFE
    else:
        state = SafetyState.SAFE

    return SimulationResult(
        starting_balance=profile.current_available_balance,
        ending_balance=balance,
        minimum_projected_balance=min_balance,
        minimum_balance_required=floor,
        state=state,
        first_floor_violation_date=first_violation,
        timeline=trace,
        unresolved_evidence=unresolved_material,
        diagnostics=[])
