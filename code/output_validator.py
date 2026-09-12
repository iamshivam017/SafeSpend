"""Official output-contract parsing and invariant validation (Phase 1 scope).

Validates every invariant expressible without the finance engine (docs/01 §2,
docs/03 R15–R33). Checks that need Phase 2/3 financial semantics are explicit
TODO hooks, never fake validations.

Structural checks implemented now:
- exact column set/order; one row per evaluation request; no duplicates/extras
- amount bounds 0 <= asp <= requested_amount
- allowed enum values
- payment_plan syntax: "none" or chronological "YYYY-MM-DD:amount|..." entries
- installment plans exactly match a supplied payment option (when options given)
- partial_payment plan shape: exactly two payments summing to requested_amount,
  first on request_date == asp, second on earliest_date_for_full_payment,
  earliest <= desired_completion_date, status == affordable_with_plan,
  request.allows_partial_payment true, 0 < asp < requested (needs profile for
  method acceptance -> hook)
- affordable_now => earliest == request_date (one-directional, D13)
- spending-change syntax, <=3, no duplicate identical commands, no stop+reduce
  on the same event, event exists (when events given); financial eligibility
  of the event -> Phase 3 hook
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .errors import DataError
from .parsing import parse_date, parse_money
from .schemas import (OUTPUT_COLUMNS, AffordabilityStatus, RecommendedPaymentMethod, Request)

_PLAN_ENTRY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}):(.+)$")
_STOP_RE = re.compile(r"^stop:(.+)$")
_REDUCE_RE = re.compile(r"^reduce_to:(.+):(.+)$")


@dataclass(frozen=True)
class PlanEntry:
    payment_date: date
    amount: Decimal


@dataclass(frozen=True)
class SpendingChange:
    action: str  # "stop" | "reduce_to"
    event_id: str
    new_amount: Decimal | None  # only for reduce_to


def parse_payment_plan(raw: str, *, file: str | None = None, row: int | None = None,
                       identifier: str | None = None) -> list[PlanEntry] | None:
    """Parse official payment_plan syntax. "none" (or blank) -> None.

    Raises DataError on malformed entries; enforces non-negative amounts and
    chronological ordering (official requirement).
    """
    if raw is None or raw.strip() == "" or raw.strip() == "none":
        return None
    entries: list[PlanEntry] = []
    for part in raw.split("|"):
        match = _PLAN_ENTRY_RE.match(part.strip())
        if not match:
            raise DataError(f"invalid payment plan entry {part!r} (expected "
                            f"YYYY-MM-DD:amount)", file=file, row=row, identifier=identifier)
        payment_date = parse_date(match.group(1), field="payment_plan date", file=file,
                                  row=row, identifier=identifier, nullable=False)
        amount = parse_money(match.group(2), field="payment_plan amount", file=file,
                             row=row, identifier=identifier)
        if amount is None:
            raise DataError(f"payment plan entry {part!r} has a blank amount",
                            file=file, row=row, identifier=identifier)
        if amount < 0:
            raise DataError(f"payment plan entry {part!r} has a negative amount",
                            file=file, row=row, identifier=identifier)
        entries.append(PlanEntry(payment_date=payment_date, amount=amount))
    for previous, current in zip(entries, entries[1:]):
        if current.payment_date < previous.payment_date:
            raise DataError("payment plan entries are not in chronological order",
                            file=file, row=row, identifier=identifier)
    return entries


def parse_spending_changes(raw: str, *, file: str | None = None, row: int | None = None,
                           identifier: str | None = None) -> list[SpendingChange]:
    """Parse official spending_changes_needed syntax. "none" (or blank) -> [].

    Enforces the official maximum of three changes, no duplicate identical
    commands, and no stop+reduce_to on the same event (official rule).
    """
    if raw is None or raw.strip() == "" or raw.strip() == "none":
        return []
    changes: list[SpendingChange] = []
    for part in raw.split("|"):
        text = part.strip()
        stop = _STOP_RE.match(text)
        reduce = _REDUCE_RE.match(text)
        if stop and not reduce:
            changes.append(SpendingChange(action="stop", event_id=stop.group(1).strip(),
                                          new_amount=None))
        elif reduce:
            amount = parse_money(reduce.group(2), field="spending change amount", file=file,
                                 row=row, identifier=identifier)
            if amount is None:
                raise DataError(f"reduce_to change {text!r} has a blank amount",
                                file=file, row=row, identifier=identifier)
            if amount < 0:
                raise DataError(f"reduce_to change {text!r} has a negative amount",
                                file=file, row=row, identifier=identifier)
            changes.append(SpendingChange(action="reduce_to", event_id=reduce.group(1).strip(),
                                          new_amount=amount))
        else:
            raise DataError(f"invalid spending change {text!r} (expected "
                            f"stop:<event_id> or reduce_to:<event_id>:<amount>)",
                            file=file, row=row, identifier=identifier)
    if len(changes) > 3:
        raise DataError(f"too many spending changes ({len(changes)} > 3)",
                        file=file, row=row, identifier=identifier)
    seen: set[tuple[str, str, str]] = set()
    touched: dict[str, set[str]] = {}
    for change in changes:
        signature = (change.action, change.event_id,
                     format(change.new_amount, "f") if change.new_amount is not None else "")
        if signature in seen:
            raise DataError(f"duplicate identical spending change {text!r}",
                            file=file, row=row, identifier=identifier)
        seen.add(signature)
        touched.setdefault(change.event_id, set()).add(change.action)
    for event_id, actions in touched.items():
        if len(actions) > 1:
            raise DataError(f"event {event_id!r} receives both stop and reduce_to "
                            f"(mutually exclusive per official rules)",
                            file=file, row=row, identifier=identifier)
    return changes


def format_payment_plan(entries: list[PlanEntry] | None) -> str:
    """Serialize parsed plan entries back to the official string form."""
    if not entries:
        return "none"
    return "|".join(f"{e.payment_date.isoformat()}:{format(e.amount, 'f')}" for e in entries)


def format_spending_changes(changes: list[SpendingChange]) -> str:
    if not changes:
        return "none"
    parts = []
    for change in changes:
        if change.action == "stop":
            parts.append(f"stop:{change.event_id}")
        else:
            parts.append(f"reduce_to:{change.event_id}:{format(change.new_amount, 'f')}")
    return "|".join(parts)


def _validate_installments_match_option(entries: list[PlanEntry], request_id: str,
                                        options_by_request: dict | None,
                                        violations: list[str]) -> None:
    """Official: installment plans must exactly match a supplied payment option."""
    if options_by_request is None:
        return  # context unavailable (pure-syntax mode); structural check runs in main flow
    options = options_by_request.get(request_id, [])
    for option in options:
        if option.payment_method.value != "installments":
            continue
        expected_dates = [option.first_payment_date]
        if option.payment_frequency_days is not None:
            from datetime import timedelta
            for k in range(1, option.number_of_payments):
                expected_dates.append(option.first_payment_date
                                      + timedelta(days=option.payment_frequency_days * k))
        if (len(entries) == option.number_of_payments
                and all(e.amount == option.payment_amount for e in entries)
                and all(e.payment_date == d for e, d in zip(entries, expected_dates))):
            return
    violations.append(f"{request_id}: installment plan does not exactly match any "
                      f"supplied payment option")


def validate_output_rows(rows: list[dict[str, str]], *,
                         requests_by_id: dict[str, Request] | None = None,
                         options_by_request: dict | None = None,
                         events_by_id: dict | None = None,
                         profiles_by_user_id: dict | None = None,
                         require_full_coverage: bool = True) -> list[str]:
    """Validate prediction rows against every Phase-1-expressible official invariant.

    Returns a list of violation strings (empty list = valid). Rows are raw
    string dicts keyed by the official column names, in official order.
    Set require_full_coverage=False when validating isolated rows (unit tests);
    the final full-output run always uses the default True.
    """
    violations: list[str] = []

    # --- schema-level: exact columns, in exact order ---
    # (column order is enforced by the writer; here we validate the dict keys)
    for index, row in enumerate(rows):
        if set(row.keys()) != set(OUTPUT_COLUMNS):
            missing = [c for c in OUTPUT_COLUMNS if c not in row]
            extra = [c for c in row if c not in OUTPUT_COLUMNS]
            violations.append(f"row {index}: column mismatch "
                              f"(missing={missing}, unexpected={extra})")
            return violations  # cannot continue meaningfully without the schema

    if requests_by_id is not None and require_full_coverage:
        seen_ids: list[str] = []
        for row in rows:
            seen_ids.append(row["request_id"])
        duplicates = sorted({rid for rid in seen_ids if seen_ids.count(rid) > 1})
        if duplicates:
            violations.append(f"duplicate request_id(s) in output: {duplicates}")
        expected_ids = set(requests_by_id)
        produced = set(seen_ids)
        missing_ids = sorted(expected_ids - produced)
        extra_ids = sorted(produced - expected_ids)
        if missing_ids:
            violations.append(f"missing predictions for request_id(s): {missing_ids}")
        if extra_ids:
            violations.append(f"unexpected request_id(s) not in requests.csv: {extra_ids}")
    elif requests_by_id is not None:
        for row in rows:
            if row["request_id"] not in requests_by_id:
                violations.append(f"unexpected request_id(s) not in requests.csv: "
                                  f"[{row['request_id']!r}]")

    for index, row in enumerate(rows):
        rid = row["request_id"]
        request = requests_by_id.get(rid) if requests_by_id else None

        # amount_safe_to_pay: valid Decimal within [0, requested_amount]
        try:
            asp = parse_money(row["amount_safe_to_pay"], field="amount_safe_to_pay",
                              identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            continue
        if asp is None:
            violations.append(f"{rid}: amount_safe_to_pay must not be blank")
            continue
        if asp < 0:
            violations.append(f"{rid}: amount_safe_to_pay {asp} is negative")
        if request is not None and asp > request.requested_amount:
            violations.append(f"{rid}: amount_safe_to_pay {asp} exceeds requested_amount "
                              f"{request.requested_amount}")

        # enums
        try:
            status = AffordabilityStatus.parse(row["affordability_status"],
                                               field_name="affordability_status",
                                               identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            status = None
        try:
            method = RecommendedPaymentMethod.parse(row["recommended_payment_method"],
                                                    field_name="recommended_payment_method",
                                                    identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            method = None

        if not row["decision_explanation"].strip():
            violations.append(f"{rid}: decision_explanation must not be empty")

        # earliest_date_for_full_payment
        try:
            earliest = parse_date(row["earliest_date_for_full_payment"],
                                  field="earliest_date_for_full_payment", identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            earliest = None

        # affordable_now => earliest == request_date (one-directional; D13)
        if request is not None and status == AffordabilityStatus.AFFORDABLE_NOW \
                and earliest != request.request_date:
            violations.append(f"{rid}: affordable_now requires earliest_date_for_full_payment "
                              f"== request_date ({request.request_date}), got "
                              f"{row['earliest_date_for_full_payment']!r}")

        # payment plan
        try:
            plan = parse_payment_plan(row["payment_plan"], identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            plan = None

        # method-specific structural rules
        if method == RecommendedPaymentMethod.PARTIAL_PAYMENT and request is not None:
            if status != AffordabilityStatus.AFFORDABLE_WITH_PLAN:
                violations.append(f"{rid}: partial_payment requires affordability_status "
                                  f"affordable_with_plan (official)")
            if not request.allows_partial_payment:
                violations.append(f"{rid}: partial_payment recommended but request does "
                                  f"not allow partial payment")
            if not (0 < asp < request.requested_amount):
                violations.append(f"{rid}: partial_payment requires "
                                  f"0 < amount_safe_to_pay < requested_amount "
                                  f"(got {asp} vs requested {request.requested_amount})")
            if plan is not None and len(plan) != 2:
                violations.append(f"{rid}: partial_payment plan must contain exactly two "
                                  f"payments (got {len(plan)})")
            elif plan is not None and len(plan) == 2:
                first, second = plan
                if first.payment_date != request.request_date or first.amount != asp:
                    violations.append(f"{rid}: partial_payment first payment must be "
                                      f"amount_safe_to_pay on request_date")
                if second.amount != request.requested_amount - asp:
                    violations.append(f"{rid}: partial_payment payments must add up to "
                                      f"requested_amount")
                if earliest is not None and second.payment_date != earliest:
                    violations.append(f"{rid}: partial_payment second payment must fall on "
                                      f"earliest_date_for_full_payment")
            if request is not None and earliest is not None \
                    and earliest > request.desired_completion_date:
                violations.append(f"{rid}: partial_payment requires earliest_date "
                                  f"on or before desired_completion_date")

        if method == RecommendedPaymentMethod.INSTALLMENTS and plan is not None \
                and len(plan) < 2:
            violations.append(f"{rid}: installment plan must have more than one payment")
        if method == RecommendedPaymentMethod.INSTALLMENTS and plan is not None:
            _validate_installments_match_option(plan, rid, options_by_request, violations)

        if method == RecommendedPaymentMethod.NOT_RECOMMENDED and plan is not None:
            violations.append(f"{rid}: not_recommended requires payment_plan 'none'")

        # spending changes
        try:
            changes = parse_spending_changes(row["spending_changes_needed"], identifier=rid)
        except DataError as exc:
            violations.append(f"{rid}: {exc}")
            changes = None
        if changes:
            if events_by_id is not None:
                for change in changes:
                    if change.event_id not in events_by_id:
                        violations.append(f"{rid}: spending change targets unknown event "
                                          f"{change.event_id!r}")
            # TODO(Phase 3): validate financial eligibility of each target event
            #  (recurring + flexibility != fixed + category in user's permitted
            #  lists + reduce_to >= minimum_allowed_amount).

        # TODO(Phase 2/3): financial-semantics hooks — min-balance safety of the
        #  plan (90-day simulation), asp/earliest recomputation without spending
        #  changes, spending-change optimality, not_recommended fallback check.
        _ = profiles_by_user_id  # acceptance of partial_payment per profile -> Phase 3

    return violations


def validate_output_header(header: list[str]) -> list[str]:
    """Exact official column order check for a generated output.csv."""
    if tuple(header) != OUTPUT_COLUMNS:
        return [f"output header {header!r} != official column order {list(OUTPUT_COLUMNS)!r}"]
    return []
