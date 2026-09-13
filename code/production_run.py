"""Phase 6: final 250-request production run, output.csv generation, validation.

Generates root output.csv from the evidence-aware deterministic planner,
validates the serialized artifact at the disk level, and reports run metrics.
Uses the same production path as all prior phases — no shortcuts, no sample
labels, no AI decisions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .config import OUTPUT_CSV, REPO_ROOT
from .errors import SafeSpendError
from .finance.simulator import SafetyState
from .planning.models import Method
from .output_validator import OUTPUT_COLUMNS, validate_output_header

_CANDIDATE_COLUMNS = (
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
)

_VALID_STATUSES = {"affordable_now", "affordable_with_plan",
                   "affordable_later", "not_affordable"}
_VALID_METHODS = {"full_payment", "partial_payment", "installments",
                  "wait", "not_recommended"}

_PLAN_ENTRY_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}:\d+(\.\d+)?$")
_DATE_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def _format_plan(decision) -> str:
    if decision.payment_plan is None:
        return "none"
    return "|".join(f"{p.payment_date.isoformat()}:{format(p.amount, 'f')}"
                    for p in decision.payment_plan)


def _format_changes(decision) -> str:
    if not decision.spending_changes:
        return "none"
    parts = []
    for c in decision.spending_changes:
        if c.action == "stop":
            parts.append(f"stop:{c.event_id}")
        else:
            parts.append(f"reduce_to:{c.event_id}:{format(c.new_amount, 'f')}")
    return "|".join(parts)


def _format_earliest(decision) -> str:
    if decision.earliest_date_for_full_payment is not None:
        return decision.earliest_date_for_full_payment.isoformat()
    return ""


def _explanation(decision) -> str:
    """Deterministic, grounded explanation (no LLM)."""
    facts = []
    asp = format(decision.amount_safe_to_pay, "f")
    method = decision.recommended_payment_method.value
    floor = format(decision.baseline.minimum_balance_required, "f")
    if method == "not_recommended":
        if decision.baseline.asp_uncertain:
            facts.append(f"Cannot recommend: material unresolved evidence "
                         f"prevents a provably safe amount (conservative ASP={asp}).")
        else:
            facts.append(f"Cannot afford {decision.request_id} safely within the "
                         f"horizon; ASP={asp} with minimum balance {floor} protected.")
    elif method == "wait":
        earliest = _format_earliest(decision)
        facts.append(f"Wait and pay {decision.payment_plan[0].amount if decision.payment_plan else asp} "
                     f"on {earliest}; minimum balance {floor} protected throughout.")
    else:
        facts.append(f"Pay {asp} today" +
                     (f" via {method}" if method != "full_payment" else "") +
                     f"; minimum balance {floor} protected.")
        if decision.spending_changes:
            facts.append("Spending changes applied: "
                         + "; ".join(f"{c.action}:{c.event_id}"
                                     + (f" to {format(c.new_amount, 'f')}"
                                        if c.new_amount is not None else "")
                                     for c in decision.spending_changes) + ".")
    return " ".join(facts)


def _serialize_rows(decisions: list, requests_by_id: dict) -> list[list[str]]:
    """Convert Decisions to CSV rows with per-row safety checks."""
    rows = []
    for d in decisions:
        request = requests_by_id[d.request_id]
        # safety revalidation
        if d.selected_candidate is not None:
            if d.selected_candidate.sim_state is not SafetyState.SAFE:
                raise SafeSpendError(
                    f"{d.request_id}: selected candidate state "
                    f"{d.selected_candidate.sim_state.value} is not SAFE")
        if d.selected_candidate is None \
                and d.recommended_payment_method is not Method.NOT_RECOMMENDED:
            raise SafeSpendError(
                f"{d.request_id}: {d.recommended_payment_method.value} without "
                f"selected candidate")
        asp = d.amount_safe_to_pay
        if asp < 0 or asp > request.requested_amount:
            raise SafeSpendError(f"{d.request_id}: ASP {asp} out of range")
        if d.affordability_status.value not in _VALID_STATUSES:
            raise SafeSpendError(f"{d.request_id}: invalid status")
        if d.recommended_payment_method.value not in _VALID_METHODS:
            raise SafeSpendError(f"{d.request_id}: invalid method")
        explanation = _explanation(d)
        if not explanation.strip():
            raise SafeSpendError(f"{d.request_id}: empty explanation")
        rows.append([
            d.request_id,
            format(asp, "f"),
            d.affordability_status.value,
            d.recommended_payment_method.value,
            _format_plan(d),
            _format_earliest(d),
            _format_changes(d),
            explanation,
        ])
    return rows


def generate_output(decisions: list, requests_by_id: dict,
                    output_path: Path | None = None) -> tuple[bytes, str]:
    """Serialize, validate, and return (csv_bytes, sha256_hex).

    Writes to a temporary file first, validates, then atomically replaces
    the target. Never leaves a partially written submission file.
    """
    if output_path is None:
        output_path = OUTPUT_CSV
    rows = _serialize_rows(decisions, requests_by_id)
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(OUTPUT_COLUMNS)
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    # atomic write: temp file → validate → rename
    tmp = output_path.with_suffix(".tmp")
    tmp.write_bytes(data)
    # disk-level validation
    _validate_serialized(tmp, requests_by_id)
    os.replace(str(tmp), str(output_path))
    return data, sha


def _validate_serialized(path: Path, requests_by_id: dict) -> dict:
    """Disk-level submission validator: reads the actual CSV and checks everything."""
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        raise SafeSpendError("output.csv is empty")
    header = all_rows[0]
    violations = validate_output_header(header)
    if violations:
        raise SafeSpendError(f"header violation: {violations}")
    data_rows = all_rows[1:]
    if len(data_rows) != len(requests_by_id):
        raise SafeSpendError(f"row count {len(data_rows)} != expected {len(requests_by_id)}")
    seen_ids = set()
    for i, row in enumerate(data_rows, start=2):
        if len(row) != len(OUTPUT_COLUMNS):
            raise SafeSpendError(f"line {i}: {len(row)} columns, expected {len(OUTPUT_COLUMNS)}")
        rid = row[0]
        if rid in seen_ids:
            raise SafeSpendError(f"line {i}: duplicate request_id {rid!r}")
        seen_ids.add(rid)
        if rid not in requests_by_id:
            raise SafeSpendError(f"line {i}: unknown request_id {rid!r}")
        asp_str = row[1]
        if not asp_str or asp_str.startswith("-") or "e" in asp_str.lower():
            raise SafeSpendError(f"line {i}: invalid ASP {asp_str!r}")
        if row[2] not in _VALID_STATUSES:
            raise SafeSpendError(f"line {i}: invalid status {row[2]!r}")
        if row[3] not in _VALID_METHODS:
            raise SafeSpendError(f"line {i}: invalid method {row[3]!r}")
        plan = row[4]
        if row[3] == "not_recommended" and plan != "none":
            raise SafeSpendError(f"line {i}: not_recommended must have plan 'none'")
        if plan != "none":
            for part in plan.split("|"):
                if not _PLAN_ENTRY_RE.match(part):
                    raise SafeSpendError(f"line {i}: invalid plan entry {part!r}")
        earliest = row[5]
        if earliest and not _DATE_RE.match(earliest):
            raise SafeSpendError(f"line {i}: invalid earliest date {earliest!r}")
        changes = row[6]
        if changes != "none":
            for part in changes.split("|"):
                if not (part.startswith("stop:") or part.startswith("reduce_to:")):
                    raise SafeSpendError(f"line {i}: invalid change {part!r}")
        if not row[7].strip():
            raise SafeSpendError(f"line {i}: empty explanation")
    expected_ids = set(requests_by_id.keys())
    missing = expected_ids - seen_ids
    if missing:
        raise SafeSpendError(f"missing request IDs: {sorted(missing)[:5]}...")
    extra = seen_ids - expected_ids
    if extra:
        raise SafeSpendError(f"extra request IDs: {sorted(extra)[:5]}...")
    return {"rows": len(data_rows), "header": header,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw)}


def run_final_production() -> dict:
    """Execute the full 250-request production run and generate output.csv."""
    from .data_loader import load_all
    from .evidence.apply import collect_claims
    from .finance import recurrence as rec
    from .indexes import Indexes
    from .planning.planner import plan_for_request

    # freeze-check: production defaults must be canonical
    dp = rec.DEFAULT_PROVISION_PARAMS
    if dp.scope != "protected" or dp.occurrences != 1 or dp.statistic != "median":
        raise SafeSpendError(
            f"production defaults are not frozen: scope={dp.scope!r} "
            f"occurrences={dp.occurrences} statistic={dp.statistic!r}")

    bundle = load_all()
    indexes = Indexes.build(bundle)
    claims = collect_claims(bundle)
    requests_by_id = {r.request_id: r for r in bundle.requests}
    decisions = []
    t0 = datetime.now()
    for request in bundle.requests:
        decision, _facts = plan_for_request(bundle, indexes, request, claims)
        decisions.append(decision)
    elapsed = (datetime.now() - t0).total_seconds()
    data, sha = generate_output(decisions, requests_by_id)
    return {"decisions": decisions, "sha256": sha, "elapsed": elapsed,
            "data": data, "timestamp": t0.isoformat()}


def run_reproducibility_check() -> tuple[bool, str, str]:
    """Run the full production generation twice (fresh data load each time).
    Returns (identical, sha1, sha2)."""
    run1 = run_final_production()
    run2 = run_final_production()
    return run1["sha256"] == run2["sha256"], run1["sha256"], run2["sha256"]
