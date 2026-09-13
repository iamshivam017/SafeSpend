"""Deterministic evidence application: typed claims -> financial state.

Builds an EvidenceContext per user/request:
- resolved_amounts: blank event amounts resolved from image evidence (D21 of
  the official rule: blank amount -> image -> amount; never zero on failure)
- income_series: evidence-backed confirmed income (salary resumed / confirmed /
  changed) that supersedes history-derived salary projections (official
  conflict precedence 1: explicit amendment first)
- suppress_salary_patterns: INCOME_ENDED removes future salary projections
- extra_unresolved: e.g. a recurring expense started WITHOUT an amount —
  represented as unresolved impact, never invented (conservative)

All application is deterministic; claims are data, never instructions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from ..errors import DataError
from ..schemas import EventDirection, FinancialEvent
from .claims import ClaimType, EvidenceClaim, EvidenceSource, make_claim
from ..finance.lifecycle import UnresolvedEvidence

CACHE_PATH = Path(__file__).resolve().parent / "cache.json"


@dataclass(frozen=True)
class IncomeSeries:
    amount: Decimal
    currency: str
    first_date: date
    anchor_day: int
    source_id: str


@dataclass
class EvidenceContext:
    user_id: str
    claims: list[EvidenceClaim] = field(default_factory=list)
    resolved_amounts: dict[str, Decimal] = field(default_factory=dict)
    income_series: list[IncomeSeries] = field(default_factory=list)
    suppress_salary_patterns: bool = False
    extra_unresolved: list = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def load_image_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)["resolved"]


def image_claims(bundle_images: list, cache: dict[str, dict] | None = None) -> list[EvidenceClaim]:
    """Build IMAGE_AMOUNT claims for every image whose event has a blank amount."""
    cache = cache if cache is not None else load_image_cache()
    claims = []
    for image in bundle_images:
        entry = cache.get(image.related_event_id) if image.related_event_id else None
        if not entry:
            continue
        claims.append(make_claim(
            source_type=EvidenceSource.IMAGE,
            source_id=image.image_id,
            user_id=image.user_id,
            related_event_id=image.related_event_id,
            claim_type=ClaimType.IMAGE_AMOUNT,
            amount=Decimal(entry["amount"]),
            currency=entry["currency"],
            confidence=entry.get("confidence", "high"),
            provenance_text=entry.get("provenance", ""),
        ))
    return claims


def build_evidence_context(user_id: str, request_date: date, claims: list[EvidenceClaim],
                           user_events: list[FinancialEvent]) -> EvidenceContext:
    """Apply official conflict precedence to claims for one user/request.

    Explicit amendments (claims) supersede history-derived projections;
    settled history still governs anything the evidence does not cover;
    ambiguous/insufficient evidence stays unresolved (financially safer).
    """
    ctx = EvidenceContext(user_id=user_id)
    salary_events = sorted(
        [e for e in user_events if e.category == "salary"
         and e.status.value == "settled" and e.amount is not None],
        key=lambda e: e.event_date)
    history_anchor = salary_events[-1].event_date.day if salary_events else request_date.day

    for claim in claims:
        if claim.user_id != user_id:
            continue
        ct = claim.claim_type
        if ct is ClaimType.IMAGE_AMOUNT and claim.related_event_id:
            ctx.resolved_amounts[claim.related_event_id] = claim.amount
            ctx.diagnostics.append(
                f"{claim.source_id}: event {claim.related_event_id} amount resolved "
                f"to {claim.amount} {claim.currency} ({claim.confidence})")
        elif ct is ClaimType.SALARY_RESUMED and claim.amount is not None \
                and claim.effective_date is not None:
            ctx.income_series.append(IncomeSeries(
                amount=claim.amount, currency=claim.currency or "",
                first_date=claim.effective_date,
                anchor_day=claim.effective_date.day, source_id=claim.source_id))
            ctx.diagnostics.append(
                f"{claim.source_id}: salary {claim.amount} {claim.currency} resumes "
                f"{claim.effective_date.isoformat()} (monthly series)")
        elif ct is ClaimType.SALARY_CONFIRMED and claim.amount is not None:
            first = claim.settlement_date or request_date
            anchor = first.day
            ctx.income_series.append(IncomeSeries(
                amount=claim.amount, currency=claim.currency or "",
                first_date=first, anchor_day=anchor, source_id=claim.source_id))
            ctx.diagnostics.append(
                f"{claim.source_id}: salary {claim.amount} {claim.currency} confirmed "
                f"(first credit {first.isoformat()}, monthly series)")
        elif ct is ClaimType.SALARY_CHANGED and claim.amount is not None:
            effective = claim.effective_date or request_date
            anchor = effective.day if claim.effective_date else history_anchor
            ctx.income_series.append(IncomeSeries(
                amount=claim.amount, currency=claim.currency or "",
                first_date=max(effective, request_date) if claim.effective_date else request_date,
                anchor_day=anchor, source_id=claim.source_id))
            ctx.diagnostics.append(
                f"{claim.source_id}: salary changed to {claim.amount} {claim.currency} "
                f"effective {effective.isoformat()}")
        elif ct is ClaimType.INCOME_ENDED:
            ctx.suppress_salary_patterns = True
            ctx.diagnostics.append(f"{claim.source_id}: income ended; future salary "
                                   f"projections suppressed")
        elif ct is ClaimType.RECURRING_EXPENSE_STARTED and claim.amount is None:
            category = claim.category_hint or "unresolved_recurring_expense"
            ctx.extra_unresolved.append(UnresolvedEvidence(
                event_id=f"evidence:{claim.source_id}",
                reason="recurring expense started; no amount supplied by evidence "
                       "(not invented; conservative unresolved impact)",
                effective_date=request_date,
                direction=EventDirection.DEBIT,
                category=category))
            ctx.diagnostics.append(
                f"{claim.source_id}: recurring expense started without amount -> "
                f"unresolved impact (category hint: {category})")
        # informational claims (PENDING_INCOME_NOTE, REFUND_*, PAYMENT_SETTLED,
        # PAYMENT_CANCELLED) are recorded for traceability; the lifecycle
        # resolver already applies their cash semantics via linked events.

    return ctx


def apply_evidence_to_patterns(patterns: list, evidence: EvidenceContext) -> list:
    """Evidence supersedes history-derived income projections (precedence 1)."""
    if evidence is None:
        return patterns
    out = []
    for p in patterns:
        if p.direction.value == "credit" and p.category == "salary" \
                and (evidence.suppress_salary_patterns or evidence.income_series):
            continue  # evidence-backed income replaces the history estimate
        out.append(p)
    return out


def collect_claims(bundle) -> list[EvidenceClaim]:
    """Parse every message + resolve every image into typed claims (once)."""
    from .message_parser import parse_message
    claims: list[EvidenceClaim] = []
    for message in bundle.messages:
        parsed, _notes = parse_message(message)
        claims.extend(parsed)
    claims.extend(image_claims(bundle.images))
    return claims


def build_user_evidence(user_id: str, request_date, all_claims: list[EvidenceClaim],
                        user_events: list[FinancialEvent]) -> EvidenceContext:
    return build_evidence_context(user_id, request_date, all_claims, user_events)

def build_request_state(bundle, indexes: Indexes, request, all_claims=None):
    """Evidence-aware per-request financial state (Phase 4 production path).

    Returns (profile, lifecycle, patterns, timeline, evidence, unresolved).
    """
    from code.evidence.apply import (build_user_evidence, collect_claims)
    from code.finance.lifecycle import resolve_lifecycle
    from code.finance.recurrence import detect_recurring_patterns
    from code.finance.timeline import build_cash_timeline

    profile = indexes.profiles_by_user_id[request.user_id]
    user_events = indexes.events_by_user_id.get(request.user_id, [])
    claims = all_claims if all_claims is not None else collect_claims(bundle)
    evidence = build_user_evidence(request.user_id, request.request_date,
                                   claims, user_events)
    lifecycle = resolve_lifecycle(user_events, request.request_date,
                                  resolved_amounts=evidence.resolved_amounts)
    patterns = detect_recurring_patterns(user_events)
    timeline = build_cash_timeline(profile, request.request_date, lifecycle,
                                   patterns, indexes, evidence=evidence)
    unresolved = list(lifecycle.unresolved) + list(evidence.extra_unresolved)
    return profile, lifecycle, patterns, timeline, evidence, unresolved
