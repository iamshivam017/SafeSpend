"""SafeSpend entry point (Phase 1: data foundation skeleton).

Phase 1 scope: load every participant dataset, build indexes, run structural
relationship validation, and report. It does NOT fabricate predictions and does
NOT write output.csv — the prediction engine arrives in later phases
(docs/09 roadmap). `--selfcheck` exercises the 25-sample regression harness.

Run from the repository root:
    python code/main.py
    python code/main.py --selfcheck
    python code/main.py --diagnose
    python code/main.py --plan        # Phase 3 dry-run: plan 250 requests, no output.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # executed as a script: make the repo root importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from code.data_loader import load_all, validate_relationships  # noqa: E402
from code.indexes import Indexes  # noqa: E402
from code.errors import SafeSpendError  # noqa: E402


def _run_foundation() -> int:
    bundle = load_all()
    print("Loaded participant datasets:")
    print(f"  requests.csv              {len(bundle.requests):>6} evaluation requests")
    print(f"  sample_requests.csv       {len(bundle.samples):>6} solved samples")
    print(f"  financial_profiles.csv    {len(bundle.profiles):>6} profiles")
    print(f"  financial_events.csv      {len(bundle.events):>6} events")
    blank_amounts = sum(1 for e in bundle.events if e.amount is None)
    print(f"    - blank amounts         {blank_amounts:>6} (officially valid; tracked for "
          f"image resolution, never zero-filled)")
    print(f"  request_payment_options   {len(bundle.options):>6} options")
    print(f"  exchange_rates.csv        {len(bundle.rates):>6} rates")
    print(f"  messages.csv              {len(bundle.messages):>6} messages")
    print(f"  images.csv                {len(bundle.images):>6} image references "
          f"({sum(1 for im in bundle.images if im.file_exists)} files present)")

    problems = validate_relationships(bundle)
    if problems:
        print("\nStructural relationship problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nStructural relationship validation: PASS")
    print("Phase 1 foundation OK. (No predictions are generated yet — the finance "
          "engine is built in later phases.)")
    return 0


def _run_diagnose() -> int:
    """Phase 2 diagnostic: run the financial engine over the 25 sample users.

    Produces deterministic baseline traces (no output labels are read).
    """
    from code.finance.lifecycle import resolve_lifecycle
    from code.finance.recurrence import detect_recurring_patterns
    from code.finance.simulator import simulate
    from code.finance.timeline import build_cash_timeline

    bundle = load_all()
    problems = validate_relationships(bundle)
    if problems:
        print("Structural problems:", *problems, sep="\n  ")
        return 1
    indexes = Indexes.build(bundle)
    print("Phase 2 baseline diagnostics over the 25 sample users "
          "(no hypothetical payments; labels not read):\n")
    print(f"{'request':<12}{'user':<10}{'state':<11}{'min_proj':>16}{'floor':>14}"
          f"{'flows':>7}{'patterns':>9}{'unres':>6}")
    from code.evidence.apply import build_request_state
    all_claims = None
    for sample in bundle.samples:
        request = sample.request
        try:
            profile, lifecycle, patterns, timeline, evidence, unresolved =                 build_request_state(bundle, indexes, request, all_claims)
        except SafeSpendError as exc:
            print(f"{request.request_id:<12}{request.user_id:<10}ERROR: {exc}")
            continue
        sim = simulate(profile, request.request_date, timeline.flows,
                       unresolved_evidence=unresolved, include_trace=False)
        print(f"{request.request_id:<12}{request.user_id:<10}{sim.state.value:<11}"
              f"{sim.minimum_projected_balance:>16}{sim.minimum_balance_required:>14}"
              f"{len(timeline.flows):>7}{len(patterns):>9}{len(unresolved):>6}")
    return 0


def _run_plan() -> int:
    """Phase 3 dry-run: plan every request without writing output.csv."""
    from collections import Counter
    from code.evidence.apply import collect_claims, build_request_state
    from code.evidence.claims import EvidenceClaim
    from code.planning.planner import plan_for_request
    import time

    bundle = load_all()
    problems = validate_relationships(bundle)
    if problems:
        print("Structural problems:")
        for problem in problems:
            print("  -", problem)
        return 1
    indexes = Indexes.build(bundle)
    claims = collect_claims(bundle)
    t0 = time.perf_counter()
    statuses: Counter = Counter()
    methods: Counter = Counter()
    planned = 0
    for request in bundle.requests:
        try:
            decision, _facts = plan_for_request(bundle, indexes, request, claims)
        except SafeSpendError as exc:
            print(f"{request.request_id}: ERROR {exc}")
            continue
        planned += 1
        statuses[decision.affordability_status.value] += 1
        methods[decision.recommended_payment_method.value] += 1
    elapsed = time.perf_counter() - t0
    print(f"planned {planned}/{len(bundle.requests)} requests in {elapsed:.2f}s "
          f"(dry run; no output.csv written)")
    print(f"statuses: {dict(statuses)}")
    print(f"methods:  {dict(methods)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selfcheck" in argv:
        from code.evaluation.sample_evaluator import main as evaluator_main
        return evaluator_main(["--selfcheck"])
    if "--diagnose" in argv:
        return _run_diagnose()
    if "--plan" in argv:
        return _run_plan()
    try:
        return _run_foundation()
    except SafeSpendError as exc:
        print(f"FOUNDATION ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
