"""Typed evidence claims and deterministic validation.

EvidenceClaim is the ONLY structure the finance engine consumes from
messages/images. Every field is validated; anything invalid or ambiguous is
rejected (recorded as unparsed) — never guessed, never zero-filled.

Message/image content is untrusted DATA: only whitelisted claim types are
recognized, and free-form text (including instruction-like phrases) can never
alter challenge rules or produce behavior.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

from ..errors import DataError
from ..parsing import parse_date, parse_money


class ClaimType(Enum):
    SALARY_CONFIRMED = "salary_confirmed"          # amount (+ optionally first credit date)
    SALARY_CHANGED = "salary_changed"              # amount changed, optional effective date
    SALARY_RESUMED = "salary_resumed"              # regular salary resumes on a date
    INCOME_ENDED = "income_ended"                  # employment/income stream ended
    PAYMENT_DELAYED = "payment_delayed"            # salary/credit date moved
    PAYMENT_CANCELLED = "payment_cancelled"
    PAYMENT_SETTLED = "payment_settled"
    AMOUNT_AMENDED = "amount_amended"              # an event's amount amended
    RECURRING_EXPENSE_STARTED = "recurring_expense_started"
    RECURRING_EXPENSE_CHANGED = "recurring_expense_changed"
    REFUND_PENDING = "refund_pending"
    REFUND_SETTLED = "refund_settled"
    PENDING_INCOME_NOTE = "pending_income_note"    # informational: income not yet confirmed
    IMAGE_AMOUNT = "image_amount"                  # blank event amount resolved from an image


class EvidenceSource(Enum):
    MESSAGE = "message"
    IMAGE = "image"


@dataclass(frozen=True)
class EvidenceClaim:
    source_type: EvidenceSource
    source_id: str
    user_id: str
    claim_type: ClaimType
    request_id: str | None = None
    related_event_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    effective_date: date | None = None
    settlement_date: date | None = None
    recurrence: str = "unknown"        # recurring | one_time | unchanged | unknown
    confidence: str = "high"           # high | medium | low
    provenance_text: str = ""          # short verbatim quote supporting the claim
    category_hint: str | None = None   # e.g. "childcare", "salary" (hint only)

    @property
    def provenance_hash(self) -> str:
        return hashlib.sha256(self.provenance_text.encode("utf-8")).hexdigest()[:16]


def _validated(claim: EvidenceClaim) -> EvidenceClaim:
    """Deterministic claim validation (directive section 4)."""
    if not isinstance(claim.claim_type, ClaimType):
        raise DataError(f"unknown claim type {claim.claim_type!r}", identifier=claim.source_id)
    if claim.amount is not None and not isinstance(claim.amount, Decimal):
        raise DataError("claim amount must be Decimal", identifier=claim.source_id)
    if claim.effective_date is not None and not isinstance(claim.effective_date, date):
        raise DataError("claim effective_date must be a date", identifier=claim.source_id)
    if claim.claim_type in (ClaimType.SALARY_CONFIRMED, ClaimType.SALARY_CHANGED,
                            ClaimType.SALARY_RESUMED, ClaimType.IMAGE_AMOUNT,
                            ClaimType.AMOUNT_AMENDED) and claim.amount is None:
        raise DataError(f"{claim.claim_type.value} requires an amount",
                        identifier=claim.source_id)
    if claim.source_type is EvidenceSource.IMAGE and claim.related_event_id is None:
        raise DataError("image claim must reference related_event_id",
                        identifier=claim.source_id)
    return claim


def make_claim(**kwargs) -> EvidenceClaim:
    """Build and validate a claim; raises DataError on invalid structure."""
    return _validated(EvidenceClaim(**kwargs))


def parse_claim_amount(raw: str, *, source_id: str) -> Decimal:
    value = parse_money(raw, field="evidence amount", identifier=source_id)
    if value is None:
        raise DataError("blank evidence amount", identifier=source_id)
    return value


def parse_claim_date(raw: str, *, source_id: str) -> date:
    value = parse_date(raw, field="evidence date", identifier=source_id, nullable=False)
    return value
