# SafeSpend — Buy or Wait?

HackerRank Orchestrate September 2026 — Deterministic financial decision agent.

## What This Solution Does

For every purchase/payment request in `dataset/requests.csv`, the agent determines:

- **amount_safe_to_pay** — the maximum provably safe payment today
- **affordability_status** — affordable_now / affordable_with_plan / affordable_later / not_affordable
- **recommended_payment_method** — full_payment / partial_payment / installments / wait / not_recommended
- **payment_plan** — chronological payment schedule
- **earliest_date_for_full_payment** — first date the full amount is safe as one payment
- **spending_changes_needed** — optional stop/reduce actions on flexible expenses
- **decision_explanation** — grounded explanation of the recommendation

## Architecture

```
participant data (CSV)
  → typed loaders (fail-fast, Decimal money)
  → deterministic evidence layer (EN/ID message parser + image cache)
  → lifecycle resolution (conflict precedence, dedup, FX)
  → recurrence detection (gap-bucket cadence + day-of-month clustering)
  → 90-day cash-flow simulator (EOD floor checks)
  → planner (ASP / earliest / candidates / spending changes)
  → official ranker (6-key, exact order)
  → Decision → output validator → output.csv
```

## Why Financial Decisions Are Deterministic

All financial policy — ASP, earliest date, candidate generation, ranking, status mapping — is implemented in pure Python using `Decimal` arithmetic. No AI/LLM/VLM participates in any financial decision. Message and image content are treated as untrusted data: only whitelisted claim types are extracted, and free-form text can never alter challenge rules.

## How Messages Are Handled

A deterministic EN/ID regex parser (`code/evidence/message_parser.py`) converts formulaic payroll/bank/provider notices into typed claims (salary confirmed/changed/resumed/ended, payment delayed, recurring expense started). Only whitelisted templates produce claims; everything else is recorded as informational. Embedded instructions are flagged and ignored.

## How Image-Derived Blank Amounts Are Handled

When a financial event has a blank amount, the engine looks up the linked image via `images.csv`. The image amount was transcribed during development (agent-assisted vision) into a validated, provenance-preserving cache (`code/evidence/cache.json`). At runtime, the cached amount is loaded and used — never zero. If no image exists or extraction fails, the amount stays unresolved and the simulation reports a conservative UNRESOLVED state (never treated as safe).

## How ASP Is Calculated

ASP = clamp(baseline_min_EOD_balance − minimum_balance_to_keep, 0, requested_amount), floored to 0.01. The derivation is mathematically exact under EOD netting (paying p today shifts every EOD balance down by p) and verified by a real simulator run.

## How Earliest Full-Payment Date Is Calculated

The first date d in [request_date, request_date+90] where both prefix_min[d−1] ≥ floor and suffix_min[d] − requested ≥ floor, using prefix/suffix minima of the baseline EOD path. Mathematically equivalent to per-date simulation.

## Full / Partial / Installment / Wait Logic

- **full_payment**: pay requested_amount today if SAFE; optional spending changes may rescue
- **partial_payment**: exactly 2 payments (ASP today + remainder on earliest date), no option needed
- **installments**: exact reproduction of a supplied payment option (dates/amounts/fees)
- **wait**: single full payment on the earliest safe date
- Ranking: official 6-key order (deadline, no changes, min total, early start, fewer payments, lowest option_id)

## Spending-Change Logic

Changes target projected recurring debit streams that are flexible, non-protected, and in a category the user permits adjusting. reduce_to targets exactly the supplied minimum_allowed_amount. Max 3 changes; stop/reduce on the same event are mutually exclusive.

## How to Run

```bash
# place the official dataset at ./dataset/ (sibling to code/)
python code/main.py --output
```

This generates `output.csv` at the repository root.

## Validation Commands

```bash
python -m unittest discover -s tests -v    # 258 tests
python code/main.py --selfcheck            # sample self-check (25/25)
python code/main.py --diagnose             # per-user baseline diagnostics
```

## Dependencies

- Python 3.10+ (stdlib only — no external packages required)

## Dataset Location

The official `dataset/` directory must be placed as a sibling to `code/`:

```
project-root/
├── code/
├── dataset/
└── output.csv  (generated)
```

## Where usage_report.md Lives

`code/evaluation/usage_report.md` — describes the final 250-request production run's model/token/cost metrics (zero external inference calls; fully deterministic).
