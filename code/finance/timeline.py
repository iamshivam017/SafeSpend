"""Cash-timeline normalization: raw lifecycle output -> home-currency CashFlow list.

CashFlow carries full provenance (source events, basis, certainty state,
essential/protected metadata, recurrence provenance). Raw records are never
mutated or destroyed.

The 90-day horizon is [request_date, request_date + 90 days] INCLUSIVE on both
ends (official wording: "Forecast the user's balance for the next 90 days";
day 0 is the request date itself, whose movements must be affordable now).
Events effective after day 90 are outside the forecast and are not applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from ..indexes import Indexes
from ..schemas import FinancialProfile
from .currency import CurrencyConverter
from .lifecycle import LifecycleResult, ResolvedCashEvent
from .recurrence import RecurringPattern, project_occurrences

HORIZON_DAYS = 90


def horizon_end(request_date: date) -> date:
    """Final day of the official 90-day forecast window (inclusive)."""
    return request_date + timedelta(days=HORIZON_DAYS)


@dataclass(frozen=True)
class CashFlow:
    amount_home: Decimal          # signed: negative = debit/outflow, positive = credit
    effective_date: date
    category: str
    direction_value: str          # "debit" | "credit"
    basis: str                    # settled | scheduled | pending_debit_reserved | recurring_projection
    source_event_ids: tuple[str, ...]
    essential: bool               # category is in the user's protected list
    flexibility: str
    certainty: str                # "actual" | "projected"
    event_type: str


@dataclass
class TimelineResult:
    flows: list[CashFlow]
    projected_diagnostics: list[str]

    def trace_lines(self, limit: int | None = None) -> list[str]:
        lines = []
        shown = self.flows if limit is None else self.flows[:limit]
        for f in shown:
            lines.append(f"  {f.effective_date} {f.amount_home:>16} {f.basis:<24} "
                         f"{f.category:<18} certainty={f.certainty:<9} "
                         f"src={','.join(f.source_event_ids[:3])}"
                         + ("..." if len(f.source_event_ids) > 3 else ""))
        if limit is not None and len(self.flows) > limit:
            lines.append(f"  ... {len(self.flows) - limit} more")
        return lines


def _essential(profile: FinancialProfile, category: str) -> bool:
    return category in profile.expense_categories_to_protect


def build_cash_timeline(profile: FinancialProfile, request_date: date,
                        lifecycle: LifecycleResult, patterns: list[RecurringPattern],
                        indexes: Indexes, evidence=None) -> TimelineResult:
    """Normalize resolved events + recurrence projections into home-currency flows.

    Raises MissingRateError (a DataError) when an in-horizon foreign-currency
    event has no official same-date rate — never guesses.
    """
    converter = CurrencyConverter(indexes)
    end = horizon_end(request_date)
    flows: list[CashFlow] = []

    def signed(direction_value: str, amount: Decimal) -> Decimal:
        return -amount if direction_value == "debit" else amount

    for c in lifecycle.cash_events:
        if c.effective_date > end:
            continue  # outside the forecast window
        amount_home = converter.convert(c.amount, c.currency, profile.home_currency,
                                        on_date=c.effective_date, context=c.source_event_ids[0])
        flows.append(CashFlow(
            amount_home=signed(c.direction.value, amount_home),
            effective_date=c.effective_date, category=c.category,
            direction_value=c.direction.value, basis=c.basis,
            source_event_ids=c.source_event_ids,
            essential=_essential(profile, c.category),
            flexibility=c.flexibility, certainty="actual", event_type=c.event_type))

    user_events = indexes.events_by_user_id.get(profile.user_id, [])
    if evidence is not None:
        from ..evidence.apply import apply_evidence_to_patterns  # noqa: F401
        patterns = apply_evidence_to_patterns(patterns, evidence)
    projected, diagnostics = project_occurrences(
        patterns, request_date, end, lifecycle.cash_events,
        source_events=user_events,
        protected_categories=set(profile.expense_categories_to_protect))
    from .recurrence import essential_provisions
    projected_fixed_keys = {(c.category, "debit") for c in projected}
    protected = set(profile.expense_categories_to_protect)
    adjustable = (set(profile.expense_categories_user_is_willing_to_stop)
                  | set(profile.expense_categories_user_is_willing_to_reduce))
    from ..finance.recurrence import ProvisionParams
    pp = ProvisionParams()
    if pp.scope == "adjustable_variable_only":
        cat_filter = adjustable - protected
    elif pp.scope == "all":
        cat_filter = set()  # all categories
    else:
        cat_filter = protected
    provisions = essential_provisions(
        user_events, protected, request_date, patterns,
        projected_fixed_keys=projected_fixed_keys,
        provision_params=pp, adjustable_categories=cat_filter)
    for c in provisions:
        amount_home = converter.convert(c.amount, c.currency, profile.home_currency,
                                        on_date=c.effective_date,
                                        context=f"provision:{c.category}")
        flows.append(CashFlow(
            amount_home=signed(c.direction.value, amount_home),
            effective_date=c.effective_date, category=c.category,
            direction_value=c.direction.value, basis=c.basis,
            source_event_ids=c.source_event_ids,
            essential=True, flexibility=c.flexibility, certainty="projected",
            event_type=c.event_type))
    for c in projected:
        amount_home = converter.convert(c.amount, c.currency, profile.home_currency,
                                        on_date=c.effective_date,
                                        context=f"projection:{c.category}")
        flows.append(CashFlow(
            amount_home=signed(c.direction.value, amount_home),
            effective_date=c.effective_date, category=c.category,
            direction_value=c.direction.value, basis=c.basis,
            source_event_ids=c.source_event_ids,
            essential=_essential(profile, c.category),
            flexibility=c.flexibility, certainty="projected",
            event_type=c.event_type))

    if evidence is not None and evidence.income_series:
        from .recurrence import _month_add as month_add
        for srow in evidence.income_series:
            amount_home = converter.convert(
                srow.amount, srow.currency or profile.home_currency,
                profile.home_currency, on_date=min(srow.first_date, end),
                context=f"evidence:{srow.source_id}")
            occurrences = []
            if request_date <= srow.first_date <= end:
                occurrences.append(srow.first_date)
            steps = 1
            while True:
                occ = month_add(srow.anchor_day, srow.first_date, steps)
                if occ > end:
                    break
                if occ > request_date:
                    occurrences.append(occ)
                steps += 1
                if steps > 400:
                    break
            for occ in sorted(set(occurrences)):
                flows.append(CashFlow(
                    amount_home=amount_home, effective_date=occ, category="salary",
                    direction_value="credit", basis="evidence_income",
                    source_event_ids=(srow.source_id,), essential=False,
                    flexibility="fixed", certainty="actual", event_type="income"))

    flows.sort(key=lambda f: (f.effective_date, f.amount_home, f.category))
    return TimelineResult(flows=flows, projected_diagnostics=diagnostics)


def detect_patterns_for_user(user_id: str, indexes: Indexes,
                             params=None) -> list[RecurringPattern]:
    """Convenience wrapper: detect patterns from a user's full settled history."""
    from .recurrence import DEFAULT_PARAMS, detect_recurring_patterns
    events = indexes.events_by_user_id.get(user_id, [])
    return detect_recurring_patterns(events, params=params or DEFAULT_PARAMS)
