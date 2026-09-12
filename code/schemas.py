"""Typed domain schemas for all participant-facing datasets plus the output contract.

Dataclasses preserve every official field (no premature information loss).
Monetary fields are Decimal or None (None = officially blank, never 0).
Controlled-value fields use StrEnum; unknown values raise EnumValueError at load
time so structural surprises surface immediately (docs/01 §2, docs/03 §3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

from .errors import EnumValueError
from .parsing import format_date, format_money


class _StrictEnum(StrEnum):
    @classmethod
    def parse(cls, raw: str, *, field_name: str, file: str | None = None,
              row: int | None = None, identifier: str | None = None,
              nullable: bool = False):
        if raw is None or raw.strip() == "":
            if nullable:
                return None
            raise EnumValueError(f"missing required value for {field_name!r}",
                                 file=file, row=row, identifier=identifier)
        text = raw.strip()
        try:
            return cls(text)
        except ValueError:
            allowed = ", ".join(m.value for m in cls)
            raise EnumValueError(f"unknown value {raw!r} for {field_name!r} "
                                 f"(allowed: {allowed})",
                                 file=file, row=row, identifier=identifier) from None


class EventStatus(_StrictEnum):
    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class EventDirection(_StrictEnum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventType(_StrictEnum):
    EXPENSE = "expense"
    SUBSCRIPTION = "subscription"
    INCOME = "income"
    DEBT_PAYMENT = "debt_payment"
    INVESTMENT_PURCHASE = "investment_purchase"
    REFUND = "refund"
    INVESTMENT_VALUATION = "investment_valuation"
    INVESTMENT_SALE = "investment_sale"


class Flexibility(_StrictEnum):
    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


class RequestType(_StrictEnum):
    PURCHASE = "purchase"
    TRAVEL = "travel"
    EDUCATION = "education"
    FAMILY_TRANSFER = "family_transfer"
    DEBT_REPAYMENT = "debt_repayment"
    INVESTMENT = "investment"
    HOUSING = "housing"
    EMERGENCY_EXPENSE = "emergency_expense"
    OTHER = "other"


class AffordabilityStatus(_StrictEnum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class RecommendedPaymentMethod(_StrictEnum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class PaymentMethod(_StrictEnum):
    """Methods used in payment options and profile preference lists."""
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"


@dataclass(frozen=True)
class FinancialProfile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: list[str] = field(default_factory=list)
    expense_categories_to_protect: list[str] = field(default_factory=list)
    expense_categories_user_is_willing_to_reduce: list[str] = field(default_factory=list)
    expense_categories_user_is_willing_to_stop: list[str] = field(default_factory=list)
    payment_methods_user_will_consider: list[PaymentMethod] = field(default_factory=list)
    max_installment_months: int | None = None  # blank = user will not consider installments


@dataclass(frozen=True)
class FinancialEvent:
    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: EventDirection
    amount: Decimal | None  # None = officially blank; MUST NOT become 0 (resolved via images in Phase 4)
    currency: str
    event_date: date
    settlement_date: date | None
    status: EventStatus
    linked_event_id: str | None
    flexibility: Flexibility
    minimum_allowed_amount: Decimal | None


@dataclass(frozen=True)
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: RequestType
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str


@dataclass(frozen=True)
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: PaymentMethod
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: int | None  # blank for full_payment options
    financing_fee: Decimal
    total_payable_amount: Decimal


@dataclass(frozen=True)
class ExchangeRate:
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass(frozen=True)
class Message:
    message_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    sent_at: str  # ISO timestamp kept raw; only ordering/precedence needs it later
    source_type: str
    message_text: str


@dataclass(frozen=True)
class ImageEvidenceReference:
    image_id: str
    user_id: str
    request_id: str | None
    related_event_id: str | None
    image_path: str  # dataset/media/images/<image_id>.png (resolved, may not exist)
    file_exists: bool  # evidence must never be invented when the file is absent (R11)


@dataclass(frozen=True)
class SampleRequest:
    """A solved example row: request fields + the official completed answer columns."""
    request: Request
    amount_safe_to_pay: Decimal
    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    payment_plan: str  # raw official string ("" in malformed rows); parse via output_validator
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str  # raw official string
    decision_explanation: str


@dataclass(frozen=True)
class OutputRow:
    """One prediction row. Serialization order == official required column order."""
    request_id: str
    amount_safe_to_pay: Decimal
    affordability_status: AffordabilityStatus
    recommended_payment_method: RecommendedPaymentMethod
    payment_plan: str  # "none" or validated "YYYY-MM-DD:amount|..." string
    earliest_date_for_full_payment: date | None
    spending_changes_needed: str  # "none" or validated "stop:<id>|reduce_to:<id>:<amt>" string
    decision_explanation: str

    def to_csv_row(self) -> list[str]:
        return [
            self.request_id,
            format_money(self.amount_safe_to_pay),
            self.affordability_status.value,
            self.recommended_payment_method.value,
            self.payment_plan,
            format_date(self.earliest_date_for_full_payment),
            self.spending_changes_needed,
            self.decision_explanation,
        ]


OUTPUT_COLUMNS: tuple[str, ...] = (
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
)
