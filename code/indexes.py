"""Reusable deterministic lookup indexes over the loaded datasets.

Built once per run; later phases must never re-filter full tables inside loops.
All mappings preserve dataset file order for deterministic iteration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .data_loader import DatasetBundle
from .errors import DuplicateIdError
from .schemas import (ExchangeRate, FinancialEvent, FinancialProfile, ImageEvidenceReference,
                      Message, PaymentOption, Request, SampleRequest)


@dataclass(frozen=True)
class RateKey:
    rate_date: date
    from_currency: str
    to_currency: str


@dataclass
class Indexes:
    profiles_by_user_id: dict[str, FinancialProfile]
    events_by_event_id: dict[str, FinancialEvent]
    events_by_user_id: dict[str, list[FinancialEvent]]        # dataset order
    requests_by_request_id: dict[str, Request]
    samples_by_request_id: dict[str, SampleRequest]
    options_by_request_id: dict[str, list[PaymentOption]]     # dataset order
    options_by_option_id: dict[str, PaymentOption]
    messages_by_request_id: dict[str, list[Message]]          # dataset order
    messages_by_user_id: dict[str, list[Message]]             # dataset order
    images_by_request_id: dict[str, list[ImageEvidenceReference]]
    images_by_related_event_id: dict[str, list[ImageEvidenceReference]]
    _rates: dict[RateKey, Decimal] = field(default_factory=dict)

    @classmethod
    def build(cls, bundle: DatasetBundle) -> "Indexes":
        def unique_index(items: list, key, label: str) -> dict:
            index: dict = {}
            for item in items:
                k = key(item)
                if k in index:
                    raise DuplicateIdError(f"duplicate {label} {k!r}", identifier=str(k))
                index[k] = item
            return index

        def group(items: list, key) -> dict:
            grouped: dict = {}
            for item in items:
                grouped.setdefault(key(item), []).append(item)
            return grouped

        profiles = unique_index(bundle.profiles, lambda p: p.user_id, "profile user_id")
        events = unique_index(bundle.events, lambda e: e.event_id, "event_id")
        requests = unique_index(bundle.requests, lambda r: r.request_id, "request_id")
        samples = unique_index(bundle.samples, lambda s: s.request.request_id, "sample request_id")
        options = unique_index(bundle.options, lambda o: o.payment_option_id, "payment_option_id")

        rates: dict[RateKey, Decimal] = {}
        for rate in bundle.rates:
            k = RateKey(rate.rate_date, rate.from_currency, rate.to_currency)
            if k in rates:
                raise DuplicateIdError(f"duplicate exchange rate for {k}", identifier=str(k))
            rates[k] = rate.rate

        return cls(
            profiles_by_user_id=profiles,
            events_by_event_id=events,
            events_by_user_id=group(bundle.events, lambda e: e.user_id),
            requests_by_request_id=requests,
            samples_by_request_id=samples,
            options_by_request_id=group(bundle.options, lambda o: o.request_id),
            options_by_option_id=options,
            messages_by_request_id=group(
                [m for m in bundle.messages if m.request_id], lambda m: m.request_id),
            messages_by_user_id=group(bundle.messages, lambda m: m.user_id),
            images_by_request_id=group(
                [im for im in bundle.images if im.request_id], lambda im: im.request_id),
            images_by_related_event_id=group(
                [im for im in bundle.images if im.related_event_id],
                lambda im: im.related_event_id),
            _rates=rates,
        )

    def get_rate(self, rate_date: date, from_currency: str, to_currency: str) -> Decimal | None:
        """Direct dated rate lookup; None when no row exists (chaining is Phase 2 policy)."""
        return self._rates.get(RateKey(rate_date, from_currency, to_currency))
