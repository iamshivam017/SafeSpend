"""25-sample regression evaluator (Phase 1 deliverable).

Compares candidate predictions against the solved sample answers field-by-field.
Reads sample labels ONLY here — production decision code never imports this
module or the sample answer columns (docs/07 §4 no-leak boundary).

Comparisons:
- amount_safe_to_pay: exact Decimal equality (no invented tolerance; D16)
- affordability_status / recommended_payment_method: exact
- payment_plan: parsed then compared entry-by-entry (dates exact, Decimal amounts exact)
- earliest_date_for_full_payment: exact (both-empty counts as match)
- spending_changes_needed: parsed then compared as sets (order-insensitive per
  official list semantics; Decimal amounts exact)
- decision_explanation: presence/consistency only (non-empty); no string match

Self-check mode: the solved samples are converted to OutputRows and compared
against themselves — must yield 25/25 on every field, proving the harness works
before it judges our algorithm. Mutated fixtures must fail (tested in tests/).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

from ..data_loader import load_sample_requests
from ..errors import DataError
from ..output_validator import (parse_payment_plan, parse_spending_changes)
from ..schemas import OUTPUT_COLUMNS, OutputRow, SampleRequest

FIELD_LABELS: tuple[str, ...] = (
    "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
    "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
)


def sample_to_output_row(sample: SampleRequest) -> OutputRow:
    """Convert a solved sample row into the official output shape."""
    return OutputRow(
        request_id=sample.request.request_id,
        amount_safe_to_pay=sample.amount_safe_to_pay,
        affordability_status=sample.affordability_status,
        recommended_payment_method=sample.recommended_payment_method,
        payment_plan=sample.payment_plan,
        earliest_date_for_full_payment=sample.earliest_date_for_full_payment,
        spending_changes_needed=sample.spending_changes_needed,
        decision_explanation=sample.decision_explanation,
    )


@dataclass
class RowDiff:
    request_id: str
    mismatched_fields: dict[str, dict] = dc_field(default_factory=dict)  # field -> {expected, produced}


@dataclass
class EvaluationReport:
    total: int
    field_matches: dict[str, int] = dc_field(default_factory=dict)
    diffs: list[RowDiff] = dc_field(default_factory=list)

    def is_perfect(self, fields: tuple[str, ...] = FIELD_LABELS) -> bool:
        return all(self.field_matches.get(f, 0) == self.total for f in fields)

    def summary_lines(self) -> list[str]:
        width = max(len(label) for label in FIELD_LABELS)
        lines = [f"{self.total} samples"]
        for label in FIELD_LABELS:
            matches = self.field_matches.get(label, 0)
            lines.append(f"{label:<{width}}  {matches}/{self.total}"
                         + ("" if matches == self.total else "  <-- MISMATCHES"))
        return lines


def _plan_equal(expected: str, produced: str) -> bool:
    try:
        expected_entries = parse_payment_plan(expected)
        produced_entries = parse_payment_plan(produced)
    except DataError:
        return False
    if (expected_entries is None) != (produced_entries is None):
        return False
    if expected_entries is None:
        return True
    return expected_entries == produced_entries  # dataclass equality: exact dates+Decimals


def _changes_equal(expected: str, produced: str) -> bool:
    try:
        expected_changes = parse_spending_changes(expected)
        produced_changes = parse_spending_changes(produced)
    except DataError:
        return False
    def normalized(changes):
        return sorted((c.action, c.event_id,
                       None if c.new_amount is None else c.new_amount) for c in changes)
    return normalized(expected_changes) == normalized(produced_changes)


def compare(pred_rows: dict[str, OutputRow], samples: list[SampleRequest]) -> EvaluationReport:
    """Field-by-field comparison of predictions against solved sample answers."""
    report = EvaluationReport(total=len(samples))
    report.field_matches = {label: 0 for label in FIELD_LABELS}
    for sample in samples:
        rid = sample.request.request_id
        produced = pred_rows.get(rid)
        diff = RowDiff(request_id=rid)
        if produced is None:
            for label in FIELD_LABELS:
                diff.mismatched_fields[label] = {"expected": "present", "produced": "missing row"}
            report.diffs.append(diff)
            continue
        if produced.amount_safe_to_pay == sample.amount_safe_to_pay:
            report.field_matches["amount_safe_to_pay"] += 1
        else:
            diff.mismatched_fields["amount_safe_to_pay"] = {
                "expected": format(sample.amount_safe_to_pay, "f"),
                "produced": format(produced.amount_safe_to_pay, "f")}
        if produced.affordability_status == sample.affordability_status:
            report.field_matches["affordability_status"] += 1
        else:
            diff.mismatched_fields["affordability_status"] = {
                "expected": sample.affordability_status.value,
                "produced": produced.affordability_status.value}
        if produced.recommended_payment_method == sample.recommended_payment_method:
            report.field_matches["recommended_payment_method"] += 1
        else:
            diff.mismatched_fields["recommended_payment_method"] = {
                "expected": sample.recommended_payment_method.value,
                "produced": produced.recommended_payment_method.value}
        if _plan_equal(sample.payment_plan, produced.payment_plan):
            report.field_matches["payment_plan"] += 1
        else:
            diff.mismatched_fields["payment_plan"] = {
                "expected": sample.payment_plan, "produced": produced.payment_plan}
        if produced.earliest_date_for_full_payment == sample.earliest_date_for_full_payment:
            report.field_matches["earliest_date_for_full_payment"] += 1
        else:
            diff.mismatched_fields["earliest_date_for_full_payment"] = {
                "expected": sample.earliest_date_for_full_payment.isoformat()
                            if sample.earliest_date_for_full_payment else "",
                "produced": produced.earliest_date_for_full_payment.isoformat()
                            if produced.earliest_date_for_full_payment else ""}
        if _changes_equal(sample.spending_changes_needed, produced.spending_changes_needed):
            report.field_matches["spending_changes_needed"] += 1
        else:
            diff.mismatched_fields["spending_changes_needed"] = {
                "expected": sample.spending_changes_needed,
                "produced": produced.spending_changes_needed}
        # decision_explanation: presence/consistency only (no string matching)
        if produced.decision_explanation.strip():
            report.field_matches["decision_explanation"] += 1
        else:
            diff.mismatched_fields["decision_explanation"] = {
                "expected": "non-empty", "produced": "empty"}
        if diff.mismatched_fields:
            report.diffs.append(diff)
    return report


def run_selfcheck() -> EvaluationReport:
    """Evaluate the solved samples against themselves; must be 25/25 everywhere."""
    samples = load_sample_requests()
    rows = {s.request.request_id: sample_to_output_row(s) for s in samples}
    return compare(rows, samples)


def _print_report(report: EvaluationReport) -> None:
    print("\n".join(report.summary_lines()))
    for diff in report.diffs:
        print(f"\n[{diff.request_id}]")
        for label, detail in diff.mismatched_fields.items():
            print(f"  {label}: expected={detail['expected']!r} produced={detail['produced']!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="25-sample regression evaluator (self-check mode)")
    parser.add_argument("--selfcheck", action="store_true",
                        help="evaluate the solved sample answers against themselves")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write machine-readable results to this path")
    args = parser.parse_args(argv)

    if not args.selfcheck:
        parser.print_help()
        print("\n(note: algorithm evaluation mode arrives with the finance engine; "
              "only --selfcheck exists in Phase 1)")
        return 2

    report = run_selfcheck()
    _print_report(report)
    if args.json is not None:
        payload = {
            "total": report.total,
            "field_matches": report.field_matches,
            "diffs": [{"request_id": d.request_id,
                       "fields": d.mismatched_fields} for d in report.diffs],
        }
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON results written to {args.json}")
    perfect = report.is_perfect()
    print(f"\nSELF-CHECK {'PASS (25/25 on all fields)' if perfect else 'FAIL'}")
    return 0 if perfect else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
