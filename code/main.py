"""SafeSpend entry point (Phase 1: data foundation skeleton).

Phase 1 scope: load every participant dataset, build indexes, run structural
relationship validation, and report. It does NOT fabricate predictions and does
NOT write output.csv — the prediction engine arrives in later phases
(docs/09 roadmap). `--selfcheck` exercises the 25-sample regression harness.

Run from the repository root:
    python code/main.py
    python code/main.py --selfcheck
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):  # executed as a script: make the repo root importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from code.data_loader import load_all, validate_relationships  # noqa: E402
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selfcheck" in argv:
        from code.evaluation.sample_evaluator import main as evaluator_main
        return evaluator_main(["--selfcheck"])
    try:
        return _run_foundation()
    except SafeSpendError as exc:
        print(f"FOUNDATION ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
