"""Typed immutable planning models (Phase 3).

Typed values throughout; official output strings are produced only at
serialization time by the decision layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from ..finance.simulator import SafetyState
from ..output_validator import PlanEntry, SpendingChange as ContractSpendingChange

PLANNING_QUANTUM = Decimal("0.01")  # D27: centralized planning money quantum


class Method(Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class Affordability(Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


@dataclass(frozen=True)
class ChangeAction:
    """A planned spending change applied to projected recurring flows."""
    action: str                 # "stop" | "reduce_to"
    event_id: str               # representative source event id of the series
    new_amount: Decimal | None  # reduce_to target (>= minimum_allowed_amount)
    category: str
    series_ids: frozenset       # source event ids identifying the EXACT series
    monthly_gain: Decimal       # per-occurrence reduction this action achieves


@dataclass(frozen=True)
class PaymentCandidate:
    method: Method
    payments: tuple[PlanEntry, ...]
    changes: tuple[ContractSpendingChange, ...] = ()
    total_paid: Decimal = Decimal("0")
    first_payment_date: date | None = None
    last_payment_date: date | None = None
    completes_by_deadline: bool = False
    payment_option_id: str | None = None
    sim_state: SafetyState | None = None
    sim_minimum: Decimal | None = None
    rejection_reason: str | None = None
    diagnostics: tuple[str, ...] = ()

    @property
    def uses_spending_changes(self) -> bool:
        return len(self.changes) > 0

    @property
    def payment_count(self) -> int:
        return len(self.payments)


@dataclass(frozen=True)
class BaselineMetrics:
    """Baseline financial fields — computed once, never altered by candidates."""
    request_id: str
    amount_safe_to_pay: Decimal
    earliest_date_for_full_payment: date | None
    baseline_state: SafetyState
    baseline_minimum: Decimal           # min EOD balance over horizon without payment
    minimum_balance_required: Decimal
    asp_uncertain: bool                 # True when unresolved evidence constrained ASP
    earliest_uncertain: bool
    uncertainty_notes: tuple[str, ...] = ()


@dataclass
class Decision:
    """Internal final decision object (Phase 3 output; no output.csv yet)."""
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: Affordability
    recommended_payment_method: Method
    payment_plan: tuple[PlanEntry, ...] | None   # None == "none"
    earliest_date_for_full_payment: date | None
    spending_changes: tuple[ContractSpendingChange, ...]
    selected_candidate: PaymentCandidate | None
    baseline: BaselineMetrics
    reason_codes: tuple[str, ...] = ()
    explanation_facts: dict = field(default_factory=dict)
