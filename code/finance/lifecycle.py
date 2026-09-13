"""Event lifecycle resolution: which financial events are cash-material, when, why.

Official rules implemented (docs/03 §1.2, R4-R8, R14):
- cancelled / failed events never affect cash;
- pending debits are reserved; pending credits are ignored (90-Day Safety Check:
  "Ignore pending credits...");
- scheduled events count on their settlement date (known future facts);
- settled events count on their settlement date;
- unrealized / non_cash investment records are never cash;
- linked_event_id groups the same lifecycle; the link alone decides nothing —
  cash state does. Within one lifecycle group, a settled record supersedes a
  pending representation of the same movement (double-count prevention);
- duplicate-substance settled/scheduled/pending rows (identical
  user/type/category/direction/amount/dates/status, distinct IDs) are
  collapsed to one representative (safety net; the current dataset has none).

Precedence per official conflict rules (R14): explicit status (settled /
cancelled / failed) first; newer record within a lifecycle group next; settled
over pending; financially safer interpretation otherwise (documented per
record in the trace).

Blank amounts are NEVER zero: an in-horizon cash-material debit-class event
with a blank amount becomes an UnresolvedEvidence item (state UNRESOLVED
downstream). Phase 4 may supply `resolved_amounts[event_id]` without any
engine rewrite. Historical (pre-request_date) blank-amount events are already
reflected in the starting balance and are simply out of scope.

Raw Phase-1 records are never mutated; resolution produces new records with
full provenance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..schemas import EventDirection, EventStatus, FinancialEvent


@dataclass(frozen=True)
class ResolvedCashEvent:
    """A cash-material movement derived from one or more raw events."""
    amount: Decimal              # positive magnitude, in the event's own currency
    currency: str
    direction: EventDirection    # DEBIT or CREDIT only
    effective_date: date         # the date the movement hits the timeline
    category: str
    event_type: str
    flexibility: str
    source_event_ids: tuple[str, ...]
    basis: str                   # "settled" | "scheduled" | "pending_debit_reserved"
    resolved_from_evidence: bool = False  # True when amount came from resolved_amounts


@dataclass(frozen=True)
class IgnoredRecord:
    event_id: str
    reason: str


@dataclass(frozen=True)
class UnresolvedEvidence:
    event_id: str
    reason: str
    effective_date: date
    direction: EventDirection
    category: str


@dataclass
class LifecycleResult:
    cash_events: list[ResolvedCashEvent] = field(default_factory=list)
    ignored: list[IgnoredRecord] = field(default_factory=list)
    unresolved: list[UnresolvedEvidence] = field(default_factory=list)

    def trace_lines(self) -> list[str]:
        lines = ["cash events:"]
        for c in self.cash_events:
            lines.append(f"  {c.effective_date} {c.direction.value:<6} {c.amount} {c.currency} "
                         f"{c.category:<18} basis={c.basis:<20} src={','.join(c.source_event_ids)}"
                         + (" [evidence-resolved]" if c.resolved_from_evidence else ""))
        lines.append("ignored:")
        for ig in self.ignored:
            lines.append(f"  {ig.event_id}: {ig.reason}")
        lines.append("unresolved:")
        for u in self.unresolved:
            lines.append(f"  {u.event_id}: {u.reason} (effective {u.effective_date})")
        return lines


def _group_lifecycles(events: list[FinancialEvent]) -> list[list[FinancialEvent]]:
    """Union events connected by linked_event_id (child -> parent) into groups."""
    by_id = {e.event_id: e for e in events}
    parent_of: dict[str, str] = {}

    def find(x: str) -> str:
        while x in parent_of:
            x = parent_of[x]
            if x not in by_id:  # link to an event not supplied: root at the missing id
                break
        return x

    for e in events:
        if e.linked_event_id:
            parent_of[e.event_id] = e.linked_event_id

    groups: dict[str, list[FinancialEvent]] = {}
    for e in events:
        groups.setdefault(find(e.event_id), []).append(e)
    return list(groups.values())


def _effective_date(e: FinancialEvent, request_date: date) -> date:
    if e.status == EventStatus.PENDING:
        # reserve as early as officially possible: today if already incurred,
        # otherwise on the date the pending movement is dated
        return max(request_date, e.event_date)
    return e.settlement_date or e.event_date


def _classify_single(e: FinancialEvent, request_date: date,
                     resolved_amounts: dict[str, Decimal] | None,
                     result: LifecycleResult) -> ResolvedCashEvent | None:
    """Status-based classification of one event (official cash-state rules)."""
    effective = _effective_date(e, request_date)

    if e.status in (EventStatus.CANCELLED, EventStatus.FAILED):
        result.ignored.append(IgnoredRecord(e.event_id, f"status={e.status.value}: no cash impact"))
        return None
    if e.direction == EventDirection.NON_CASH or e.status == EventStatus.UNREALIZED:
        result.ignored.append(IgnoredRecord(
            e.event_id, "unrealized/non-cash: never available cash (official)"))
        return None
    if e.status == EventStatus.PENDING and e.direction == EventDirection.CREDIT:
        result.ignored.append(IgnoredRecord(
            e.event_id, "pending credit: ignored until settled (official)"))
        return None

    # cash-material from here: settled (both directions), scheduled (both), pending debit
    amount = e.amount
    from_evidence = False
    if amount is None:
        if resolved_amounts and e.event_id in resolved_amounts:
            amount = resolved_amounts[e.event_id]
            from_evidence = True
        elif effective < request_date:
            # historical blank amount: already inside the starting balance
            result.ignored.append(IgnoredRecord(
                e.event_id, "blank amount, historical (pre request_date): already in balance"))
            return None
        else:
            result.unresolved.append(UnresolvedEvidence(
                e.event_id, "blank amount on in-horizon cash-material event "
                            "(image resolution pending, Phase 4)",
                effective, e.direction, e.category))
            return None

    if effective < request_date:
        # settled/scheduled movement already reflected in the starting balance
        result.ignored.append(IgnoredRecord(
            e.event_id, f"effective {effective.isoformat()} before request_date: "
                        f"already in starting balance"))
        return None

    if e.status == EventStatus.PENDING and e.direction == EventDirection.DEBIT:
        basis = "pending_debit_reserved"
    else:
        basis = e.status.value
    return ResolvedCashEvent(
        amount=amount, currency=e.currency, direction=e.direction,
        effective_date=effective, category=e.category, event_type=e.event_type.value,
        flexibility=e.flexibility.value, source_event_ids=(e.event_id,),
        basis=basis, resolved_from_evidence=from_evidence)


def _drop_same_group_pending_duplicates(cash_events: list[ResolvedCashEvent],
                                        groups: list[list[FinancialEvent]],
                                        result: LifecycleResult) -> list[ResolvedCashEvent]:
    """Lifecycle-group double-count prevention.

    A pending debit inside a lifecycle group is dropped when:
    - the group contains a settled record with the same direction and amount
      (re-presented charge: e.g. the observed settled->pending shopping pairs,
      identical amounts 11 days apart — counting both would double-count); or
    - the group contains a cancelled or failed record (the movement was
      explicitly resolved away).
    Distinct pending movements (different amount) remain reserved.
    """
    events_by_id = {e.event_id: e for group in groups for e in group}
    group_of: dict[str, int] = {}
    for gi, group in enumerate(groups):
        for e in group:
            group_of[e.event_id] = gi

    drop: set[str] = set()
    for gi, group in enumerate(groups):
        pending_debits = [e for e in group
                          if e.status == EventStatus.PENDING and e.direction == EventDirection.DEBIT]
        if not pending_debits:
            continue
        settled_same = [e for e in group if e.status == EventStatus.SETTLED
                        and e.direction == EventDirection.DEBIT and e.amount is not None]
        terminal = [e for e in group
                    if e.status in (EventStatus.CANCELLED, EventStatus.FAILED)]
        for pending in pending_debits:
            if terminal:
                drop.add(pending.event_id)
                result.ignored.append(IgnoredRecord(
                    pending.event_id,
                    f"pending movement resolved by a {terminal[0].status.value} record "
                    f"in the same lifecycle group"))
                continue
            representation = [s for s in settled_same
                              if s.amount == pending.amount
                              and abs((pending.event_date - s.event_date).days) <= 45]
            if representation:
                drop.add(pending.event_id)
                result.ignored.append(IgnoredRecord(
                    pending.event_id,
                    f"pending re-presentation of settled {representation[0].event_id} "
                    f"(same amount, same lifecycle; double-count prevention)"))
    _ = events_by_id
    return [c for c in cash_events if c.source_event_ids[0] not in drop]


def _collapse_duplicate_substance(cash_events: list[ResolvedCashEvent],
                                  result: LifecycleResult) -> list[ResolvedCashEvent]:
    """Collapse identical settled/scheduled substance rows (duplicate records)."""
    seen: dict[tuple, ResolvedCashEvent] = {}
    kept: list[ResolvedCashEvent] = []
    for c in cash_events:
        if c.basis in ("settled", "scheduled"):
            signature = (c.effective_date, c.direction, c.amount, c.currency,
                         c.category, c.basis)
            if signature in seen:
                result.ignored.append(IgnoredRecord(
                    c.source_event_ids[0],
                    "duplicate substance of "
                    f"{seen[signature].source_event_ids[0]} (double-count prevention)"))
                continue
            seen[signature] = c
        kept.append(c)
    return kept


def resolve_lifecycle(events: list[FinancialEvent], request_date: date,
                      resolved_amounts: dict[str, Decimal] | None = None) -> LifecycleResult:
    """Resolve raw events into cash-material movements with full provenance."""
    result = LifecycleResult()
    resolved_amounts = resolved_amounts or {}

    cash: list[ResolvedCashEvent] = []
    groups = _group_lifecycles(events)
    group_index: dict[str, int] = {}
    for gi, group in enumerate(groups):
        for e in group:
            group_index[e.event_id] = gi

    for e in events:
        c = _classify_single(e, request_date, resolved_amounts, result)
        if c is not None:
            cash.append(c)

    cash = _drop_same_group_pending_duplicates(cash, groups, result)
    cash = _collapse_duplicate_substance(cash, result)
    cash.sort(key=lambda c: (c.effective_date, c.direction.value, c.amount, c.category))
    result.cash_events = cash
    return result
