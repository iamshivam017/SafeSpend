"""Phase 5 calibration harness (EVALUATION-ONLY).

Compares generalized reserve-policy variants over the 25 solved samples:
  scope:      protected | all
  occurrences: 1 | 2 | 3
  statistic:  median | max | trailing

Reports per-variant field-level exact counts and plan-safety contradictions.
Production code is untouched; variants are applied by temporarily overriding
module defaults (restored after each variant). Sample labels never enter
production code.
"""
from __future__ import annotations

import sys
from collections import Counter
from decimal import Decimal

from ..data_loader import load_all
from ..evidence.apply import collect_claims
from ..finance import recurrence as rec
from ..indexes import Indexes
from ..output_validator import parse_payment_plan, parse_spending_changes
from ..planning.planner import plan_for_request


def _sample_scores(bundle, indexes, claims) -> dict:
    matches = Counter({f: 0 for f in ("asp", "status", "method", "plan",
                                      "earliest", "changes", "all_six")})
    contradictions = 0
    for sample in bundle.samples:
        request = sample.request
        try:
            decision, _ = plan_for_request(bundle, indexes, request, claims)
        except Exception:
            matches["errors"] += 1
            continue
        plan_ok = None
        produced_plan = None if decision.payment_plan is None else \
            [(p.payment_date, p.amount) for p in decision.payment_plan]
        official_plan = parse_payment_plan(sample.payment_plan)
        official_plan = None if official_plan is None else \
            [(e.payment_date, e.amount) for e in official_plan]
        plan_ok = produced_plan == official_plan
        changes_ok = ([(c.action, c.event_id, c.new_amount) for c in decision.spending_changes]
                      == [(c.action, c.event_id, c.new_amount)
                          for c in parse_spending_changes(sample.spending_changes_needed)])
        asp_ok = decision.amount_safe_to_pay == sample.amount_safe_to_pay
        status_ok = decision.affordability_status.value == sample.affordability_status.value
        method_ok = decision.recommended_payment_method.value == sample.recommended_payment_method.value
        earliest_ok = (decision.earliest_date_for_full_payment
                       == sample.earliest_date_for_full_payment)
        for flag, ok in (("asp", asp_ok), ("status", status_ok), ("method", method_ok),
                         ("plan", plan_ok), ("earliest", earliest_ok),
                         ("changes", changes_ok)):
            if ok:
                matches[flag] += 1
        if asp_ok and status_ok and method_ok and plan_ok and earliest_ok and changes_ok:
            matches["all_six"] += 1
        # plan-safety contradiction check (official plan must be SAFE)
        if decision.selected_candidate is None and sample.recommended_payment_method.value != "not_recommended":
            contradictions += 1
    return {"matches": dict(matches), "contradictions": contradictions}


def run_variants() -> dict:
    bundle = load_all()
    indexes = Indexes.build(bundle)
    claims = collect_claims(bundle)
    results = {}
    import itertools
    for scope, occ, stat in itertools.product(
            ("protected", "all"), (1, 2, 3), ("median", "max", "trailing")):
        name = f"scope={scope} occ={occ} stat={stat}"
        saved = rec.DEFAULT_PROVISION_PARAMS
        try:
            rec.DEFAULT_PROVISION_PARAMS = rec.ProvisionParams(
                scope=scope, occurrences=occ, statistic=stat)
            # plan-safety contradictions for the 15 originally-passing samples
            contradictions = 0
            scores = {"asp": 0, "status": 0, "method": 0, "plan": 0,
                      "earliest": 0, "changes": 0, "all_six": 0}
            for sample in bundle.samples:
                request = sample.request
                try:
                    decision, _ = plan_for_request(bundle, indexes, request, claims)
                except Exception:
                    contradictions += 1
                    continue
                produced_plan = None if decision.payment_plan is None else \
                    [(p.payment_date, p.amount) for p in decision.payment_plan]
                official_plan = parse_payment_plan(sample.payment_plan)
                official_plan = None if official_plan is None else \
                    [(e.payment_date, e.amount) for e in official_plan]
                if sample.recommended_payment_method.value != "not_recommended" \
                        and decision.recommended_payment_method.value == "not_recommended" \
                        and decision.baseline.baseline_state.value == "safe":
                    contradictions += 1
                if decision.amount_safe_to_pay == sample.amount_safe_to_pay:
                    scores["asp"] += 1
                if decision.affordability_status.value == sample.affordability_status.value:
                    scores["status"] += 1
                if decision.recommended_payment_method.value == sample.recommended_payment_method.value:
                    scores["method"] += 1
                if produced_plan == official_plan:
                    scores["plan"] += 1
                if decision.earliest_date_for_full_payment == sample.earliest_date_for_full_payment:
                    scores["earliest"] += 1
                if ([(c.action, c.event_id, c.new_amount) for c in decision.spending_changes]
                        == [(c.action, c.event_id, c.new_amount)
                            for c in parse_spending_changes(sample.spending_changes_needed)]):
                    scores["changes"] += 1
            results[name] = {"scores": scores, "contradictions": contradictions}
        finally:
            rec.DEFAULT_PROVISION_PARAMS = saved
    return results


def main() -> int:
    results = run_variants()
    for name, r in sorted(results.items(), key=lambda kv: -kv[1]["scores"]["status"]):
        s = r["scores"]
        print(f"{name:<28} asp={s['asp']:>2} status={s['status']:>2} method={s['method']:>2} "
              f"plan={s['plan']:>2} earliest={s['earliest']:>2} changes={s['changes']:>2} "
              f"contradictions={r['contradictions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
