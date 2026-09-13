"""Recurrence detection and projection — deterministic, evidence-based only.

Official rule: "Detect recurring spending/income only when history supports it."
An event series is recurring only when its settled history shows a consistent
cadence; category names are never used as evidence (D18).

Algorithm (parameters are explicit and testable):
1. Group settled, cash-material, non-blank events by
   (user, category, direction, currency).
2. Compute consecutive event-date gaps; classify the series cadence:
     monthly      majority of gaps in 28..31 (projected by day-of-month anchor)
     fixed-gap    majority of gaps equal (±1) to one dominant gap value
                  (covers the observed weekly 7d, 10d, 14d, 21d cadences)
   Pick the dominant classification. A series is periodic when
   (a) at least `min_observations` events and (b) the matching gaps cover at
   least `min_bucket_fraction` of all gaps. Outlier one-off adjustments
   (e.g. a 5-day gap inside a monthly salary series) are tolerated by the
   majority rule.
3. Representative amount (conservative, D18):
   debits  -> max of the last `recent_window` amounts  (over-reserve spending)
   credits -> median of the last `recent_window` amounts (under-count income;
              tolerates one-off small/large adjustments)
4. Staleness (C3 fix): a series only projects while its last historical
   occurrence is recent — within `max_silent_cadences` cadences of
   request_date. A series that went silent longer than that is no longer
   treated as active.
5. Projection: monthly cadences step by day-of-month from the ANCHOR day
   (last occurrence's day; clamping never drifts the anchor, W3 fix). Fixed
   gaps step by +g days. Only occurrences strictly AFTER request_date are
   emitted (a same-day projected credit is never treated as available cash).
   A projected occurrence is DROPPED when an actual cash event with the same
   (category, direction) already lands within `actual_tolerance` days of it —
   actual records outrank forecasts (official conflict rule 3).

Insufficient evidence -> not recurring (never hallucinated).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from ..schemas import EventDirection, EventStatus, FinancialEvent
from .lifecycle import ResolvedCashEvent


@dataclass(frozen=True)
class RecurrenceParams:
    min_observations: int = 3
    min_bucket_fraction: float = 0.6
    recent_window: int = 3
    weekly_band: tuple[int, int] = (6, 8)
    biweekly_band: tuple[int, int] = (13, 15)
    monthly_band: tuple[int, int] = (28, 31)
    actual_tolerance_days: int = 3
    max_silent_cadences: int = 2   # series silent longer than this is inactive (C3)


DEFAULT_PARAMS = RecurrenceParams()


@dataclass(frozen=True)
class RecurringPattern:
    category: str
    direction: EventDirection
    currency: str
    cadence_days: int          # representative gap (30 for monthly)
    is_monthly: bool           # monthly projects by day-of-month, not +30d
    amount: Decimal            # conservative representative amount
    flexibility: str           # dominant flexibility of source events
    source_event_ids: tuple[str, ...]
    last_occurrence: date
    classification_reason: str


def _conservative_amount(amounts: list[Decimal], direction: EventDirection,
                         window: int) -> Decimal:
    recent = amounts[-window:]
    if direction == EventDirection.DEBIT:
        return max(recent)   # conservative: reserve the worst recent spend
    # numeric median of Decimals — exact (a string median would sort
    # lexicographically and misstate mixed-magnitude income, C2)
    return statistics.median(recent)


def _dominant_flexibility(events: list[FinancialEvent]) -> str:
    counts: dict[str, int] = {}
    for e in events:
        counts[e.flexibility.value] = counts.get(e.flexibility.value, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _month_add(anchor_day: int, d: date, steps: int) -> date:
    """`steps` months after d, keeping the ANCHOR day-of-month (clamped per
    month to the month length, never drifting: Jan-31 anchor -> Feb-28 ->
    Mar-31, W3)."""
    total = d.month - 1 + steps
    year = d.year + total // 12
    month = total % 12 + 1
    month_lengths = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                     else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(anchor_day, month_lengths[month - 1]))


def detect_recurring_patterns(events: list[FinancialEvent], *,
                              params: RecurrenceParams = DEFAULT_PARAMS
                              ) -> list[RecurringPattern]:
    """Detect periodic series from settled history. No history, no pattern."""
    series: dict[tuple, list[FinancialEvent]] = {}
    for e in events:
        if e.status != EventStatus.SETTLED or e.amount is None:
            continue
        if e.direction not in (EventDirection.DEBIT, EventDirection.CREDIT):
            continue
        series.setdefault((e.user_id, e.category, e.direction, e.currency), []).append(e)

    patterns: list[RecurringPattern] = []
    for (user_id, category, direction, currency), es in series.items():
        es = sorted(es, key=lambda e: e.event_date)
        if len(es) < params.min_observations:
            continue
        gaps = [(b.event_date - a.event_date).days for a, b in zip(es, es[1:])]

        # monthly band first (calendar-month gaps drift across 28..31)
        monthly_gaps = [g for g in gaps
                        if params.monthly_band[0] <= g <= params.monthly_band[1]]
        cadence = None
        is_monthly = False
        reason = None
        if len(monthly_gaps) / len(gaps) >= params.min_bucket_fraction:
            cadence = int(statistics.median(monthly_gaps))
            is_monthly = True
            reason = f"monthly cadence ({len(monthly_gaps)}/{len(gaps)} gaps in 28-31)"
        else:
            # fixed-gap rule: dominant exact gap value with ±1 consistency
            # (covers weekly 7d, biweekly 14d and the observed 10d/21d cadences)
            gap_counts: dict[int, int] = {}
            for g in gaps:
                gap_counts[g] = gap_counts.get(g, 0) + 1
            dominant = max(gap_counts.items(), key=lambda kv: (kv[1], -kv[0]))
            g0, count = dominant
            consistent = [g for g in gaps if abs(g - g0) <= 1]
            if count >= 2 and len(consistent) / len(gaps) >= params.min_bucket_fraction:
                cadence = int(statistics.median(consistent))
                is_monthly = False
                label = ("weekly" if params.weekly_band[0] <= cadence <= params.weekly_band[1]
                         else "biweekly" if params.biweekly_band[0] <= cadence <= params.biweekly_band[1]
                         else f"fixed-{cadence}d")
                reason = f"{label} cadence ({len(consistent)}/{len(gaps)} gaps ~= {cadence}d)"
        if cadence is None:
            continue

        patterns.append(RecurringPattern(
            category=category, direction=direction, currency=currency,
            cadence_days=cadence, is_monthly=is_monthly,
            amount=_conservative_amount([e.amount for e in es], direction,
                                        params.recent_window),
            flexibility=_dominant_flexibility(es),
            source_event_ids=tuple(e.event_id for e in es),
            last_occurrence=es[-1].event_date,
            classification_reason=reason))
    patterns.sort(key=lambda p: (p.category, p.direction.value))
    return patterns


def project_occurrences(patterns: list[RecurringPattern], request_date: date,
                        horizon_end: date,
                        actual_cash: list[ResolvedCashEvent],
                        params: RecurrenceParams = DEFAULT_PARAMS
                        ) -> tuple[list[ResolvedCashEvent], list[str]]:
    """Project future occurrences of each pattern up to horizon_end.

    A pattern whose last historical occurrence is older than
    `max_silent_cadences` cadences before request_date is inactive and never
    projects (no phantom income/debits from dead series). Only occurrences
    strictly after request_date are emitted. A projection is dropped when an
    actual cash movement of the same category+direction lands within
    `actual_tolerance_days` of it (actual outranks forecast).
    """
    actual_keys: dict[tuple[str, str], list[date]] = {}
    for c in actual_cash:
        actual_keys.setdefault((c.category, c.direction.value), []).append(c.effective_date)

    projected: list[ResolvedCashEvent] = []
    diagnostics: list[str] = []
    for pattern in patterns:
        silence_limit = request_date - timedelta(
            days=params.max_silent_cadences * pattern.cadence_days)
        if pattern.last_occurrence < silence_limit:
            diagnostics.append(
                f"{pattern.category}/{pattern.direction.value} inactive: last occurrence "
                f"{pattern.last_occurrence.isoformat()} is older than "
                f"{params.max_silent_cadences} cadences before {request_date.isoformat()}")
            continue

        occurrences: list[date] = []
        if pattern.is_monthly:
            anchor_day = pattern.last_occurrence.day
            steps = 1
            while True:
                occ = _month_add(anchor_day, pattern.last_occurrence, steps)
                if occ > horizon_end:
                    break
                occurrences.append(occ)
                steps += 1
                if steps > 400:  # safety valve; 90-day horizon can't hit this
                    break
        else:
            occ = pattern.last_occurrence
            while True:
                occ = occ + timedelta(days=pattern.cadence_days)
                if occ > horizon_end:
                    break
                occurrences.append(occ)
                if len(occurrences) > 400:  # safety valve
                    break

        for occ in occurrences:
            if occ <= request_date:
                continue  # a same-day projected credit is never available cash (C3)
            near_actual = any(abs((occ - d).days) <= params.actual_tolerance_days
                              for d in actual_keys.get(
                                  (pattern.category, pattern.direction.value), []))
            if near_actual:
                diagnostics.append(
                    f"{pattern.category}/{pattern.direction.value} occurrence "
                    f"{occ.isoformat()} dropped: actual record within "
                    f"{params.actual_tolerance_days}d")
                continue
            projected.append(ResolvedCashEvent(
                amount=pattern.amount, currency=pattern.currency,
                direction=pattern.direction, effective_date=occ,
                category=pattern.category, event_type="recurring_projection",
                flexibility=pattern.flexibility,
                source_event_ids=pattern.source_event_ids,
                basis="recurring_projection"))
    projected.sort(key=lambda c: (c.effective_date, c.direction.value, c.category))
    return projected, diagnostics
