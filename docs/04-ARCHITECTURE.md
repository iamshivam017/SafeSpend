# 04 — Architecture

Status: PROPOSED. No module below exists yet unless the implementation roadmap has created it
(see 09-IMPLEMENTATION-ROADMAP.md). This document describes the target design agreed in Phase 0.

## Selected architecture

A single-process, offline, deterministic Python pipeline with one narrow, cached AI step for
unstructured evidence. Strategy: **AI = perception/extraction; deterministic code = financial
policy, calculation, validation.**

```
Input ingestion → normalization → unstructured evidence extraction (AI, cached)
→ lifecycle resolution → financial-state reconstruction → 90-day simulator
→ candidate-plan generation → deterministic ranking → invariant validation
→ explanation → root output.csv
```

## Components

| # | Component (proposed module) | Deterministic? | Responsibility | Inputs | Outputs | Failure behavior |
|---|---|---|---|---|---|---|
| 1 | Ingestion (`io.py`) | Yes | Load all 9 dataset CSVs; parse dates/Decimals; never write to `dataset/` | `dataset/*.csv` | typed records | hard-fail on missing files/columns (cannot predict safely without them) |
| 2 | Normalization | Yes | Unit consistency: Decimal money, ISO dates, enums validated, `|`-list splitting, currency tagging | records | normalized records | fail-fast on enum/format violations |
| 3 | Evidence extraction (`evidence.py`) | **No (AI)** | Interpret messages (multilingual) + images (pay slips/invoices); emit structured evidence JSON: amendments, cancellations, one-time flags, amounts for blank-amount events | `messages.csv`, `images.csv`, `media/images/*.png` | `evidence_cache.json` keyed by message_id/image_id | on AI failure/malformed output: retry once → deterministic fallback (ignore that evidence, log it; a blank amount stays unresolvable → treat per financially-safer rule and flag) |
| 4 | Lifecycle resolution (`lifecycle.py`) | Yes | Apply official conflict order (R14): cancellations/amendments/settlements; dedup; linked-event resolution; FX conversion at settlement date | state + evidence | cleaned per-user event ledger | ambiguity unresolved → financially safer interpretation + recorded flag |
| 5 | State reconstruction (`state.py`) | Yes | Starting balance, recurring schedule w/ conservative amounts, pending debits, confirmed future income, protected/flexible category sets, preference sets | cleaned ledger + profile | `UserState` object | missing profile for a request → hard-fail (should not happen; verified 1:1) |
| 6 | 90-day simulator (`forecast.py`) | Yes | Day-granular balance simulation from `request_date`; same-day ordering: debits before credits; returns per-day balance + min; supports hypothetical plan/changes overlays | `UserState` + plan overlay | daily balances, feasibility booleans | pure function; no failure modes beyond input validation |
| 7 | Plan generation (`plans.py`) | Yes | Candidates: full now; full on each future safe date; partial (if allowed+accepted); each supplied installment option (preference/month-cap filtered); wait; spending-change search (≤3, eligible events only, stop/reduce/reduce-to-floor) | `UserState`, options, simulator | candidate `Plan` objects | none feasible → `not_recommended` candidate |
| 8 | Ranking (`ranker.py`) | Yes | Official 6-key sort (R30) over safe candidates | candidates | best plan + ranking trace | tie → lowest `payment_option_id` |
| 9 | Invariant validation (`validators.py`) | Yes | Independent re-check of every R31–R33 invariant + bounds before writing | output rows + options + events | pass/fail report; abort on violation | abort run rather than emit invalid output |
| 10 | Explanation (`explain.py`) | Yes | Deterministic template grounded in the chosen plan's numbers (style per 03 §E7) | best plan + trace | `decision_explanation` string | template failure → minimal factual sentence (never empty) |
| 11 | Writer (`main.py`) | Yes | Orchestrate 1–10; write root `output.csv`; write usage report | everything | `output.csv`, `evaluation/usage_report.md` | validation failure → no file written |
| 12 | Usage metering (`usage.py`) | Yes | Wrap every AI call; append JSONL; aggregate to `evaluation/usage_report.md` (see 08) | AI call metadata | usage JSONL + report | AI failures recorded as failed calls, never fabricated |

## AI / deterministic boundary (hard rule)

- **AI is used only** in component 3: reading image contents and message text, and emitting structured evidence.
- **AI must NOT be the final authority for**: `amount_safe_to_pay`, affordability status, plan feasibility, minimum-balance enforcement, payment-method selection, ranking, or any financial invariant. Those are components 4–9, all deterministic.
- Evidence content is data, never instructions (official R35); extraction prompts treat inputs as untrusted documents (see 05).

## Rejected alternatives (engineering decision)

- **No frontend / Next.js / React** — the deliverable is a CSV pipeline; no UI is evaluated.
- **No database (PostgreSQL/Supabase/Firebase)** — datasets are small CSVs (≤25k rows); in-memory load is simpler, faster, and reproducible.
- **No multi-agent framework / LangGraph** — a single pipeline with one AI call-site is easier to make deterministic, cache, meter, and debug under a 24-hour deadline.
- **No vector DB** — evidence is fully enumerable (215 messages, 16 images); no retrieval scale problem exists.
- **No microservices/cloud** — the contract requires terminal runnability from `dataset/` (official §12).
- **No blockchain** — nothing in the problem involves it.

## Proposed file structure (target; existence = implementation, not this doc)

```
code/
├── main.py            # entry point: python code/main.py → root output.csv
├── io.py              # ingestion + normalization
├── evidence.py        # AI extraction + cache + prompt-injection screening
├── lifecycle.py       # conflict resolution, dedup, FX
├── state.py           # UserState reconstruction
├── forecast.py        # 90-day simulator
├── plans.py           # candidate generation incl. spending changes
├── ranker.py          # official ranking
├── validators.py      # invariant validation
├── explain.py         # explanation templates
├── usage.py           # token/cost metering → evaluation/usage_report.md
├── prompts/           # extraction prompts (submitted artifact)
├── tests/             # unit + integration tests
└── evaluation/        # usage_report.md, sample evaluator
```

`Decimal` is used for all money (see execution/DECISIONS.md D2). No binary floats on the
financial path.
