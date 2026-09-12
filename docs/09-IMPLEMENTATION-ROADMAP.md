# 09 — Implementation Roadmap

Phases in execution order. Each phase has explicit validation gates and a stop condition.
Progress markers: `[ ]` not started, `[~]` in progress, `[x]` complete.

---

## PHASE 0 — Repository understanding and documentation — `[x]`
- Objective: full contract/data/rule understanding before any code.
- Tasks: clone, read official docs, inspect all datasets + samples, upstream check. **Done in Phase 0.**
- Deliverables: Phase 0 report; this `docs/` suite (Phase 0.5).
- Validation gate: every doc section evidence-backed; official vs inference separation.
- Acceptance: docs match repo @ `a7b9744`; unresolved items marked OPEN/TBD.
- Stop condition: no implementation until user approves Phase 1.

## PHASE 0.5 — Documentation consolidation — `[x]` (this phase)
- Deliverables: docs/00–09 + execution/DECISIONS.md; verification per completion gate.
- Stop condition: stop and await approval before Phase 1.

## PHASE 1 — Schemas, loaders, deterministic baseline, validation framework — `[x]` (2026-09-13: 77 tests green, selfcheck 25/25, dataset diff-clean)
- Objective: trustworthy data layer + contract enforcement skeleton.
- Tasks: `io.py` (Decimal/date/enum parsing, `|`-list splitting); record types for all 9 files;
  `validators.py` output-contract checks; project README run instructions; `usage.py` skeleton;
  evidence cache format.
- Dependencies: none (Phase 0.5 approval).
- Deliverables: loaders + unit tests; contract validator runnable on a dummy output.
- Validation gates: loader tests green on all 9 files; round-trip row counts match verified counts (02).
- Acceptance: zero silent parsing coercion (fail-fast), Decimal everywhere on money.
- Stop condition: hard-fail behavior proven on malformed input fixture.

## PHASE 2 — Lifecycle resolver and 90-day simulator — `[ ]`
- Objective: correct per-user cash reality.
- Tasks: conflict-order resolver (R14); dedup; linked-event lifecycle; FX at settlement date
  (+chain fallback 03 §E4); recurrence detection (03 §E1); pending/scheduled/settled handling;
  day-granular simulator with debits-before-credits ordering and min-balance tracking.
- Dependencies: Phase 1.
- Deliverables: `lifecycle.py`, `state.py`, `forecast.py` + unit tests for T-pend*, T-cancel,
  T-unrealized, T-fx, T-recur, T-sameday.
- Validation gates: all Phase-2 unit tests green; simulator on real users produces sane
  never-below-zero-except-pending scenarios.
- Acceptance: every rule R1–R13 covered by at least one test.
- Stop condition: sample regression (Phase 5) not started until simulator is rule-complete.

## PHASE 3 — Candidate plan generation and deterministic ranking — `[ ]`
- Objective: enumerate and rank safe plans exactly per official rules.
- Tasks: full-now / full-later / partial / per-option installments / wait candidates;
  spending-change search (≤3, eligible sets, floor); official 6-key ranker (R30);
  asp + earliest-date computation **without** changes (R16/R17, distinct simulator runs).
- Dependencies: Phase 2.
- Deliverables: `plans.py`, `ranker.py` + tests T-installment, T-partial, T-changes, T-pref,
  T-maxmonths, T-earliest, ranking/tie-break tests.
- Validation gates: unit tests green; synthetic scenarios force each of the 5 methods.
- Acceptance: plan invariants R19–R30 all test-covered.
- Stop condition: no full-dataset run in this phase.

## PHASE 4 — AI evidence extraction for messages/images — `[ ]`
- Objective: structured, cached, injection-resistant perception layer.
- Tasks: model selection (**TBD — MODEL SELECTION**); prompts (evidence-as-data, claim
  contract of 05); schema validation + retry + fallback; cache; usage metering wired.
- Dependencies: Phase 1 (cache format); can run parallel to Phase 3.
- Deliverables: `evidence.py`, `prompts/`, `evidence_cache.json`, extraction tests
  (16 images + labeled messages), adversarial tests.
- Validation gates: 16/16 images correctly parsed (event_253 = 4,365,000 IDR net pay);
  labeled-message set passes; injection tests show zero behavioral change.
- Acceptance: no claim applied without provenance; blank amounts resolved or safely flagged.
- Stop condition: lifecycle resolver consumes only schema-valid claims.

## PHASE 5 — 25-sample regression debugging and hardening — `[ ]`
- Objective: reproduce all 25 solved rows field-by-field.
- Tasks: run sample evaluator; pin OPEN interpretations (03 §E1/E2/E3/E4/E8) strictly via
  sample evidence; fix until green; add missed-edge tests.
- Dependencies: Phases 2–4.
- Deliverables: `evaluation/sample_report.md` with field-level results; updated DECISIONS.md
  (OPEN → decided with evidence).
- Validation gates: 25/25 on amount_safe_to_pay, affordability_status, method, plan,
  earliest_date, spending_changes (explanation reviewed for grounding).
- Acceptance: no regression across re-runs (deterministic: two consecutive runs identical).
- Stop condition: any hard-field mismatch below 25/25 blocks Phase 6 (or is explicitly
  waived with rationale in DECISIONS.md).

## PHASE 6 — Full 250-request execution — `[ ]`
- Objective: produce the real `output.csv`.
- Tasks: clean-process full run; validators green; spot-audit ≥10 rows against raw evidence;
  timing/budget check against deadline.
- Dependencies: Phase 5 gate.
- Deliverables: root `output.csv` (250 rows + header), run artifacts.
- Validation gates: end-to-end validators (07 §7); re-run reproducibility.
- Acceptance: README pre-submit checklist items all verified mechanically.
- Stop condition: any validator violation aborts and returns to Phase 5.

## PHASE 7 — Final audit, usage report, packaging, submission — `[ ]`
- Objective: ship correct artifacts.
- Tasks: final full-dataset run tagged as the report run; regenerate
  `evaluation/usage_report.md` from that run's actual measured usage; `git fetch` upstream
  re-check + change-impact assessment; assemble `code.zip` (code, prompts, README,
  `evaluation/`); confirm `log.txt` complete; provide submission link
  (https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission).
- Dependencies: Phase 6.
- Deliverables: `code.zip`, final `output.csv`, `chat_transcript` (`log.txt`), usage report.
- Validation gates: packaging checklist; report values match the final run's JSONL.
- Acceptance: all official submission requirements (01 §13) satisfied.
- Stop condition: submit only on explicit user authorization.
