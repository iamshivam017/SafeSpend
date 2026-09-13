"""Top-level planner orchestrator: request -> Decision (Phase 3)."""
from __future__ import annotations

from ..evidence.apply import build_request_state
from ..evidence.claims import EvidenceClaim
from ..finance.recurrence import classify_pattern
from ..finance.timeline import horizon_end
from ..output_validator import PlanEntry
from .decision import Decision, explanation_facts, plan_request
from .spending_changes import enumerate_actions

__all__ = ["plan_for_request", "Decision", "explanation_facts"]


def plan_for_request(bundle, indexes, request, all_claims: list[EvidenceClaim] | None = None
                     ) -> tuple[Decision, dict]:
    """Evidence-aware planning for one request. Deterministic; no AI."""
    profile, lifecycle, patterns, timeline, evidence, unresolved = \
        build_request_state(bundle, indexes, request, all_claims=all_claims)
    user_events = indexes.events_by_user_id.get(request.user_id, [])
    options = indexes.options_by_request_id.get(request.request_id, [])
    profile_obj = indexes.profiles_by_user_id[request.user_id]

    projected_keys = {(f.category, f.direction_value) for f in timeline.flows
                      if f.basis in ("recurring_projection", "essential_provision")}
    projected_debit_patterns = []
    source_events_by_pattern: dict[int, list] = {}
    for pattern in patterns:
        key = (pattern.category, pattern.direction.value)
        source = [e for e in user_events if e.event_id in pattern.source_event_ids]
        is_projected = key in projected_keys
        is_reserve = any(f.category == pattern.category and f.basis == "essential_provision"
                         for f in timeline.flows)
        if (is_projected or is_reserve) and pattern.direction.value == "debit":
            fc = classify_pattern(pattern, source,
                                  set(profile_obj.expense_categories_to_protect))
            if fc == "fixed_commitment" or is_reserve:
                projected_debit_patterns.append(pattern)
                source_events_by_pattern[id(pattern)] = source

    actions = enumerate_actions(projected_debit_patterns, source_events_by_pattern,
                                profile_obj)
    # material = debit-class unresolved evidence INSIDE this request's horizon
    # (same filter the simulator applies; credits and out-of-horizon items are
    # never material) - keeps compute_baseline and simulate consistent
    end = horizon_end(request.request_date)
    unresolved_material = any(
        u.direction.value == "debit"
        and request.request_date <= u.effective_date <= end
        for u in unresolved)
    baseline = compute_baseline_for(profile_obj, request.request_date,
                                    timeline.flows, request.requested_amount,
                                    unresolved_material=unresolved_material)
    decision = plan_request(profile_obj, request, timeline.flows, options,
                            baseline, actions, profile_obj.max_installment_months,
                            unresolved=unresolved)
    facts = explanation_facts(decision)
    facts["evidence_diagnostics"] = list(evidence.diagnostics)
    facts["unresolved"] = [f"{u.event_id}:{u.category}" for u in unresolved]
    return decision, facts


def compute_baseline_for(profile, request_date, flows, requested_amount,
                         unresolved_material: bool):
    from .baseline import compute_baseline
    return compute_baseline(profile, request_date, flows, requested_amount,
                            unresolved_material)
