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
    # Phase 2.1 (sample evidence: requests 02/03/04/08/12/17/22): only monthly
    # commitments are projected. Sub-monthly purchase series (groceries 7/10d,
    # dining 14/21d, transport 7/21d) are HISTORY, not forecast commitments —
    # projecting them over-reserves and contradicts the official solved plans.
    project_non_monthly: bool = False


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


def _detect_series(es: list[FinancialEvent], params: RecurrenceParams
                   ) -> RecurringPattern | None:
    """Attempt cadence detection on one ordered event series."""
    if len(es) < params.min_observations:
        return None
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
        return None

    last_occurrence = es[-1].event_date
    if is_monthly:
        # anchor to the DOMINANT day-of-month, not the literal last event: a
        # one-off adjustment (e.g. salary spike 5 days after payday) must not
        # hijack the projection anchor (Phase 2.1, request_03 evidence)
        dom_counts: dict[int, int] = {}
        for e in es:
            dom_counts[e.event_date.day] = dom_counts.get(e.event_date.day, 0) + 1
        anchor_dom = max(dom_counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        dominant_events = [e for e in es if _dom_distance(e.event_date.day, anchor_dom) <= 2]
        if dominant_events:
            last_occurrence = max(e.event_date for e in dominant_events)

    return RecurringPattern(
        category=es[0].category, direction=es[0].direction, currency=es[0].currency,
        cadence_days=cadence, is_monthly=is_monthly,
        amount=_conservative_amount([e.amount for e in es], es[0].direction,
                                    params.recent_window),
        flexibility=_dominant_flexibility(es),
        source_event_ids=tuple(e.event_id for e in es),
        last_occurrence=last_occurrence,
        classification_reason=reason)


def _dom_distance(a: int, b: int) -> int:
    """Circular day-of-month distance on 1..31 (so 30/31 sit near 1/2)."""
    d = abs(a - b)
    return min(d, 31 - d + 1 if a <= 31 and b <= 31 else d)


def _cluster_by_day_of_month(es: list[FinancialEvent], tol: int = 2
                             ) -> list[list[FinancialEvent]]:
    """Split a series into day-of-month clusters (interleaved paydays etc.).

    E.g. a twice-monthly salary paid on the 15th and 20th forms two clusters;
    the combined series has irregular 5/25-day gaps and defeats gap detection,
    but each cluster alone is cleanly monthly.
    """
    clusters: list[list[FinancialEvent]] = []
    for e in sorted(es, key=lambda e: e.event_date):
        dom = e.event_date.day
        for cluster in clusters:
            center = cluster[len(cluster) // 2].event_date.day
            if _dom_distance(dom, center) <= tol:
                cluster.append(e)
                break
        else:
            clusters.append([e])
    return clusters


def detect_recurring_patterns(events: list[FinancialEvent], *,
                              params: RecurrenceParams = DEFAULT_PARAMS
                              ) -> list[RecurringPattern]:
    """Detect periodic series from settled history. No history, no pattern.

    Two-stage: whole-series detection first; if the combined series is not
    periodic, retry on day-of-month clusters (interleaved multi-payday income
    and similar sub-series). Category names are never evidence.
    """
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
        whole = _detect_series(es, params)
        if whole is not None:
            patterns.append(whole)
            continue
        if len(es) < 2 * params.min_observations:
            continue  # too little history for meaningful sub-series
        for cluster in _cluster_by_day_of_month(es):
            sub = _detect_series(cluster, params)
            if sub is not None:
                patterns.append(sub)
    patterns.sort(key=lambda p: (p.category, p.direction.value, p.amount))
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
        if not params.project_non_monthly and not pattern.is_monthly:
            diagnostics.append(
                f"{pattern.category}/{pattern.direction.value} fixed-gap series detected "
                f"but not projected (monthly-commitments-only policy, Phase 2.1)")
            continue
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


@dataclass(frozen=True)
class ProvisionParams:
    min_events_90d: int = 6          # sustained behavior, not a blip
    min_windows_active: int = 3      # spend present in each of the last 3 windows
    window_days: int = 30


DEFAULT_PROVISION_PARAMS = ProvisionParams()


def essential_provisions(events: list[FinancialEvent], protected_categories: set[str],
                         request_date: date, patterns: list[RecurringPattern],
                         params: RecurrenceParams = DEFAULT_PARAMS,
                         provision_params: ProvisionParams = DEFAULT_PROVISION_PARAMS
                         ) -> list[ResolvedCashEvent]:
    """Conservative provision for irregular essential spending (official AGENTS.md 6.3:
    "Forecast essential variable spending conservatively").

    Fires ONLY when a protected (essential) category shows sustained debit
    history — >= min_events_90d settled events in the trailing 90 days, spend
    present in each of the last 3 windows of `window_days` days — yet NO
    recurring pattern was detected. Empirical dataset fact: after day-of-month
    clustering this never fires on the official data (every essential series is
    periodic), so it is a pure safety net for unseen eval shapes.

    Provision = the trailing-window total, projected at request_date + window
    and + 2*window (the trailing window itself is already inside the starting
    balance — projecting only future windows avoids double-counting).
    """
    pattern_keys = {(p.category, p.direction.value) for p in patterns}
    by_category: dict[str, list[FinancialEvent]] = {}
    for e in events:
        if (e.direction == EventDirection.DEBIT and e.status == EventStatus.SETTLED
                and e.amount is not None and e.category in protected_categories
                and request_date - timedelta(days=90) <= e.event_date <= request_date):
            by_category.setdefault(e.category, []).append(e)

    provisions: list[ResolvedCashEvent] = []
    for category, evs in sorted(by_category.items()):
        if (category, "debit") in pattern_keys or len(evs) < provision_params.min_events_90d:
            continue
        active_windows = 0
        trailing_total = Decimal("0")
        for w in range(3):
            window_end = request_date - timedelta(days=provision_params.window_days * w)
            window_start = window_end - timedelta(days=provision_params.window_days)
            in_window = [e for e in evs if window_start < e.event_date <= window_end]
            if in_window:
                active_windows += 1
                if w == 0:
                    trailing_total = sum((e.amount for e in in_window), Decimal("0"))
        if active_windows < provision_params.min_windows_active or trailing_total <= 0:
            continue
        sources = tuple(sorted(e.event_id for e in evs))
        for k in (1, 2):
            provisions.append(ResolvedCashEvent(
                amount=trailing_total, currency=evs[0].currency,
                direction=EventDirection.DEBIT,
                effective_date=request_date + timedelta(days=provision_params.window_days * k),
                category=category, event_type="essential_provision",
                flexibility="fixed", source_event_ids=sources,
                basis="essential_provision"))
    return provisions
