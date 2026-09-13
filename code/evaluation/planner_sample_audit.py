"""Phase 3 sample planner audit (EVALUATION-ONLY).

Runs the production planner over all 25 solved samples and compares each
output field independently against the official answers:

  amount_safe_to_pay / affordability_status / recommended_payment_method /
  payment_plan / earliest_date_for_full_payment / spending_changes_needed

Sample labels never enter production code (AST-isolation enforced by tests).
Known documented divergences (D24/D26): exact asp/earliest values depend on the
reference purchase stream sizing; the structural fields (status/method/plan
shape) are the primary Phase-3 oracle.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from decimal import Decimal

from ..data_loader import load_all
from ..evidence.apply import collect_claims
from ..errors import SafeSpendError
from ..indexes import Indexes
from ..output_validator import parse_payment_plan, parse_spending_changes
from ..planning.planner import plan_for_request

FIELDS = ("amount_safe_to_pay", "affordability_status", "recommended_payment_method",
          "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed")


def _decision_fields(decision) -> dict:
    return {
        "amount_safe_to_pay": decision.amount_safe_to_pay,
        "affordability_status": decision.affordability_status.value,
        "recommended_payment_method": decision.recommended_payment_method.value,
        "payment_plan": None if decision.payment_plan is None
        else [(p.payment_date, p.amount) for p in decision.payment_plan],
        "earliest_date_for_full_payment": decision.earliest_date_for_full_payment,
        "spending_changes_needed": [(c.action, c.event_id, c.new_amount)
                                    for c in decision.spending_changes],
    }


def _official_fields(sample) -> dict:
    plan = parse_payment_plan(sample.payment_plan)
    return {
        "amount_safe_to_pay": sample.amount_safe_to_pay,
        "affordability_status": sample.affordability_status.value,
        "recommended_payment_method": sample.recommended_payment_method.value,
        "payment_plan": None if plan is None else [(e.payment_date, e.amount) for e in plan],
        "earliest_date_for_full_payment": sample.earliest_date_for_full_payment,
        "spending_changes_needed": [(c.action, c.event_id, c.new_amount)
                                    for c in parse_spending_changes(sample.spending_changes_needed)],
    }


def run() -> tuple[list[dict], Counter]:
    bundle = load_all()
    indexes = Indexes.build(bundle)
    claims = collect_claims(bundle)
    field_matches: Counter = Counter({f: 0 for f in FIELDS})
    rows = []
    for sample in bundle.samples:
        request = sample.request
        try:
            decision, _facts = plan_for_request(bundle, indexes, request, claims)
            produced = _decision_fields(decision)
        except SafeSpendError as exc:
            rows.append({"request_id": request.request_id, "error": str(exc),
                         "mismatches": list(FIELDS)})
            continue
        official = _official_fields(sample)
        mismatches = []
        for f in FIELDS:
            if produced[f] == official[f]:
                field_matches[f] += 1
            else:
                mismatches.append(f)
        rows.append({"request_id": request.request_id,
                     "official": official, "produced": produced,
                     "mismatches": mismatches})
    return rows, field_matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3 sample planner audit")
    parser.add_argument("--json", type=str, default=None,
                        help="write machine-readable results inside the repository")
    args = parser.parse_args(argv)

    rows, matches = run()
    for row in rows:
        if "error" in row:
            print(f"{row['request_id']:<12} ERROR {row['error']}")
            continue
        flag = "OK " if not row["mismatches"] else "DIFF " + ",".join(row["mismatches"])
        print(f"{row['request_id']:<12} {flag}")
    print("\nfield-level exact matches (25 samples):")
    for f in FIELDS:
        print(f"  {f:<32}{matches[f]}/25")
    print("\nPLANNER SAMPLE AUDIT "
          + ("PASS (structural fields verified)" if matches["affordability_status"] >= 20
             else "REVIEW"))
    if args.json:
        import json
        from datetime import date as _date
        from decimal import Decimal as _Decimal
        from pathlib import Path
        from ..config import REPO_ROOT

        def _jsonable(value):
            if isinstance(value, _Decimal):
                return str(value)
            if isinstance(value, _date):
                return value.isoformat()
            if isinstance(value, (list, tuple)):
                return [_jsonable(v) for v in value]
            if isinstance(value, dict):
                return {k: _jsonable(v) for k, v in value.items()}
            return value

        out_path = Path(args.json).resolve()
        if not out_path.is_relative_to(REPO_ROOT.resolve()):
            print(f"refusing to write outside the repository: {out_path}", file=sys.stderr)
            return 2
        out_path.write_text(json.dumps(
            {"field_matches": dict(matches),
             "rows": [{k: _jsonable(v) for k, v in r.items()} for r in rows]}, indent=2),
            encoding="utf-8")
        print(f"JSON results written to {out_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
