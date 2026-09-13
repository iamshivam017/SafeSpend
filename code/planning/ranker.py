"""Official candidate ranking (Phase 3).

Official order, implemented exactly (problem_statement.md "Choosing Between
Safe Plans"):
  1. Complete the full request by desired_completion_date
  2. Require no spending changes
  3. Minimize the total amount paid
  4. Start payment earlier
  5. Use fewer payments
  6. Lowest payment_option_id as the final tie-break

An internal canonicalization (fewer changes -> smaller intervention ->
lexicographic actions) applies ONLY after all six official keys are equal;
it is an ENGINEERING DECISION and never overrides an official criterion.

Only SAFE, method-eligible, deadline-completing candidates may be ranked;
UNRESOLVED/UNSAFE candidates and non-eligible methods can never win.
"""
from __future__ import annotations

from decimal import Decimal

from .models import ChangeAction, Method, PaymentCandidate


def _intervention_total(changes: tuple) -> Decimal:
    total = Decimal("0")
    for c in changes:
        if c.action == "reduce_to" and c.new_amount is not None:
            total += c.new_amount
    return total


def rank_key(candidate: PaymentCandidate) -> tuple:
    option_id = candidate.payment_option_id or "~~~~"  # sorts after any real id
    return (
        0 if candidate.completes_by_deadline else 1,          # official 1
        0 if not candidate.uses_spending_changes else 1,      # official 2
        candidate.total_paid,                                 # official 3
        candidate.first_payment_date,                         # official 4
        candidate.payment_count,                              # official 5
        option_id,                                            # official 6
        # internal canonicalization (engineering decision, after all official keys)
        len(candidate.changes),
        _intervention_total(candidate.changes),
        tuple(sorted(f"{c.action}:{c.event_id}" for c in candidate.changes)),
    )


def rank_candidates(candidates: list[PaymentCandidate]) -> list[PaymentCandidate]:
    """Filter to recommendable candidates and order by the official ranking."""
    recommendable = [c for c in candidates
                     if c.rejection_reason is None
                     and c.sim_state is not None
                     and c.sim_state.value == "safe"
                     and c.completes_by_deadline]
    return sorted(recommendable, key=rank_key)


def select_best(candidates: list[PaymentCandidate]) -> PaymentCandidate | None:
    ranked = rank_candidates(candidates)
    return ranked[0] if ranked else None


def best_candidate_for_method(candidates: list[PaymentCandidate],
                              method: Method) -> PaymentCandidate | None:
    """Best recommendable candidate of one method (diagnostics/decision use)."""
    ranked = [c for c in rank_candidates(candidates) if c.method is method]
    return ranked[0] if ranked else None
