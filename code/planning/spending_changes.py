"""Spending-change eligibility, construction, and application (Phase 3).

Official rules implemented:
- changes only target recurring projected expenses that are flexible and in a
  category the user permits adjusting (stop list / reduce list);
- flexibility is exact: fixed -> never; stoppable -> stop only; reducible ->
  reduce only; reducible_or_stoppable -> either (never both for one event);
- reduce_to never goes below minimum_allowed_amount (D9: target = the supplied
  floor — sample-derived, e.g. event_989 -> 665,950; event_1816 -> 23.50);
- at most 3 changes; stop and reduce_to of the same event are forbidden;
- protected categories are never touched; no event is ever invented.

Application: changes modify FUTURE PROJECTED occurrences of the referenced
series only (matched via source_event_ids); historical settled rows, the
current balance, and unrelated events are untouched. Provenance is preserved
via source_event_ids.
"""
from __future__ import annotations

from decimal import Decimal

from ..finance.timeline import CashFlow
from ..schemas import EventDirection, FinancialEvent
from .models import ChangeAction

MAX_CHANGES = 3


def _representative_event_id(events: list[FinancialEvent]) -> str:
    """Most recent occurrence's event id (the series' current representative)."""
    return max(events, key=lambda e: e.event_date).event_id


def eligible_actions(pattern, source_events: list[FinancialEvent],
                     profile) -> list[ChangeAction]:
    """Deterministic maximal actions for one projected recurring debit pattern.

    D9: reduce_to targets exactly the supplied minimum_allowed_amount.
    """
    if pattern.direction.value != "debit":
        return []
    category = pattern.category
    if category in profile.expense_categories_to_protect:
        return []  # protected categories are never modified
    flex = pattern.flexibility
    actions: list[ChangeAction] = []
    event_id = _representative_event_id(source_events)
    floors = [e.minimum_allowed_amount for e in source_events
              if e.minimum_allowed_amount is not None]
    min_allowed = max(floors) if floors else Decimal("0")
    pattern_key = (category, "debit")

    can_stop = (flex in ("stoppable", "reducible_or_stoppable")
                and category in profile.expense_categories_user_is_willing_to_stop)
    can_reduce = (flex in ("reducible", "reducible_or_stoppable")
                  and category in profile.expense_categories_user_is_willing_to_reduce)

    if can_stop:
        actions.append(ChangeAction(
            action="stop", event_id=event_id, new_amount=None, category=category,
            pattern_key=pattern_key, monthly_gain=pattern.amount))
    if can_reduce and pattern.amount > min_allowed:
        actions.append(ChangeAction(
            action="reduce_to", event_id=event_id, new_amount=min_allowed,
            category=category, pattern_key=pattern_key,
            monthly_gain=pattern.amount - min_allowed))
    return actions


def enumerate_actions(projected_patterns: list, source_events_by_pattern: dict,
                      profile) -> list[ChangeAction]:
    """All deterministic maximal actions over projected fixed-commitment debits."""
    actions: list[ChangeAction] = []
    for pattern in projected_patterns:
        source_events = source_events_by_pattern.get(id(pattern), [])
        actions.extend(eligible_actions(pattern, source_events, profile))
    actions.sort(key=lambda a: (a.category, a.action, a.event_id))
    return actions


def _pattern_key_of_flow(f: CashFlow) -> tuple | None:
    if f.basis == "recurring_projection":
        return (f.category, f.direction_value)
    return None


def apply_changes_to_flows(flows: list[CashFlow],
                           changes: tuple[ChangeAction, ...]) -> list[CashFlow]:
    """Apply stop/reduce_to actions to projected recurring flows only.

    stop      -> projected occurrences of the series are removed
    reduce_to -> occurrence amounts are replaced with the new amount
    Historical flows, provisions, hypothetical payments, and evidence income
    are never touched.
    """
    stop_keys = {(c.category, "debit") for c in changes if c.action == "stop"}
    reduce_by_key = {(c.category, "debit"): c.new_amount for c in changes
                     if c.action == "reduce_to"}
    out: list[CashFlow] = []
    for f in flows:
        key = _pattern_key_of_flow(f)
        if key is not None and key in stop_keys:
            continue
        if key is not None and key in reduce_by_key:
            new_amount = reduce_by_key[key]
            out.append(CashFlow(
                amount_home=-new_amount if f.direction_value == "debit" else f.amount_home,
                effective_date=f.effective_date, category=f.category,
                direction_value=f.direction_value, basis=f.basis,
                source_event_ids=f.source_event_ids, essential=f.essential,
                flexibility=f.flexibility, certainty=f.certainty,
                event_type=f.event_type))
            continue
        out.append(f)
    return out


def validate_change_set(changes: tuple[ChangeAction, ...]) -> str | None:
    """Structural validation; returns a rejection reason or None."""
    if len(changes) > MAX_CHANGES:
        return f"too many spending changes ({len(changes)} > {MAX_CHANGES})"
    seen = set()
    touched: dict[str, set[str]] = {}
    for c in changes:
        sig = (c.action, c.event_id, str(c.new_amount))
        if sig in seen:
            return "duplicate identical spending change"
        seen.add(sig)
        touched.setdefault(c.event_id, set()).add(c.action)
    for event_id, actions in touched.items():
        if len(actions) > 1:
            return f"event {event_id} receives both stop and reduce_to"
    return None


def compatible(actions: tuple[ChangeAction, ...]) -> bool:
    """A change-set is compatible when no event receives conflicting actions."""
    touched: dict[str, set[str]] = {}
    for c in actions:
        touched.setdefault(c.event_id, set()).add(c.action)
    return all(len(v) == 1 for v in touched.values())


def bounded_change_sets(actions: list[ChangeAction], level: int) -> list[tuple[ChangeAction, ...]]:
    """Deterministic bounded change-sets: level 1 = singles, 2 = pairs, 3 = triples.

    Combinatorics are bounded by the small eligible-action count; sets are
    ordered deterministically (sorted by action signature).
    """
    if level < 1 or level > MAX_CHANGES or not actions:
        return []
    ordered = sorted(actions, key=lambda a: (a.category, a.action, a.event_id))
    sets: list[tuple[ChangeAction, ...]] = []

    def combos(prefix: tuple[ChangeAction, ...], pool: list[ChangeAction], depth: int) -> None:
        if depth == 0:
            if prefix and compatible(prefix):
                sets.append(prefix)
            return
        for i, action in enumerate(pool):
            combos(prefix + (action,), pool[i + 1:], depth - 1)

    combos((), ordered, level)
    deduped: dict[tuple, tuple[ChangeAction, ...]] = {}
    for s in sets:
        key = tuple(sorted((c.action, c.event_id, str(c.new_amount)) for c in s))
        deduped.setdefault(key, s)
    return sorted(deduped.values(),
                  key=lambda s: (len(s), tuple(sorted((c.category, c.action) for c in s))))
