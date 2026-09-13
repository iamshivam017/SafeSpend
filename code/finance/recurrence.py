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
    # Phase 2.2: sub-monthly patterns are CLASSIFIED, not blanket-suppressed.
    # A non-monthly series is a fixed commitment when its amounts are stable
    # (relative spread <= stability_tolerance over the recent window) or its
    # dominant event_type is `subscription` (a billing obligation); otherwise
    # it is variable spending (essential if the category is protected, else
    # discretionary). Sample evidence (requests 02/03/04/08/12/17/22): variable
    # sub-monthly purchases must not be projected as exact commitments.
    stability_tolerance: str = "0.15"


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


PatternClass = str  # "fixed_commitment" | "variable_essential" | "variable_discretionary"


def _amount_stable(amounts, tolerance):
    """True when the recent amounts are near-constant (commitment-like)."""
    recent = amounts[-5:]
    if len(recent) < 2:
        return True
    median = statistics.median(recent)
    if median == 0:
        return False
    return (max(recent) - min(recent)) <= tolerance * median


def _dominant_type(events):
    counts = {}
    for e in events:
        counts[e.event_type.value] = counts.get(e.event_type.value, 0) + 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


def classify_pattern(pattern, source_events, protected_categories,
                     params=DEFAULT_PARAMS):
    """Classify a detected pattern into exactly one forward treatment.

    - monthly cadence -> fixed_commitment (officially validated across the
      solved plans: monthly rent/utilities/subscriptions/debt/salary streams
      project; no solved sample contradicts monthly projection)
    - non-monthly -> fixed_commitment only when commitment-like (stable amounts
      or subscription billing); otherwise VARIABLE spending:
      variable_essential when the category is protected, else
      variable_discretionary. Category NAME alone is never the classifier —
      protection comes from the user's profile, stability from history.
    """
    if pattern.is_monthly:
        return "fixed_commitment"
    tolerance = Decimal(params.stability_tolerance)
    amounts = [e.amount for e in source_events if e.amount is not None]
    if _dominant_type(source_events) == "subscription" or _amount_stable(amounts, tolerance):
        return "fixed_commitment"
    if pattern.category in protected_categories:
        return "variable_essential"
    return "variable_discretionary"


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


def project_occurrences(patterns, request_date, horizon_end, actual_cash,
                        source_events=None, protected_categories=None,
                        params=DEFAULT_PARAMS):
    """Project future occurrences of FIXED-COMMITMENT patterns to horizon_end.

    Patterns are classified (D10 rev. 3): monthly patterns and commitment-like
    non-monthly patterns (stable amounts / subscription billing) project as
    dated events; variable patterns do NOT project as exact events — protected
    variable categories receive the aggregate essential provision instead (see
    essential_provisions). A pattern whose last historical occurrence is older
    than `max_silent_cadences` cadences before request_date is inactive. Only
    occurrences strictly after request_date are emitted. A projection is
    dropped when an actual cash movement of the same category+direction lands
    within `actual_tolerance_days` of it (actual outranks forecast).
    """
    actual_keys = {}
    for c in actual_cash:
        actual_keys.setdefault((c.category, c.direction.value), []).append(c.effective_date)

    protected = protected_categories or set()
    projected = []
    diagnostics = []
    for pattern in patterns:
        source = [e for e in (source_events or [])
                  if e.event_id in pattern.source_event_ids]
        pclass = classify_pattern(pattern, source, protected, params)
        if pclass != "fixed_commitment":
            diagnostics.append(
                f"{pattern.category}/{pattern.direction.value} classified "
                f"{pclass}: not projected as exact events")
            continue
        silence_limit = request_date - timedelta(
            days=params.max_silent_cadences * pattern.cadence_days)
        if pattern.last_occurrence < silence_limit:
            diagnostics.append(
                f"{pattern.category}/{pattern.direction.value} inactive: last occurrence "
                f"{pattern.last_occurrence.isoformat()} is older than "
                f"{params.max_silent_cadences} cadences before {request_date.isoformat()}")
            continue

        occurrences = []
        if pattern.is_monthly:
            anchor_day = pattern.last_occurrence.day
            steps = 1
            while True:
                occ = _month_add(anchor_day, pattern.last_occurrence, steps)
                if occ > horizon_end:
                    break
                occurrences.append(occ)
                steps += 1
                if steps > 400:  # safety valve; 90-day horizon cannot hit this
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
    # Phase 5 calibration knobs (D30):
    scope: str = "protected"         # "protected" | "all" variable debit streams
    occurrences: int = 1             # reserve placements over the horizon
    statistic: str = "median"        # median | max | trailing (window-total statistic)


DEFAULT_PROVISION_PARAMS = ProvisionParams()


def essential_provisions(events, protected_categories, request_date, patterns,
                         projected_fixed_keys=None,
                         params=None,
                         provision_params=None):
    """Conservative aggregate provision for VARIABLE essential spending
    (official AGENTS.md 6.3: "Forecast essential variable spending
    conservatively").

    Gate (D21 rev. 2): a protected category is provisioned when it has
    sustained debit history (>= min_events_90d settled events in the trailing
    90 days, spend in each of the last 3 windows) and is NOT already projected
    as a fixed commitment. Detection alone never suppresses the provision —
    only an actual fixed projection does (Phase 2.2: a detected-but-unprojected
    sub-monthly pattern must not make essential spending vanish).

    Amount = MEDIAN of the last 3 window totals (robust upper-leaning central
    estimate; not the single largest window, not one historical event).
    Placement = ONE occurrence at request_date + window_days (the trailing
    window itself is already inside the starting balance). Classified as an
    ENGINEERING DECISION (D21); empirically calibrated against the solved
    samples (request_01's official budget admits exactly one aggregate
    provision).
    """
    params = params or DEFAULT_PARAMS
    provision_params = provision_params or DEFAULT_PROVISION_PARAMS
    projected_keys = projected_fixed_keys or set()
    by_category = {}
    for e in events:
        if (e.direction == EventDirection.DEBIT and e.status == EventStatus.SETTLED
                and e.amount is not None
                and request_date - timedelta(days=90) <= e.event_date <= request_date):
            by_category.setdefault(e.category, []).append(e)
    if provision_params.scope == "protected":
        by_category = {c: v for c, v in by_category.items()
                       if c in protected_categories}

    provisions = []
    for category, evs in sorted(by_category.items()):
        if (category, "debit") in projected_keys:
            continue  # fixed projection already covers it (no double count)
        if len(evs) < provision_params.min_events_90d:
            continue
        window_totals = []
        for w in range(3):
            window_end = request_date - timedelta(days=provision_params.window_days * w)
            window_start = window_end - timedelta(days=provision_params.window_days)
            in_window = [e for e in evs if window_start < e.event_date <= window_end]
            window_totals.append(
                sum((e.amount for e in in_window), Decimal("0")) if in_window else None)
        if any(total is None for total in window_totals):
            continue  # spend must be present in all three windows (sustained)
        if provision_params.statistic == "max":
            amount = max(window_totals)
        elif provision_params.statistic == "trailing":
            amount = window_totals[0]
        else:
            amount = statistics.median(window_totals)
        if amount <= 0:
            continue
        sources = tuple(sorted(e.event_id for e in evs))
        for k in range(1, provision_params.occurrences + 1):
            provisions.append(ResolvedCashEvent(
                amount=amount, currency=evs[0].currency,
                direction=EventDirection.DEBIT,
                effective_date=request_date
                + timedelta(days=provision_params.window_days * k),
                category=category, event_type="essential_provision",
                flexibility="fixed", source_event_ids=sources,
                basis="essential_provision"))
    return provisions
