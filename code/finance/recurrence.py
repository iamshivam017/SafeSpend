"""Recurrence detection and projection — deterministic, evidence-based only.

Official rule: "Detect recurring spending/income only when history supports it."
An event series is recurring only when its settled history shows a consistent
cadence; category names are never used as evidence (D18).

Algorithm (parameters are explicit and testable):
1. Group settled, cash-material, non-blank events by
   (user, category, direction, currency).
2. Compute consecutive event-date gaps; bucket each gap:
     weekly       6..8
     biweekly    13..15
     monthly     28..31
     custom      any fixed gap g where the observation count is sufficient
   Pick the dominant bucket (most observations). A series is periodic when
   (a) at least `min_observations` events and (b) the dominant bucket covers
   at least `min_bucket_fraction` of all gaps. Outlier one-off adjustments
   (e.g. a 5-day gap inside a monthly salary series) are tolerated by the
   majority rule.
3. Representative amount (conservative, D18):
   debits  -> max of the last `recent_window` amounts  (over-reserve spending)
   credits -> median of the last `recent_window` amounts (under-count income;
              tolerates one-off small/large adjustments)
4. Projection: from the last historical occurrence, step by the cadence
   (monthly uses day-of-month clamping; fixed gaps use +g days) until the
   horizon end. A projected occurrence is DROPPED when an actual cash event
   with the same (category, direction) already lands within `actual_tolerance`
   days of it — actual records outrank forecasts (official conflict rule 3).

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


def _bucket(gap: int, p: RecurrenceParams) -> str | None:
    if p.weekly_band[0] <= gap <= p.weekly_band[1]:
        return "weekly"
    if p.biweekly_band[0] <= gap <= p.biweekly_band[1]:
        return "biweekly"
    if p.monthly_band[0] <= gap <= p.monthly_band[1]:
        return "monthly"
    return None


def _conservative_amount(amounts: list[Decimal], direction: EventDirection,
                         window: int) -> Decimal:
    recent = amounts[-window:]
    if direction == EventDirection.DEBIT:
        return max(recent)   # conservative: reserve the worst recent spend
    return Decimal(str(statistics.median([str(a) for a in recent])))


def _dominant_flexibility(events: list[FinancialEvent]) -> str:
    counts: dict[str, int] = {}
    for e in events:
        counts[e.flexibility.value] = counts.get(e.flexibility.value, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def _add_month_clamped(d: date) -> date:
    """Same day-of-month next month, clamped to the month length."""
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


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
        buckets: dict[str, list[int]] = {}
        for g in gaps:
            b = _bucket(g, params)
            if b is not None:
                buckets.setdefault(b, []).append(g)
        if not buckets:
            continue
        bucket_name, bucket_gaps = max(
            buckets.items(), key=lambda kv: (len(kv[1]), -abs(statistics.median(kv[1]) - 30)))
        if len(bucket_gaps) / len(gaps) < params.min_bucket_fraction:
            continue

        if bucket_name == "monthly":
            cadence = int(statistics.median(bucket_gaps))
            is_monthly = True
            reason = f"monthly cadence ({len(bucket_gaps)}/{len(gaps)} gaps in 28-31)"
        else:
            # weekly/biweekly or a fixed custom gap: require near-exact consistency
            med = statistics.median(bucket_gaps)
            consistent = [g for g in gaps if abs(g - med) <= 1]
            if len(consistent) / len(gaps) < params.min_bucket_fraction:
                continue
            cadence = int(med)
            is_monthly = False
            label = {"weekly": "weekly", "biweekly": "biweekly"}.get(
                bucket_name, f"fixed-{cadence}d")
            reason = f"{label} cadence ({len(consistent)}/{len(gaps)} gaps ~= {cadence}d)"

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

    Returns (projected_events, diagnostics). A projection is dropped when an
    actual cash movement of the same category+direction already lands within
    `actual_tolerance_days` of it (actual outranks forecast).
    """
    actual_keys: dict[tuple[str, str], list[date]] = {}
    for c in actual_cash:
        actual_keys.setdefault((c.category, c.direction.value), []).append(c.effective_date)

    projected: list[ResolvedCashEvent] = []
    diagnostics: list[str] = []
    for pattern in patterns:
        occurrences: list[date] = []
        next_date = pattern.last_occurrence
        while True:
            next_date = (_add_month_clamped(next_date) if pattern.is_monthly
                         else next_date + timedelta(days=pattern.cadence_days))
            if next_date > horizon_end:
                break
            occurrences.append(next_date)
            if len(occurrences) > 400:  # safety valve; 90-day horizon can't hit this
                break
        for occ in occurrences:
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
