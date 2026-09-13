"""90-day cash-flow simulator with the minimum-balance invariant.

Same-day semantics (D6, REVISED in Phase 2.1 on sample evidence): the floor is
checked on the END-OF-DAY balance. The original debits-first intraday check was
contradicted by official solved plans that pay on a day a salary arrives
(request_18, request_23: official wait plans land exactly on payday, EOD-safe,
and the official model treats them as safe — an intraday debits-first check
would reject them). Within-day order is therefore only a deterministic TRACE
presentation (debits largest-first, then credits); end-of-day balance is
order-independent. Official wording never specifies intra-day order; the
solved samples are the stronger evidence.

Horizon: [request_date, request_date + 90] inclusive (docs/finance/timeline).

Safety states (internal, NOT the HackerRank affordability_status):
- SAFE       : floor never violated and no unresolved material evidence
- UNSAFE     : floor violated at some point (temporary recovery does not repair
               it). UNSAFE outranks UNRESOLVED: unresolved blank debits can only
               lower the balance further, so a proven violation is certain
               information that must not be masked.
- UNRESOLVED : no floor violation yet, but an in-horizon cash-material debit
               has a blank amount awaiting Phase 4 evidence resolution — no
               falsely precise claims

Hypothetical payment schedules (Phase 3 input) are injected as debits on their
dates; the simulator only answers "does this schedule preserve the floor?".
Payments outside the [request_date, horizon_end] window raise DataError
(Phase 3 must never discover a silently ignored payment).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

from ..errors import DataError
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
                        essential=False, flexibility="fixed", certainty="hypothetical",
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
               day: date, trace: list[TimelineEntry]) -> tuple[Decimal, date | None]:
    """Apply one day's flows; floor checked on the END-OF-DAY balance (D6 rev. 2).

    Movement recording is deterministic (debits largest-first, then credits
    ascending) but does not affect the balance outcome.
    """
    debits = sorted([f for f in flows if f.amount_home < 0],
                    key=lambda f: (f.amount_home, f.category))  # most negative first
    credits = sorted([f for f in flows if f.amount_home >= 0],
                     key=lambda f: (f.amount_home, f.category))
    entry = TimelineEntry(date=day, starting_balance=day_start, minimum_required=floor)
    balance = day_start
    for f in debits:
        balance += f.amount_home
        entry.movements.append((f.basis, f.amount_home, f.category))
    for f in credits:
        balance += f.amount_home
        entry.movements.append((f.basis, f.amount_home, f.category))
    first_violation: date | None = None
    if balance < floor:
        first_violation = day
        entry.safe_after_step = False
    entry.ending_balance = balance
    trace.append(entry)
    return balance, first_violation


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
    end = horizon_end(request_date)
    for p in hypothetical_payments or []:
        if not (request_date <= p.payment_date <= end):
            raise DataError(
                f"hypothetical payment dated {p.payment_date.isoformat()} outside the "
                f"forecast window [{request_date.isoformat()}, {end.isoformat()}] "
                f"(silently ignoring it would fake feasibility)", identifier="_payment")
        flows_by_day.setdefault(p.payment_date, []).append(p.as_cash_flow())

    unresolved_material = [u for u in (unresolved_evidence or [])
                           if u.direction.value == "debit"
                           and request_date <= u.effective_date <= horizon_end(request_date)]

    trace: list[TimelineEntry] = []
    first_violation: date | None = None
    min_balance = balance
    day = request_date
    while day <= end:
        balance, violation = _apply_day(balance, flows_by_day.get(day, []), floor,
                                        day, trace if include_trace else [])
        min_balance = min(min_balance, balance)
        if violation is not None and first_violation is None:
            first_violation = violation
        day += timedelta(days=1)

    # UNSAFE outranks UNRESOLVED: unresolved blank debits can only lower the
    # balance further, so a proven floor violation is certain information (W2).
    if first_violation is not None:
        state = SafetyState.UNSAFE
    elif unresolved_material:
        state = SafetyState.UNRESOLVED
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
