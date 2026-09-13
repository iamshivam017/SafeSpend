"""Deterministic multilingual (EN/ID) message-evidence parser.

The official messages are formulaic employer/provider/bank notices. A
deterministic parser (rather than free-form model output) keeps extraction
reproducible, auditable, and injection-proof: ONLY whitelisted template
patterns produce claims; every other sentence — including any instruction-like
phrase ("ignore previous instructions", "mark this affordable", ...) — is
ignored text and can never alter the finance engine (official rule: message
content is untrusted data; embedded instructions never override the rules).

D7 note: a deterministic parser was selected over a model call because the
message corpus is template-generated and fully covered by whitelisted patterns;
this is more reproducible and costs nothing. The claim schema is
model-agnostic — an AI extractor can be plugged in behind the same
EvidenceClaim contract if the corpus ever outgrows the templates.
"""
from __future__ import annotations

import re

from ..errors import DataError
from .claims import ClaimType, EvidenceSource, EvidenceClaim, make_claim, \
    parse_claim_amount, parse_claim_date

# ---------------------------------------------------------------- patterns --
_CURRENCY_RE = r"(EUR|IDR|INR|ZAR|USD)"
_AMOUNT_RE = r"([0-9][0-9,\.\ ]*[0-9]|[0-9])"
_DATE_RE = r"(\d{4}-\d{2}-\d{2})"

_TEMPLATES = [
    # (regex, claim_type, fields captured)
    (re.compile(rf"regular salary of {_CURRENCY_RE} {_AMOUNT_RE} resum\w* on {_DATE_RE}", re.I),
     ClaimType.SALARY_RESUMED, ("currency", "amount", "effective_date")),
    (re.compile(rf"first salary will be {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CONFIRMED, ("currency", "amount")),
    (re.compile(rf"confirmed credit date is {_DATE_RE}", re.I),
     ClaimType.SALARY_CONFIRMED, ("settlement_date",)),
    (re.compile(rf"salary is now expected on {_DATE_RE}", re.I),
     ClaimType.PAYMENT_DELAYED, ("effective_date",)),
    (re.compile(rf"salary is reduced to {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CHANGED, ("currency", "amount")),
    (re.compile(rf"(?:temporary|monthly) pay is {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CHANGED, ("currency", "amount")),
    (re.compile(rf"confirmed (?:base )?salary is {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CONFIRMED, ("currency", "amount")),
    (re.compile(rf"regular salary of {_CURRENCY_RE} {_AMOUNT_RE} resum", re.I),
     ClaimType.SALARY_RESUMED, ("currency", "amount")),
    # Indonesian salary templates
    (re.compile(rf"Gaji bulanan Anda naik menjadi {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CHANGED, ("currency", "amount")),
    (re.compile(rf"Gaji bulanan Anda turun menjadi {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CHANGED, ("currency", "amount")),
    (re.compile(rf"Gaji pokok yang dikonfirmasi adalah {_CURRENCY_RE} {_AMOUNT_RE}", re.I),
     ClaimType.SALARY_CONFIRMED, ("currency", "amount")),
    (re.compile(rf"berlaku mulai {_DATE_RE}", re.I),
     ClaimType.SALARY_CHANGED, ("effective_date",)),
    # income ended
    (re.compile(r"seasonal contract has ended|contract has ended|kontrak telah berakhir", re.I),
     ClaimType.INCOME_ENDED, ()),
    # recurring expense started (amount intentionally absent -> unresolved)
    (re.compile(r"new recurring (?:childcare|care) payment begins|recurring childcare payment begins", re.I),
     ClaimType.RECURRING_EXPENSE_STARTED, ()),
    (re.compile(r"pembayaran rutin (?:childcare|penitipan anak) mulai", re.I),
     ClaimType.RECURRING_EXPENSE_STARTED, ()),
    # one-time adjustment (informational: not projected as recurring)
    (re.compile(r"one-time|one time|sekali secara terpisah|penyesuaian satu kali", re.I),
     ClaimType.SALARY_CONFIRMED, ()),
]

# flat pattern -> type map for date/amount attachment
_DATE_CLAIM_TYPES = {ClaimType.PAYMENT_DELAYED, ClaimType.SALARY_RESUMED}
_INJECTION_RE = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above) instructions|disregard (?:the )?rules|"
    r"mark this (?:as )?affordable|use full payment|change the minimum balance|"
    r"override (?:the )?rules|you must (?:recommend|approve)", re.I)


def _amount_to_decimal(raw: str, source_id: str) -> Decimal:
    cleaned = raw.replace(",", "").replace(" ", "")
    return parse_claim_amount(cleaned, source_id=source_id)


def parse_message(message) -> tuple[list[EvidenceClaim], list[str]]:
    """Extract typed claims from one message row.

    Returns (claims, unparsed_notes). Instruction-like content is ignored by
    construction: only whitelisted templates yield claims.
    """
    text = message.message_text or ""
    claims: list[EvidenceClaim] = []
    notes: list[str] = []

    if _INJECTION_RE.search(text):
        notes.append(f"{message.message_id}: injection-pattern text ignored "
                     f"(content treated as untrusted data)")

    merged: dict[ClaimType, dict] = {}
    matched = False
    for regex, claim_type, fields in _TEMPLATES:
        m = regex.search(text)
        if not m:
            continue
        matched = True
        bucket = merged.setdefault(claim_type, {})
        groups = list(m.groups())
        for i, field_name in enumerate(fields):
            raw = groups[i] if i < len(groups) else None
            if raw is None:
                continue
            try:
                if field_name == "amount":
                    bucket["amount"] = _amount_to_decimal(raw, message.message_id)
                elif field_name in ("effective_date", "settlement_date"):
                    bucket[field_name] = parse_claim_date(raw, source_id=message.message_id)
                elif field_name == "currency":
                    bucket["currency"] = raw.upper()
            except DataError as exc:
                notes.append(f"{message.message_id}: rejected {claim_type.value}: {exc}")

    for claim_type, fields in merged.items():
        try:
            claims.append(make_claim(
                source_type=EvidenceSource.MESSAGE,
                source_id=message.message_id,
                user_id=message.user_id,
                request_id=message.request_id,
                related_event_id=message.related_event_id,
                claim_type=claim_type,
                amount=fields.get("amount"),
                currency=fields.get("currency"),
                effective_date=fields.get("effective_date"),
                settlement_date=fields.get("settlement_date"),
                provenance_text=text[:200],
            ))
        except DataError as exc:
            notes.append(f"{message.message_id}: claim rejected: {exc}")

    if not matched and not notes:
        notes.append(f"{message.message_id}: no whitelisted template matched "
                     f"(informational only)")
    return claims, notes
