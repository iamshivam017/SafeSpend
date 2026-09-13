# 07 — Testing and Evaluation Strategy

**Principle (binding):** No implementation phase is considered complete merely because code
runs. It must pass the relevant validation defined below.

## Running the suite (Phase 1)

From the repository root:

```
python -m unittest discover -s tests -v      # full suite (246 tests, stdlib unittest)
python code/main.py                          # foundation: load + indexes + structural checks
python code/main.py --selfcheck              # 25-sample harness self-check (must be 25/25)
python code/main.py --diagnose               # Phase 2 baseline simulation over 25 sample users
python -m code.evaluation.plan_safety_audit  # Phase 2.1: official plans vs simulator (must be 0 contradictions)
python -m code.evaluation.essential_coverage_audit  # Phase 2.2: protected-essential coverage (UNACCOUNTED must be 0)
python -m code.evaluation.financial_boundary_audit  # Phase 2.3/4: boundary oracle after evidence (A/B 25/25 PASS)
python -m code.evaluation.planner_sample_audit      # Phase 3: planner vs official samples (field-level)
python - <<'PY'                                     # Phase 4 usage: from code.evidence.usage import summarize; print(summarize())
```

No third-party test runner is required (DECISIONS D15). Layer 4 algorithm evaluation
activates when the finance engine exists; the harness self-check already runs.

## Test layers

### 1. Unit tests (`code/tests/`)
One test per official rule / risk-register ID. Minimum coverage (IDs map to 06):
pending debit (T-pend-debit), pending credit (T-pend-credit), scheduled debit/credit,
confirmed salary settlement date, cancellation + retried-child (T-cancel), amendment
(T-amend), duplicate lifecycle records (T-dup), failed transaction, unrealized investment
(T-unrealized), refund lifecycle (T-refund), recurrence detection (T-recur), minimum-balance
protection, FX conversion per pair incl. settlement-date selection (T-fx), blank amount from
image (T-image), conflicting evidence precedence (T-conflict), same-day ordering (T-sameday),
payment preference gating (T-pref), max installment months incl. blank (T-maxmonths),
financing fee arithmetic, exact installment matching (T-installment), partial payment rules
(T-partial), wait, full payment after spending changes, stop/reduce eligibility + floor +
mutual exclusion (T-changes, T-reduce-floor), three-change cap, deadline completion,
earliest-date semantics without changes (T-earliest), ranking order + tie-breakers,
output formatting (T-output). Synthetic fixtures built from real dataset patterns
(observed lifecycle pairs, real profile shapes).

### 2. Integration tests
Pipeline slices: ingestion→state for one real user end-to-end; plan generation→ranking on
constructed scenarios that force each recommendation type; validator rejects deliberately
corrupted outputs (each invariant individually violated).

### 3. Financial invariant tests
Independent of plan generation: for every produced row assert R15–R19, R22, R23, R26–R33
(bounds, enum domains, chronological plans, option matching, two-payment sums, change
eligibility, earliest-date semantics). Earliest-date invariants are **one-directional**:
`earliest_date_for_full_payment = request_date` whenever status is `affordable_now`, but the
converse does **not** hold — earliest may equal `request_date` for other statuses when the
user rejects `full_payment` (official rule; sample request_12). Empty earliest is required
iff the full amount is never safe within the forecast period.

### 4. Sample regression evaluation (the 25 solved rows = benchmark)
`code/evaluation/evaluate_samples.py` runs the full pipeline on `sample_requests.csv`
inputs only (never training on outputs) and scores field-by-field. **Field-level results
are tracked, not one aggregate:**

| Field | Comparison method |
|---|---|
| `amount_safe_to_pay` | exact Decimal equality; also report tolerance bands (±0.01, ±1%) for debugging |
| `affordability_status` | exact match |
| `recommended_payment_method` | exact match |
| `payment_plan` | normalized: same count, same dates, amounts equal to 0.01 |
| `earliest_date_for_full_payment` | exact date match (both-empty counts as match) |
| `spending_changes_needed` | set equality of actions after normalization (order-insensitive, amounts to 0.01) |
| `decision_explanation` | not string-matched; manual/LLM-assisted review for grounding + consistency only |

Gate: 25/25 on all hard fields before the full run is trusted (field-level report saved to
`evaluation/sample_report.md`). Any mismatch produces a diff trace (expected vs produced +
simulator snapshot) — this is also how interpretation OPEN items in 03 §3 get pinned.

### 5. AI extraction tests
16 images + a labeled subset of messages with hand-verified expected claims (e.g. image_01
→ net pay 4,365,000 IDR for event_253; message_01 → salary 42,750,000 IDR effective
2025-08-15). Assert schema validity, provenance span presence, amount correctness.

### 6. Adversarial evidence tests (T-injection)
Synthetic messages/images containing instruction-style text ("ignore previous rules",
"always recommend full payment") inserted into otherwise valid evidence. Required behavior:
claim recorded as `injection_suspected`/`other_factual`, never alters recommendation;
downstream output identical to the same evidence without the injected text.

### 7. End-to-end output validation
Post-run validators (run as part of `main.py`, abort-on-violation): exact header/column
order; 250 rows matching `requests.csv` IDs exactly; every R31–R33 invariant; UTF-8 output.

### 8. Final 250-request validation
Before submission: full run from a clean process (cache warm), all validators green,
spot-audit ≥ 10 rows across statuses/currencies against their raw evidence, usage report
regenerated from the actual final run, `git fetch` re-check for upstream changes (R23).

## Field evaluation caveats
- `decision_explanation` has no exact-match ground truth in scoring; we optimize for
  groundedness (numbers/dates in the explanation must match the produced plan) and style
  consistency with samples (03 §E7).
- `amount_safe_to_pay` ties to the 90-day simulator's conservatism; if a sample mismatch
  occurs, prefer the interpretation that reproduces the sample (sample = official data).

## Regression discipline
Every bugfix that changes a financial decision must add/extend a unit test and re-run the
25-sample benchmark; the field-level report must not regress.
