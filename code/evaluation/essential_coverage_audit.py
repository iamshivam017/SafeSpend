"""Protected-essential coverage audit (Phase 2.2, EVALUATION-ONLY).

For every user (all 275) and every PROTECTED category from their profile with
recent spending history, classify the forward treatment the Phase-2 engine
gives it:

- FIXED_RECURRING            projected as dated recurring events
- VARIABLE_ESSENTIAL_RESERVE covered by the aggregate conservative provision
- UNRESOLVED                 blank-amount evidence pending (Phase 4)
- NO_FUTURE_EVIDENCE         history below the evidence gate (documented policy:
                             insufficient evidence to forecast)
- UNACCOUNTED                meaningful recent protected spending (meets the
                             evidence gate) yet neither projected nor
                             provisioned — an engine gap; acceptance target 0

ISOLATION: evaluation-only; production code must never import it.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import timedelta

from ..data_loader import load_all, validate_relationships
from ..errors import SafeSpendError
from ..finance.lifecycle import resolve_lifecycle
from ..finance.recurrence import (detect_recurring_patterns, essential_provisions,
                                  project_occurrences)
from ..indexes import Indexes
from ..schemas import Request


def _request_date_for(user_id: str, bundle) -> object | None:
    for r in bundle.requests:
        if r.user_id == user_id:
            return r.request_date
    for s in bundle.samples:
        if s.request.user_id == user_id:
            return s.request.request_date
    return None


def classify_coverage(bundle, indexes: Indexes, user_id: str, request_date,
                      all_claims=None):
    """Return {protected_category: classification} for one user (evidence-aware)."""
    from ..evidence.apply import build_user_evidence
    profile = indexes.profiles_by_user_id[user_id]
    user_events = indexes.events_by_user_id.get(user_id, [])
    evidence = build_user_evidence(user_id, request_date,
                                   all_claims if all_claims is not None else [],
                                   user_events)
    lifecycle = resolve_lifecycle(user_events, request_date,
                                  resolved_amounts=evidence.resolved_amounts)
    patterns = detect_recurring_patterns(user_events)
    projected, _ = project_occurrences(
        patterns, request_date, request_date + timedelta(days=90),
        lifecycle.cash_events, source_events=user_events,
        protected_categories=set(profile.expense_categories_to_protect))
    fixed_keys = {(c.category, "debit") for c in projected}
    provisions = essential_provisions(
        user_events, set(profile.expense_categories_to_protect),
        request_date, patterns, projected_fixed_keys=fixed_keys)
    provision_keys = {c.category for c in provisions}
    unresolved_keys = {u.category for u in lifecycle.unresolved
                       if u.direction.value == "debit"}
    unresolved_keys.update(u.category for u in evidence.extra_unresolved)

    horizon_end = request_date + timedelta(days=90)
    result = {}
    for category in profile.expense_categories_to_protect:
        recent = [e for e in user_events
                  if e.category == category and e.direction.value == "debit"
                  and e.status.value in ("settled", "scheduled", "pending")
                  and request_date - timedelta(days=90) <= e.event_date <= horizon_end]
        if (category, "debit") in fixed_keys and category not in unresolved_keys:
            result[category] = "FIXED_RECURRING"
        elif category in unresolved_keys:
            result[category] = "UNRESOLVED"
        elif category in provision_keys:
            result[category] = "VARIABLE_ESSENTIAL_RESERVE"
        elif len(recent) >= 6:
            result[category] = "UNACCOUNTED"
        else:
            result[category] = "NO_FUTURE_EVIDENCE"
    return result


def run_coverage() -> tuple[Counter, list[str], int]:
    bundle = load_all()
    problems = validate_relationships(bundle)
    if problems:
        raise SafeSpendError("structural problems: " + "; ".join(problems))
    indexes = Indexes.build(bundle)
    from ..evidence.apply import collect_claims
    all_claims = collect_claims(bundle)
    counts: Counter = Counter()
    unaccounted: list[str] = []
    for user_id in sorted(indexes.profiles_by_user_id):
        request_date = _request_date_for(user_id, bundle)
        if request_date is None:
            continue  # profile without any request (no forecast context)
        for category, classification in classify_coverage(
                bundle, indexes, user_id, request_date,
                all_claims=all_claims).items():
            counts[classification] += 1
            if classification == "UNACCOUNTED":
                unaccounted.append(f"{user_id}/{category}")
    return counts, unaccounted, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Protected-essential coverage audit across all users")
    args = parser.parse_args(argv)
    counts, unaccounted, _users = run_coverage()
    print("protected-category forward-treatment coverage (all users):")
    for key in ("FIXED_RECURRING", "VARIABLE_ESSENTIAL_RESERVE", "UNRESOLVED",
                "NO_FUTURE_EVIDENCE", "UNACCOUNTED"):
        print(f"  {key:<28}{counts.get(key, 0)}")
    if unaccounted:
        print(f"\nUNACCOUNTED ({len(unaccounted)}):")
        for entry in unaccounted:
            print(f"  - {entry}")
    print("\nCOVERAGE " + ("PASS (UNACCOUNTED = 0)" if not unaccounted
                           else f"FAIL ({len(unaccounted)} unaccounted)"))
    return 0 if not unaccounted else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
