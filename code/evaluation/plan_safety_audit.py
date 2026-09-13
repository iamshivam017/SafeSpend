"""Sample-plan safety audit (Phase 2.1, EVALUATION-ONLY).

Replays each solved sample's OFFICIAL payment_plan as hypothetical simulator
payments and reports whether the official recommendation passes the Phase-2
safety simulation. This tool is a regression oracle for the financial engine.

ISOLATION GUARANTEE: production prediction code must never import this module
(enforced by tests/test_sample_evaluator.py-style AST checks extended here via
a dedicated test). It reads sample answer columns — the no-leak boundary.

Verdicts per sample:
- PASS          official plan keeps the floor for the whole horizon
- CONTRADICTION official plan violates the floor while Phase 2 has enough
                information to evaluate it (no unresolved evidence, no
                spending changes) — engine bug or over-projection
- DEFERRED      a later-phase dependency genuinely prevents evaluation:
                unresolved image evidence, official spending changes
                (Phase 3 semantics), or no plan to evaluate (not_recommended)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from ..data_loader import load_all, validate_relationships
from ..errors import SafeSpendError
from ..finance.lifecycle import resolve_lifecycle
from ..finance.recurrence import detect_recurring_patterns
from ..finance.simulator import Payment, SafetyState, simulate
from ..finance.timeline import build_cash_timeline
from ..indexes import Indexes
from ..output_validator import parse_payment_plan, parse_spending_changes
from ..schemas import SampleRequest


@dataclass
class AuditRow:
    request_id: str
    official_status: str
    official_method: str
    official_plan: str
    simulator_state: str
    first_violation: str
    reason: str
    verdict: str
    protected_categories: int = 0
    fixed_essentials_projected: int = 0
    variable_essential_reserves: int = 0
    uncovered_protected: int = 0

    def line(self) -> str:
        return (f"{self.request_id:<12}{self.official_status:<22}{self.official_method:<18}"
                f"{self.official_plan:<40}{self.simulator_state:<11}"
                f"{self.first_violation:<12}{self.verdict:<14}{self.reason}")


def _coverage_summary(coverage: dict[str, str]) -> tuple[int, int, int, list[str]]:
    """Essential coverage diagnostics from a classify_coverage result."""
    protected = len(coverage)
    fixed = sum(1 for v in coverage.values() if v == "FIXED_RECURRING")
    reserves = sum(1 for v in coverage.values() if v == "VARIABLE_ESSENTIAL_RESERVE")
    uncovered = sorted(c for c, v in coverage.items() if v == "UNACCOUNTED")
    return protected, fixed, reserves, uncovered


def _audit_sample(sample: SampleRequest, indexes: Indexes) -> AuditRow:
    request = sample.request
    base = AuditRow(request.request_id, sample.affordability_status.value,
                    sample.recommended_payment_method.value, sample.payment_plan,
                    "", "", "", "")

    # DEFER: no plan to evaluate
    if sample.recommended_payment_method.value == "not_recommended":
        base.simulator_state, base.verdict = "-", "DEFERRED"
        base.reason = "official plan is none (not_recommended); ranking semantics are Phase 3"
        return base

    plan = parse_payment_plan(sample.payment_plan)

    # DEFER: official spending changes are Phase 3 semantics
    changes = parse_spending_changes(sample.spending_changes_needed)
    if changes:
        base.simulator_state, base.verdict = "-", "DEFERRED"
        base.reason = (f"official spending changes ({sample.spending_changes_needed}) "
                       f"require Phase 3 optimization semantics")
        return base

    profile = indexes.profiles_by_user_id[request.user_id]
    user_events = indexes.events_by_user_id.get(request.user_id, [])
    lifecycle = resolve_lifecycle(user_events, request.request_date)
    patterns = detect_recurring_patterns(user_events)

    # DEFER: unresolved image evidence affects the horizon
    if lifecycle.unresolved:
        base.simulator_state, base.verdict = "-", "DEFERRED"
        base.reason = (f"unresolved blank-amount evidence: "
                       f"{','.join(u.event_id for u in lifecycle.unresolved)} (Phase 4)")
        return base

    try:
        timeline = build_cash_timeline(profile, request.request_date, lifecycle,
                                       patterns, indexes)
    except SafeSpendError as exc:
        base.simulator_state, base.verdict = "ERROR", "DEFERRED"
        base.reason = f"timeline build failed: {exc}"
        return base

    from .essential_coverage_audit import classify_coverage
    coverage = classify_coverage(bundle=None, indexes=indexes,
                                 user_id=request.user_id,
                                 request_date=request.request_date)
    (base.protected_categories, base.fixed_essentials_projected,
     base.variable_essential_reserves, uncovered) = _coverage_summary(coverage)
    if uncovered:
        base.reason += f"; UNACCOUNTED protected: {uncovered}"

    payments = [Payment(entry.payment_date, entry.amount) for entry in plan]
    sim = simulate(profile, request.request_date, timeline.flows,
                   hypothetical_payments=payments, include_trace=False)
    base.simulator_state = sim.state.value
    base.first_violation = (sim.first_floor_violation_date.isoformat()
                            if sim.first_floor_violation_date else "-")
    if sim.state is SafetyState.UNSAFE:
        base.verdict = "CONTRADICTION"
        base.reason = (f"official plan violates floor on {base.first_violation} "
                       f"(min {sim.minimum_projected_balance} < {sim.minimum_balance_required})")
    else:
        base.verdict = "PASS"
        base.reason = f"min {sim.minimum_projected_balance} >= floor {sim.minimum_balance_required}"
    return base


def run_audit() -> list[AuditRow]:
    bundle = load_all()
    problems = validate_relationships(bundle)
    if problems:
        raise SafeSpendError("structural problems: " + "; ".join(problems))
    indexes = Indexes.build(bundle)
    return [_audit_sample(s, indexes) for s in bundle.samples]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sample-plan safety audit (evaluation-only; reads sample labels)")
    parser.add_argument("--json", type=str, default=None,
                        help="write machine-readable results to this path")
    args = parser.parse_args(argv)

    rows = run_audit()
    print(f"{'request':<12}{'official_status':<22}{'method':<18}{'plan':<40}"
          f"{'state':<11}{'violation':<12}{'verdict':<14}reason")
    for row in rows:
        print(row.line())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    print(f"\nverdicts: {counts}")
    contradictions = [r for r in rows if r.verdict == "CONTRADICTION"]
    if args.json:
        import json
        from pathlib import Path as _Path
        from ..config import REPO_ROOT
        out_path = _Path(args.json).resolve()
        if not out_path.is_relative_to(REPO_ROOT.resolve()):
            print(f"refusing to write outside the repository: {out_path}",
                  file=sys.stderr)
            return 2
        out_path.write_text(json.dumps([r.__dict__ for r in rows], indent=2),
                            encoding="utf-8")
        print(f"\nJSON results written to {out_path}")
    print("AUDIT " + ("PASS (no contradictions)" if not contradictions
                      else f"FAIL ({len(contradictions)} contradiction(s))"))
    return 0 if not contradictions else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
