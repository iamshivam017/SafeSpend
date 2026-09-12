"""Deterministic loaders for the participant-facing datasets.

Fail-fast on structural problems (missing/extra headers, malformed values,
duplicate primary identifiers) with file/row/identifier context. Officially
valid nullable fields (blank amounts, blank settlement dates, blank
related_event_id, ...) stay None — never coerced to defaults.

dataset/output.csv is NOT loaded as ground truth anywhere.
"""
from __future__ import annotations

import csv
from pathlib import Path

from . import config
from .errors import DataError, DuplicateIdError, HeaderError
from .parsing import parse_bool, parse_date, parse_int, parse_money, parse_pipe_list
from .schemas import (EventDirection, EventStatus, EventType, ExchangeRate,
                      FinancialEvent, FinancialProfile, Flexibility, ImageEvidenceReference,
                      Message, PaymentMethod, PaymentOption, Request, RequestType,
                      SampleRequest, AffordabilityStatus, RecommendedPaymentMethod)

# (file stem -> required header tuple). Exact set equality is enforced so any
# upstream schema change surfaces immediately instead of silently shifting data.
_REQUIRED_HEADERS: dict[str, tuple[str, ...]] = {
    "requests": ("request_id", "user_id", "request_date", "request_type",
                 "requested_amount", "desired_completion_date", "allows_partial_payment",
                 "request_text"),
    "sample_requests": ("request_id", "user_id", "request_date", "request_type",
                        "requested_amount", "desired_completion_date", "allows_partial_payment",
                        "request_text", "amount_safe_to_pay", "affordability_status",
                        "recommended_payment_method", "payment_plan",
                        "earliest_date_for_full_payment", "spending_changes_needed",
                        "decision_explanation"),
    "financial_profiles": ("user_id", "home_currency", "current_available_balance",
                           "minimum_balance_to_keep", "financial_priorities",
                           "expense_categories_to_protect",
                           "expense_categories_user_is_willing_to_reduce",
                           "expense_categories_user_is_willing_to_stop",
                           "payment_methods_user_will_consider", "max_installment_months"),
    "financial_events": ("event_id", "user_id", "event_type", "description", "category",
                         "direction", "amount", "currency", "event_date", "settlement_date",
                         "status", "linked_event_id", "flexibility", "minimum_allowed_amount"),
    "request_payment_options": ("payment_option_id", "request_id", "payment_method",
                                "payment_amount", "number_of_payments", "first_payment_date",
                                "payment_frequency_days", "financing_fee",
                                "total_payable_amount"),
    "exchange_rates": ("rate_date", "from_currency", "to_currency", "rate"),
    "messages": ("message_id", "user_id", "request_id", "related_event_id", "sent_at",
                 "source_type", "message_text"),
    "images": ("image_id", "user_id", "request_id", "related_event_id"),
}


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read a CSV, enforcing the exact expected header set, preserving raw strings."""
    if not path.exists():
        raise DataError(f"required dataset file not found: {path}", file=str(path))
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise HeaderError("empty CSV (no header row)", file=path.name)
        headers = tuple(reader.fieldnames)
        expected = _REQUIRED_HEADERS[path.stem]
        missing = [h for h in expected if h not in headers]
        extra = [h for h in headers if h not in expected]
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"missing columns {missing}")
            if extra:
                parts.append(f"unexpected columns {extra}")
            raise HeaderError("; ".join(parts), file=path.name)
        rows = []
        for row_number, record in enumerate(reader, start=2):  # header is line 1
            if any(v is None for v in record.values()):
                raise DataError("row has fewer fields than the header",
                                file=path.name, row=row_number)
            rows.append(record)
        return list(headers), rows


def _require_unique(rows: list[dict[str, str]], key: str, path: Path) -> None:
    seen: set[str] = set()
    for row_number, record in enumerate(rows, start=2):
        value = record[key].strip()
        if not value:
            raise DataError(f"blank primary identifier {key!r}", file=path.name,
                            row=row_number)
        if value in seen:
            raise DuplicateIdError(f"duplicate {key} {value!r}", file=path.name,
                                   row=row_number, identifier=value)
        seen.add(value)


def load_requests(path: Path = config.REQUESTS_CSV) -> list[Request]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "request_id", path)
    requests = []
    for i, r in enumerate(rows, start=2):
        rid = r["request_id"].strip()
        requests.append(Request(
            request_id=rid,
            user_id=r["user_id"].strip(),
            request_date=parse_date(r["request_date"], field="request_date",
                                    file=path.name, row=i, identifier=rid, nullable=False),
            request_type=RequestType.parse(r["request_type"], field_name="request_type",
                                           file=path.name, row=i, identifier=rid),
            requested_amount=parse_money(r["requested_amount"], field="requested_amount",
                                         file=path.name, row=i, identifier=rid),
            desired_completion_date=parse_date(r["desired_completion_date"],
                                               field="desired_completion_date",
                                               file=path.name, row=i, identifier=rid,
                                               nullable=False),
            allows_partial_payment=parse_bool(r["allows_partial_payment"],
                                              field="allows_partial_payment",
                                              file=path.name, row=i, identifier=rid),
            request_text=r["request_text"],
        ))
    return requests


def load_sample_requests(path: Path = config.SAMPLE_REQUESTS_CSV) -> list[SampleRequest]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "request_id", path)
    samples = []
    for i, r in enumerate(rows, start=2):
        rid = r["request_id"].strip()
        base = Request(
            request_id=rid,
            user_id=r["user_id"].strip(),
            request_date=parse_date(r["request_date"], field="request_date",
                                    file=path.name, row=i, identifier=rid, nullable=False),
            request_type=RequestType.parse(r["request_type"], field_name="request_type",
                                           file=path.name, row=i, identifier=rid),
            requested_amount=parse_money(r["requested_amount"], field="requested_amount",
                                         file=path.name, row=i, identifier=rid),
            desired_completion_date=parse_date(r["desired_completion_date"],
                                               field="desired_completion_date",
                                               file=path.name, row=i, identifier=rid,
                                               nullable=False),
            allows_partial_payment=parse_bool(r["allows_partial_payment"],
                                              field="allows_partial_payment",
                                              file=path.name, row=i, identifier=rid),
            request_text=r["request_text"],
        )
        samples.append(SampleRequest(
            request=base,
            amount_safe_to_pay=parse_money(r["amount_safe_to_pay"], field="amount_safe_to_pay",
                                           file=path.name, row=i, identifier=rid),
            affordability_status=AffordabilityStatus.parse(
                r["affordability_status"], field_name="affordability_status",
                file=path.name, row=i, identifier=rid),
            recommended_payment_method=RecommendedPaymentMethod.parse(
                r["recommended_payment_method"], field_name="recommended_payment_method",
                file=path.name, row=i, identifier=rid),
            payment_plan=r["payment_plan"],
            earliest_date_for_full_payment=parse_date(
                r["earliest_date_for_full_payment"], field="earliest_date_for_full_payment",
                file=path.name, row=i, identifier=rid),
            spending_changes_needed=r["spending_changes_needed"],
            decision_explanation=r["decision_explanation"],
        ))
    return samples


def load_profiles(path: Path = config.FINANCIAL_PROFILES_CSV) -> list[FinancialProfile]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "user_id", path)
    profiles = []
    for i, r in enumerate(rows, start=2):
        uid = r["user_id"].strip()
        methods = [PaymentMethod.parse(m, field_name="payment_methods_user_will_consider",
                                       file=path.name, row=i, identifier=uid)
                   for m in parse_pipe_list(r["payment_methods_user_will_consider"])]
        profiles.append(FinancialProfile(
            user_id=uid,
            home_currency=r["home_currency"].strip(),
            current_available_balance=parse_money(r["current_available_balance"],
                                                  field="current_available_balance",
                                                  file=path.name, row=i, identifier=uid),
            minimum_balance_to_keep=parse_money(r["minimum_balance_to_keep"],
                                                field="minimum_balance_to_keep",
                                                file=path.name, row=i, identifier=uid),
            financial_priorities=parse_pipe_list(r["financial_priorities"]),
            expense_categories_to_protect=parse_pipe_list(r["expense_categories_to_protect"]),
            expense_categories_user_is_willing_to_reduce=parse_pipe_list(
                r["expense_categories_user_is_willing_to_reduce"]),
            expense_categories_user_is_willing_to_stop=parse_pipe_list(
                r["expense_categories_user_is_willing_to_stop"]),
            payment_methods_user_will_consider=methods,
            max_installment_months=parse_int(r["max_installment_months"],
                                             field="max_installment_months",
                                             file=path.name, row=i, identifier=uid),
        ))
    return profiles


def load_events(path: Path = config.FINANCIAL_EVENTS_CSV) -> list[FinancialEvent]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "event_id", path)
    events = []
    for i, r in enumerate(rows, start=2):
        eid = r["event_id"].strip()
        events.append(FinancialEvent(
            event_id=eid,
            user_id=r["user_id"].strip(),
            event_type=EventType.parse(r["event_type"], field_name="event_type",
                                       file=path.name, row=i, identifier=eid),
            description=r["description"],
            category=r["category"].strip(),
            direction=EventDirection.parse(r["direction"], field_name="direction",
                                           file=path.name, row=i, identifier=eid),
            # Blank amount stays None (officially valid; image-resolved later). Never 0.
            amount=parse_money(r["amount"], field="amount", file=path.name, row=i,
                               identifier=eid),
            currency=r["currency"].strip(),
            event_date=parse_date(r["event_date"], field="event_date", file=path.name,
                                  row=i, identifier=eid, nullable=False),
            settlement_date=parse_date(r["settlement_date"], field="settlement_date",
                                       file=path.name, row=i, identifier=eid),
            status=EventStatus.parse(r["status"], field_name="status",
                                     file=path.name, row=i, identifier=eid),
            linked_event_id=r["linked_event_id"].strip() or None,
            flexibility=Flexibility.parse(r["flexibility"], field_name="flexibility",
                                          file=path.name, row=i, identifier=eid),
            minimum_allowed_amount=parse_money(r["minimum_allowed_amount"],
                                               field="minimum_allowed_amount",
                                               file=path.name, row=i, identifier=eid),
        ))
    return events


def load_payment_options(path: Path = config.REQUEST_PAYMENT_OPTIONS_CSV) -> list[PaymentOption]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "payment_option_id", path)
    options = []
    for i, r in enumerate(rows, start=2):
        oid = r["payment_option_id"].strip()
        options.append(PaymentOption(
            payment_option_id=oid,
            request_id=r["request_id"].strip(),
            payment_method=PaymentMethod.parse(r["payment_method"], field_name="payment_method",
                                               file=path.name, row=i, identifier=oid),
            payment_amount=parse_money(r["payment_amount"], field="payment_amount",
                                       file=path.name, row=i, identifier=oid),
            number_of_payments=parse_int(r["number_of_payments"], field="number_of_payments",
                                         file=path.name, row=i, identifier=oid),
            first_payment_date=parse_date(r["first_payment_date"], field="first_payment_date",
                                          file=path.name, row=i, identifier=oid, nullable=False),
            payment_frequency_days=parse_int(r["payment_frequency_days"],
                                             field="payment_frequency_days",
                                             file=path.name, row=i, identifier=oid),
            financing_fee=parse_money(r["financing_fee"], field="financing_fee",
                                      file=path.name, row=i, identifier=oid),
            total_payable_amount=parse_money(r["total_payable_amount"],
                                             field="total_payable_amount",
                                             file=path.name, row=i, identifier=oid),
        ))
    return options


def load_exchange_rates(path: Path = config.EXCHANGE_RATES_CSV) -> list[ExchangeRate]:
    _header, rows = _read_rows(path)
    rates = []
    for i, r in enumerate(rows, start=2):
        key = f"{r['from_currency'].strip()}->{r['to_currency'].strip()}@{r['rate_date'].strip()}"
        rates.append(ExchangeRate(
            rate_date=parse_date(r["rate_date"], field="rate_date", file=path.name,
                                 row=i, identifier=key, nullable=False),
            from_currency=r["from_currency"].strip(),
            to_currency=r["to_currency"].strip(),
            rate=parse_money(r["rate"], field="rate", file=path.name, row=i, identifier=key),
        ))
    return rates


def load_messages(path: Path = config.MESSAGES_CSV) -> list[Message]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "message_id", path)
    messages = []
    for i, r in enumerate(rows, start=2):
        mid = r["message_id"].strip()
        messages.append(Message(
            message_id=mid,
            user_id=r["user_id"].strip(),
            request_id=r["request_id"].strip() or None,
            related_event_id=r["related_event_id"].strip() or None,
            sent_at=r["sent_at"].strip(),
            source_type=r["source_type"].strip(),
            message_text=r["message_text"],
        ))
    return messages


def load_images(path: Path = config.IMAGES_CSV,
                media_dir: Path = config.MEDIA_IMAGES_DIR) -> list[ImageEvidenceReference]:
    _header, rows = _read_rows(path)
    _require_unique(rows, "image_id", path)
    images = []
    for i, r in enumerate(rows, start=2):
        iid = r["image_id"].strip()
        image_path = media_dir / f"{iid}.png"
        images.append(ImageEvidenceReference(
            image_id=iid,
            user_id=r["user_id"].strip(),
            request_id=r["request_id"].strip() or None,
            related_event_id=r["related_event_id"].strip() or None,
            image_path=str(image_path),
            file_exists=image_path.exists(),
        ))
    return images


class DatasetBundle:
    """All participant datasets plus the indexes built from them."""

    def __init__(self, requests: list[Request], samples: list[SampleRequest],
                 profiles: list[FinancialProfile], events: list[FinancialEvent],
                 options: list[PaymentOption], rates: list[ExchangeRate],
                 messages: list[Message], images: list[ImageEvidenceReference]):
        self.requests = requests
        self.samples = samples
        self.profiles = profiles
        self.events = events
        self.options = options
        self.rates = rates
        self.messages = messages
        self.images = images


def load_all(dataset_dir: Path | None = None) -> DatasetBundle:
    """Load every participant dataset (path override only for tests)."""
    _ = dataset_dir  # loaders take explicit paths; kept for test ergonomics
    return DatasetBundle(
        requests=load_requests(), samples=load_sample_requests(),
        profiles=load_profiles(), events=load_events(), options=load_payment_options(),
        rates=load_exchange_rates(), messages=load_messages(), images=load_images())


def validate_relationships(bundle: DatasetBundle) -> list[str]:
    """Structural sanity checks over officially valid relationships.

    Returns a list of human-readable problems (empty = structurally sound).
    Semantic financial conflicts are deliberately NOT checked here; they belong
    to lifecycle resolution (Phase 2).
    """
    problems: list[str] = []
    profile_users = {p.user_id for p in bundle.profiles}
    event_ids = {e.event_id for e in bundle.events}
    request_ids = {r.request_id for r in bundle.requests}
    sample_request_ids = {s.request.request_id for s in bundle.samples}

    for request in bundle.requests:
        if request.user_id not in profile_users:
            problems.append(f"{request.request_id}: user_id {request.user_id!r} has no profile")
    for sample in bundle.samples:
        if sample.request.user_id not in profile_users:
            problems.append(f"{sample.request.request_id}: user_id "
                            f"{sample.request.user_id!r} has no profile")
    for option in bundle.options:
        if option.request_id not in request_ids and option.request_id not in sample_request_ids:
            problems.append(f"{option.payment_option_id}: references unknown request "
                            f"{option.request_id!r}")
    for message in bundle.messages:
        if message.request_id and message.request_id not in request_ids \
                and message.request_id not in sample_request_ids:
            problems.append(f"{message.message_id}: references unknown request "
                            f"{message.request_id!r}")
        if message.related_event_id and message.related_event_id not in event_ids:
            problems.append(f"{message.message_id}: related_event_id "
                            f"{message.related_event_id!r} does not resolve")
    for event in bundle.events:
        if event.linked_event_id and event.linked_event_id not in event_ids:
            problems.append(f"{event.event_id}: linked_event_id "
                            f"{event.linked_event_id!r} does not resolve")
    for image in bundle.images:
        if image.request_id and image.request_id not in request_ids \
                and image.request_id not in sample_request_ids:
            problems.append(f"{image.image_id}: references unknown request "
                            f"{image.request_id!r}")
        if image.related_event_id and image.related_event_id not in event_ids:
            problems.append(f"{image.image_id}: related_event_id "
                            f"{image.related_event_id!r} does not resolve")
        if not image.file_exists:
            problems.append(f"{image.image_id}: image file missing at {image.image_path}")
    return problems
