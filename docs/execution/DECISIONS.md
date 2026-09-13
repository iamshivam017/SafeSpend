# Engineering Decision Record

Append-only. Only decisions actually made are recorded. Unresolved items carry STATUS: OPEN.
Categories of rule authority: OFFICIAL (source is official repo material — recorded here only
when we adopt it as a binding engineering constraint), OBSERVED (from sample data), ENGINEERING (our choice).

---

## D1 — Python as implementation language
- Date: 2026-09-13
- Decision: implement in Python (3.10+), entry point `code/main.py`.
- Status: DECIDED
- Context: no required language; contract requires terminal runnability.
- Alternatives considered: JavaScript/TypeScript.
- Chosen approach: Python.
- Why: Decimal money support, fastest to build a deterministic pipeline in the remaining ~14h, official docs name `code/main.py` as the conventional entry point.
- Trade-offs: none material for a CSV pipeline.
- Evidence/source: AGENTS.md §6.6, README.md.
- Revisit condition: only if a hard blocker appears in Phase 1.

## D2 — Decimal for all monetary calculations
- Date: 2026-09-13
- Decision: `decimal.Decimal` (with explicit context) for every money value; no binary floats on the financial path; output formatting without scientific notation.
- Status: DECIDED
- Context: hidden ground-truth compares `amount_safe_to_pay` exactly; IDR-scale amounts (46,018,000) and fee arithmetic make float error real.
- Alternatives: integers in minor units (fails on IDR which has no minor unit in data; amounts already carry 2 decimals for ZAR/EUR/USD and none for IDR — Decimal preserves what the data states).
- Chosen approach: Decimal.
- Why: exactness + matches dataset string precision directly.
- Trade-offs: slower; negligible at this scale.
- Evidence/source: user Phase 0 directive + engineering judgment; dataset amount formats.
- Revisit condition: never unless official data changes shape.

## D3 — AI limited to unstructured evidence interpretation
- Date: 2026-09-13
- Decision: AI is used only for message/image/request-text perception; all financial policy, calculation, selection, ranking, and validation are deterministic Python.
- Status: DECIDED
- Context: official rules demand deterministic behavior "where possible" and reproducibility; scoring is exact-field comparison.
- Alternatives: AI end-to-end decisioning (rejected: nondeterministic, unmeterable, unverifiable).
- Chosen approach: perception-only AI with structured claim contract (docs/05).
- Why: auditability, caching to zero-token re-runs, invariant enforcement possible.
- Trade-offs: two subsystems to integrate; mitigated by the claim contract.
- Evidence/source: problem_statement.md determinism constraints; user Phase 0 directive.
- Revisit condition: if evidence extraction proves impossible within budget (would degrade to deterministic-only + flagged rows).

## D4 — No frontend / database / multi-agent framework / vector DB / microservices / cloud
- Date: 2026-09-13
- Decision: single-process offline pipeline; stdlib-only core (plus optional Pillow if needed for image preprocessing).
- Status: DECIDED
- Context: deliverables are CSV files; contract requires terminal runnability from `dataset/`.
- Alternatives: all of the above rejected (see docs/04 §Rejected Alternatives).
- Chosen approach: minimal architecture.
- Why: smallest architecture achieving accuracy/reliability/reproducibility under a 24h deadline.
- Trade-offs: none for this problem size (≤25k rows, 231 evidence items).
- Evidence/source: user Phase 0 directive §7; AGENTS.md §6.4.
- Revisit condition: none anticipated.

## D5 — Caching strategy for AI evidence
- Date: 2026-09-13
- Decision: extract once per evidence item, cache to `code/evidence_cache.json` keyed by source_id + content hash; re-runs (incl. final full-dataset run) require zero AI calls.
- Status: DECIDED
- Context: usage report must match the final run; determinism required.
- Alternatives: re-extract every run (nondeterministic + token waste).
- Chosen approach: persistent cache + run tagging in usage JSONL.
- Why: reproducibility, cost, and honest usage reporting.
- Trade-offs: stale cache risk if prompts change → cache keyed by prompt version too.
- Evidence/source: engineering; docs/08.
- Revisit condition: if prompt iteration invalidates cache during Phase 4/5.

## D6 — Same-day semantics — REVISED IN PHASE 2.1 on sample evidence
- Date: 2026-09-13 (revision 2)
- Decision: the minimum-balance floor is checked on the END-OF-DAY balance. Within-day movement order is deterministic TRACE presentation only (debits largest-first, then credits ascending); it does not affect the outcome. Revision 1 (debits-first intraday checks) was contradicted by official solved samples: request_18 and request_23 wait-plans pay exactly on payday and are official-safe, which an intraday debits-first check rejects.
- Status: DECIDED (rev. 2; implemented in code/finance/simulator.py::_apply_day)
- Context: official wording never specifies intra-day order; the solved samples are the stronger evidence and they net the day.
- Alternatives: intraday debits-first (rev. 1 — rejected by samples 18/23); credits-first (same objection as before).
- Chosen approach: EOD netting with ordered trace presentation.
- Why: official plans pay on payday; netting matches the official oracle. Netting is not leniency: a day whose NET dips below the floor is still unsafe (tested).
- Trade-offs: an intraday dip recovered by same-day credit is no longer flagged — accepted because the official oracle contradicts flagging it.
- Evidence/source: sample_requests.csv requests 18/23; plan-safety audit (0 contradictions post-change).
- Revisit condition: contrary hidden-ground-truth evidence in Phase 5/6.

## D7 — Model / provider selection — RESOLVED IN PHASE 4
- Date: 2026-09-13 (resolved, see D25)
- Decision: **RESOLVED** — deterministic EN/ID message parser + one-time agent vision for images; no external AI provider; pluggable claim contract retained (full rationale in D25). (TBD — MODEL SELECTION). Requirement: text+image input, JSON- reliable output, low cost; usage metering is provider-agnostic.
- Context: 215 messages (multilingual) + 16 images to extract; one-time cached pass.
- Alternatives considered: pending.
- Chosen approach: pending.
- Why: —
- Trade-offs: —
- Evidence/source: docs/05, docs/08.
- Revisit condition: decide at Phase 4 start; record price table then.

## D8 — `max_installment_months` semantics — RESOLVED IN PHASE 3
- Date: 2026-09-13 (resolved)
- Decision: an installment option is eligible when its span — (number_of_payments − 1) × payment_frequency_days, i.e. first-to-last payment duration — is <= max_installment_months × 30 days (30-day month convention). Blank max_installment_months = installments never considered.
- Status: DECIDED (ENGINEERING DECISION, sample-consistent; implemented in code/planning/candidates.py)
- Context/analysis: all five installment samples are consistent — chosen option spans ~2 months with max months 7/12/11/3/6, and every rejected alternative's span exceeds the cap (17.6>7, 14.0>12, 18.7>11, 17.6>3, 14.0>6). Note: in these samples the rejected longer options also carry higher totals, so ranking criterion 3 alone agrees; the cap never binds contradictorily. A number-of-payments reading would also fit the five samples — the duration reading matches the field name and is chosen.
- Alternatives: number-of-payments cap (equally consistent on samples, less literal); calendar-month arithmetic (unnecessary precision).
- Trade-offs: a hidden weekly-commitment option with span slightly over the cap is excluded — Phase 5 calibration revisits if evidence appears.
- Evidence/source: AGENTS.md 6.1; request_payment_options.csv; solved samples 02/07/12/17/22.
- Revisit condition: Phase 5 sample regression contradiction.

## D9 — Reduce-target policy — RESOLVED IN PHASE 3
- Date: 2026-09-13 (resolved)
- Decision: reduce_to targets EXACTLY the supplied `minimum_allowed_amount` of the referenced series (the sample evidence: event_989 -> 665,950; event_1816 -> 23.50 — both exactly the floor). No intermediate reductions; floor 0 when no floor is supplied.
- Status: DECIDED (SAMPLE-DERIVED / ENGINEERING DECISION; implemented in code/planning/spending_changes.py::eligible_actions)
- Alternatives: minimal-sufficient reduction per candidate (more complex, no sample support); reduce-to-zero (rejected — ignores the supplied floor).
- Why: deterministic, maximizes safety gain, exactly reproduces both official reduce_to samples.
- Trade-offs: may reduce slightly more than strictly necessary — conservative direction, and ranking criterion 2 (fewer changes) limits usage.
- Evidence/source: sample_requests.csv requests 11/21; user Phase 3 directive section 15.
- Revisit condition: Phase 5 calibration evidence.

## D10 — Recurrence policy — REVISED IN PHASE 2.1/2.2 on sample evidence
- Date: 2026-09-13 (revision 3)
- Decision (detection): unchanged gap-bucket cadence detection (monthly 28-31d; fixed gaps +/-1; >=3 observations; >=60% majority; category names never evidence), PLUS day-of-month clustering: when a whole (user, category, direction, currency) series is not periodic, it is split into day-of-month clusters (tolerance 2, circular) and each cluster is re-tested — this detects interleaved twice-monthly salaries (users 09/13 evidence: paydays on the 7th/20th and 15th/20th) that naive gap detection misses. Monthly patterns anchor to the DOMINANT day-of-month, so a one-off adjustment (user_03's 08-20 spike) cannot hijack the projection anchor.
- Decision (projection scope, rev. 3 in Phase 2.2): patterns are CLASSIFIED, not blanket-suppressed by cadence. Monthly cadence -> fixed_commitment. Non-monthly -> fixed_commitment only when commitment-like (recent-5 amount spread <= 15% of median, or dominant event_type = subscription billing); otherwise variable spending (variable_essential if the category is protected, else variable_discretionary). Only fixed_commitment patterns project as dated events. Evidence: requests 02/03/04/08/12/17/22 official plans require variable sub-monthly purchases NOT to project as exact commitments, while directive 6.7 forbids blanket forbidding of genuine weekly/biweekly obligations. Conservative amounts unchanged (debits MAX last-3, credits MEDIAN last-3); staleness bound unchanged; +/-3d actual-overlap drop unchanged.
- Status: DECIDED (rev. 2); verified by the sample-plan safety audit: 0 contradictions across all officially-evaluable solved plans (was 10).
- Alternatives: keep sub-monthly projections (rejected — contradicts 7 official plans); project sub-monthly at means (still contradicts 5); category-based recurrence (forbidden).
- Why: the official solved plans are the strongest public regression oracle; repeated purchase gaps alone are not proof of a commitment.
- Trade-offs: sub-monthly commitments (if the hidden ground truth has any) are under-forecast — Phase 5 calibration revisits with full asp/earliest machinery.
- Evidence/source: sample_requests.csv (requests 09/13 traces; audit table); user Phase 2.1 directive.
- Revisit condition: Phase 5 calibration evidence.

## D18 — Conservative variable-essential amounts
- Date: 2026-09-13
- Decision: for a detected recurring DEBIT series, the projected amount is the MAX of the last 3 observations (over-reserve spending); for recurring CREDIT series, the MEDIAN of the last 3 (under-count income; robust to one-off adjustments). No provisioning is currently applied to irregular (non-periodic) essential categories.
- Status: DECIDED (Phase 5 calibration subject)
- Context: official "forecast essential variable spending conservatively" (AGENTS.md 6.3); the dataset shows fixed categories with constant amounts (rent/subscriptions/insurance) and variable essentials (utilities/groceries/dining) on strict cadences.
- Alternatives considered: trailing-30-day category provisioning for irregular essentials (rejected for now — no sample evidence yet, over/under-reservation risk unquantified); overall historical max (over-reserves stale spikes); minimum (forbidden — not conservative).
- Chosen approach: recent-window max (debits) / median (credits).
- Why: simple, deterministic, bounded by real history; the median robustly excluded user_03's one-off 1,964,250 salary adjustment.
- Trade-offs: if hidden ground truth provisions irregular essentials (groceries beyond their detected cadence), we under-reserve — Phase 5 regression will expose and recalibrate.
- Evidence/source: AGENTS.md 6.3; user Phase 2 directive section 11; dataset amount analysis.
- Revisit condition: Phase 5 calibration evidence.

## D21 — Essential variable spending provision — REVISED IN PHASE 2.2
- Date: 2026-09-13 (revision 2)
- Decision (rev. 2): gate condition is 'NOT already PROJECTED as a fixed commitment' — merely DETECTING a (sub-monthly) pattern no longer suppresses the provision (Phase 2.1 gap: detection + non-projection + gate-on-detection made essential spending vanish). Amount = MEDIAN of the last three 30-day window totals (robust central estimate; not one historical event, not the max window), placed ONCE at request_date+30. Empirically calibrated: request_01's official budget (X <= 15,225.10 ZAR) admits exactly one aggregate groceries provision (3,226.39); two occurrences or max-window sizing would contradict the official answer.
- Status: DECIDED (implemented in code/finance/recurrence.py::essential_provisions)
- Context: official "Forecast essential variable spending conservatively" (AGENTS.md 6.3). Coverage audit across all 275 users (D23): 611 protected categories FIXED_RECURRING, 273 VARIABLE_ESSENTIAL_RESERVE, 2 UNRESOLVED (blank-amount evidence, Phase 4), 0 NO_FUTURE_EVIDENCE, 0 UNACCOUNTED. The provision actively covers variable-essential streams (e.g. user_01 groceries 3,226.39 ZAR; user_13 groceries 396.09 + transport 195.55 EUR).
- Alternatives considered: 75th-percentile robust estimate (more aggressive, no evidence); weekly trailing average (same coverage, more occurrences); omitting the policy entirely (rejected — leaves the official rule uncovered for irregular essentials).
- Why: conservative, evidence-gated, double-count-safe, provenance-preserving (source event ids retained), independently tested.
- Trade-offs: none on current data (never fires); if future data triggers it, Phase 5 calibration revisits the gate.
- Evidence/source: AGENTS.md 6.3; user Phase 2.1 directive section 5; dataset census (0 essential-series gaps).
- Revisit condition: Phase 5/6 evidence that the hidden ground truth provisions irregular essentials differently.

## D23 — Two-concept recurrence architecture (Phase 2.2)
- Date: 2026-09-13
- Decision: the engine explicitly separates (A) FIXED / COMMITMENT-LIKE recurrence — projected as dated recurring events when history supports it (monthly cadence, or sub-monthly with stable amounts / subscription billing) — from (B) VARIABLE ESSENTIAL SPENDING — protected-category streams forecast as ONE aggregate conservative reserve (median of the last three 30-day totals), never as exact repeated purchases and never omitted. Every protected category with sustained history receives EXACTLY ONE treatment (fixed projection or reserve, never both, never neither); the coverage audit enforces UNACCOUNTED = 0 across all users. Repeated historical transactions and fixed commitments are distinct concepts; public-sample calibration must not erase protected spending.
- Status: DECIDED
- Context: Phase 2.1's monthly-only projection plus a detection-gated provision made protected variable spending vanish (the exact gap the external audit flagged).
- Alternatives: blanket project_non_monthly flag (rejected — disposable-weekly assumption contradicts directive 6.7); per-purchase projection of variable streams (rejected — contradicts 7 official plans); max-window or two-occurrence provisioning (rejected — contradicts request_01's official budget).
- Why: honors both official sentences — commitments respect supplied schedules, essentials are forecast conservatively — while the solved samples arbitrate the borderline.
- Trade-offs: the 15% stability tolerance and single-provision placement are engineering parameters; Phase 5 calibrates.
- Evidence/source: user_01/user_13 traces; audit + coverage outputs; user Phase 2.2 directive.
- Revisit condition: Phase 5 calibration evidence.

## D24 — Boundary oracle audit — Phase-2.3 hypothesis SUPERSEDED / INCORRECT
- Date: 2026-09-13 (Phase 2.3; SUPERSEDED same day by Phase 4 evidence discovery)
- Decision: add `code/evaluation/financial_boundary_audit.py` (evaluation-only, AST-isolated) running six boundary tests (A zero-payment baseline, B official-asp payment, C simulator-implied asp vs official, D requested amount at official earliest date, E one-day-before minimality, F full-today consistency vs earliest==request_date) over all 25 solved samples, with per-failure deep traces and cause classification.
- Phase-2.3 hypothesis (INCORRECT): the audit initially concluded that exact official asp/earliest embed "the reference implementation's hidden future event stream" and were information-theoretically unreproducible from participant-visible data.
- Why it was wrong: the Phase-2.3 analysis had not consumed `messages.csv`, which is participant-visible and contains material forward-looking facts. Counter-evidence: user_14's message states "Regular salary of EUR 2717 resumes on 2025-08-15. A new recurring childcare payment begins in the same month."; user_15's message states "Your first salary will be EUR 1661. The confirmed credit date is 2026-01-15." These directly explain the request_14/15 baseline contradictions (positive official asp with no participant-side detected income).
- CORRECTED CONCLUSION: boundary mismatches remain provisional until participant-visible message/image evidence is resolved. Material future income, amendments, cancellations, delays, and blank amounts may exist in messages/images and must be incorporated before concluding that public financial boundaries cannot be reproduced. (Phase 4 executes evidence resolution BEFORE Phase 3 planning for exactly this reason.)
- Status: SUPERSEDED (the audit tool and its per-test bookkeeping remain valid regression infrastructure)
- Evidence/source: messages.csv message_10 (user_14), message_11 (user_15); user Phase 2.3/4 directives.
- Revisit condition: after Phase 4 evidence application, remaining boundary deltas are re-analyzed before any new conclusion.

## D25 — Evidence pipeline architecture and D7 resolution (Phase 4)
- Date: 2026-09-13 (Phase 4)
- Decision: build `code/evidence/` — typed `EvidenceClaim` contract (14 whitelisted claim types), deterministic multilingual (EN/ID) message parser, image-amount cache, evidence-application layer, usage tracking. Architecture: untrusted message/image -> extraction -> strict typed claim -> validation/provenance -> deterministic finance engine. D7 RESOLVED: no external AI provider is used for extraction. Rationale: (a) the message corpus is template-generated and fully covered by whitelisted deterministic patterns — a regex parser is more reproducible, auditable, and free; (b) no external API credentials exist in the environment; (c) the 16 images were transcribed once by the interactive coding agent's own vision during development and cached in `code/evidence/cache.json` (recorded honestly in the usage log as agent-assisted, zero billed cost). The claim schema is model-agnostic: an AI extractor can be plugged in behind the same contract if an API key is provided.
- Status: DECIDED (D7 closed); message coverage 215/215 parsed (claims or recorded informational notes); image coverage 16/16 resolved (14 high confidence, 2 medium — handwritten/partially cropped); cache keyed by content identity and invalidated on prompt/schema/model change.
- Injection defense: only whitelisted templates yield claims; instruction-like phrases are flagged and ignored; free-form prose can never enter the finance engine (tested with adversarial phrases).
- Alternatives: external multimodal LLM extraction (rejected for now — no credentials, non-deterministic, cost; schema ready for it); manual hardcoded amounts (forbidden).
- Why: reproducibility + auditability + the official untrusted-evidence rule.
- Trade-offs: unseen message phrasings fall to the unparsed bucket (traceable, conservative); Phase 5 can extend templates.
- Evidence/source: messages.csv (215 rows), media/images (16), user Phase 4 directive; tests/test_phase4_evidence.py.
- Revisit condition: corpus phrasing drift, or user supplies an API key for the pluggable AI extractor.

## D26 — Post-evidence boundary status (Phase 4)
- Date: 2026-09-13
- Decision: after applying all participant-visible evidence (messages + 16 images), the boundary audit improves from 23 to 20 contradictions: Tests A (zero-payment baseline) and B (official-asp payment) become 25/25 PASS — the request_14/15 contradictions are fully explained by message evidence (salary resumed EUR 2717 on 2025-08-15; first salary EUR 1661 confirmed 2026-01-15). The remaining 20 (Tests E minimality + F full-today consistency) share one demonstrated mechanism: the official earliest dates always fall on PAYDAYS, implying the reference forecast includes sub-monthly purchase outflows that drain the balance before payday. Demonstrated on request_13: projecting sub-monthly purchases reproduces the official pre-payday-unsafe/payday-safe signature, but at our conservative max-last-3 amounts even payday becomes unsafe — the official purchase sizing sits between our policies and is not recoverable. No production change was made: fitting purchase amounts to close E/F would overfit hidden reference internals (prohibited).
- Status: DECIDED (documented model boundary)
- Alternatives: re-enabling sub-monthly projections (breaks 7 official plan audits); mean-amount purchases (still contradicts request_01's budget).
- Why: plan-level safety (the harder, fully-visible oracle) takes precedence; the residual is documented, not hidden.
- Trade-offs: asp/earliest exact-match accuracy remains bounded; Phase 5 may calibrate a purchase-amount statistic between mean and max.
- Evidence/source: financial_boundary_audit.py before/after (A/B 22->25 PASS each); request_13 mechanism demo; user Phase 4 addendum.
- Revisit condition: Phase 5 calibration evidence.

## D30 — Phase 5 calibration findings and parameter-propagation fix
- Date: 2026-09-13 (Phase 5 + addendum + reconciliation)
- Decision:
  (a) The original Phase-5 calibration harness results AND the addendum results are both SUPERSEDED. The original harness produced asp=3/status=18/method=20/plan=20/earliest=15 for scope=all occ=2 median; the addendum produced identical scores across all variants due to a parameter-shadowing bug (timeline.py constructed ProvisionParams() with hard-coded defaults instead of reading the module-level variable). The authoritative post-fix results are: protected/1/median = asp 4/status 19/method 21/plan 18/earliest 11/changes 22/0 contradictions (production default); all/2/median = asp 3/status 18/method 20/plan 17/earliest 9/changes 22/0 contradictions (no structural improvement).
  (b) No tested variant improves aggregate structural scores without introducing contradictions or losing capped samples. The current policy (scope=protected, occurrences=1, statistic=median) is retained as the local optimum.
  (c) The min_allowed classification was tested and REVERTED (creates request_01 contradiction).
  (d) D22 tested both horizon conventions: 11/25 exact both ways — no aggregate evidence, stays OPEN.
  (e) D16 rounding confirmed adequate (0.01 quantum, floor).
  (f) Parameter-propagation regression test added: proves that changing ProvisionParams scope/occurrences/statistic measurably changes reserve flows.
- Status: DECIDED (Phase 5 complete; D24 superseded; D22/D16 OPEN)
- Alternatives: adopting scope=all occ=2 median (rejected — loses asp/status/method without net structural gain); min_allowed classification (rejected — creates request_01 contradiction).
- Why: the harness is the objective arbiter; no variant dominates.
- Trade-offs: asp/earliest exact values remain bounded by D26.
- Evidence/source: calibration_harness.py output (18 variants, all measured); timeline.py shadowing fix (commit 8cac782); test_phase3_review_fixes.py.
- Revisit condition: Phase 6+ if new calibration evidence appears.

## D27 — Planning money quantum: 0.01, floor (Phase 3)
- Date: 2026-09-13 (Phase 3)
- Decision: one centralized planning quantum `PLANNING_QUANTUM = 0.01` (code/planning/models.py). ASP is FLOORED to the quantum (never rounded up — safety first); no other rounding is introduced (D16 unchanged).
- Status: DECIDED (ENGINEERING DECISION; sample-derived support: all 25 official asp values carry at most 2 decimal places across all five currencies)
- Alternatives: currency-specific minor units (rejected — IDR has none in the data); no quantization (rejected — unbounded fractional asp from FX arithmetic).
- Why: exact safety preserved (floor only lowers the payment), matches official precision.
- Trade-offs: a fractional-cent of headroom is discarded — negligible.
- Evidence/source: sample_requests.csv asp precision census; user Phase 3 directive.
- Revisit condition: official evidence of different precision.

## D28 — Unresolved/unsafe ASP fallback: conservative zero (Phase 3)
- Date: 2026-09-13 (Phase 3)
- Decision: when material unresolved evidence exists in the horizon, or the no-payment baseline is UNSAFE (even p=0 violates the floor), ASP = 0 with an uncertainty flag — no positive amount is provably safe, so none is asserted. Similarly earliest_date = None (empty) when the horizon is materially unresolved. UNRESOLVED is never treated as SAFE.
- Status: DECIDED (ENGINEERING DECISION, directive Part 4; request_14 is the regression fixture — childcare without amount)
- Alternatives: asserting asp from partial information (rejected — falsely precise); treating unresolved as safe (forbidden).
- Why: the required numeric output needs a value; zero is the only defensible conservative one.
- Trade-offs: asp=0 for unresolved users scores 0 on those asp cells — accepted as honest.
- Evidence/source: user Phase 3 directive sections 4/33; request_14 evidence trace.
- Revisit condition: Phase 4 extension resolves the unknown amounts.

## D29 — Planner architecture and ASP/earliest derivation (Phase 3)
- Date: 2026-09-13 (Phase 3)
- Decision: the planner (`code/planning/`) computes baseline fields by exact derivation with simulator verification, not by search: (a) paying p on request_date shifts every EOD balance by -p, so ASP = clamp(min_EOD_balance_without_payment - floor, 0, requested), floored to the 0.01 quantum (D27) and verified by one simulator run; (b) earliest = the first day d where prefix_min[d-1] >= floor and suffix_min[d] - requested >= floor (prefix/suffix minima of the baseline EOD path), mathematically equivalent to per-date simulation under EOD netting. Both are computed once per request (BaselineMetrics) and NEVER altered by candidates. Spending changes are evaluated by direct simulation of modified flow sets (singles -> pairs -> triples, lazily). Ranking is the official 6-key tuple plus an internal canonicalization applied only after all official keys (fewer changes -> smaller intervention -> lexicographic).
- Status: DECIDED
- Alternatives: cent-by-cent bisection ASP search (unnecessary — derivation is exact); per-date full simulation for earliest (equivalent but slower); fitting asp to official values (rejected — D24/D26 information boundary).
- Why: exactness, speed (250 requests planned in 1.17s dry-run), and provable monotonicity.
- Trade-offs: asp/earliest values diverge from the official oracle wherever the reference purchase-stream sizing differs (documented, D26; sample audit field matches: status 19/25, method 21/25, plan 18/25, changes 22/25, asp 4/25, earliest 11/25 — Phase 5 calibration frontier).
- Evidence/source: problem_statement.md; user Phase 3 directive; planner_sample_audit output.
- Revisit condition: Phase 5 calibration.

## D22 — Sample-plan safety audit + horizon classification
- Date: 2026-09-13 (Phase 2.1)
- Decision: (a) added `code/evaluation/plan_safety_audit.py` — an EVALUATION-ONLY oracle that replays each solved sample's official payment_plan as hypothetical payments and reports PASS/CONTRADICTION/DEFERRED; production code is barred from importing it (AST-enforced). Result after corrections: 14 PASS / 11 DEFERRED / 0 CONTRADICTIONS. (b) The 90-day horizon boundary ([request_date, request_date+90] inclusive, 91 entries) is reclassified: official wording ("Forecast the user's balance for the next 90 days") does NOT resolve inclusive vs exclusive endpoints; no solved sample distinguishes them. It is an ENGINEERING DECISION / OPEN calibration item, centralized behind `HORIZON_DAYS` in code/finance/timeline.py (single constant; no scattered +90 assumptions).
- Status: DECIDED (audit); OPEN (horizon boundary convention)
- Alternatives: claiming the 91-entry convention as official (rejected — no official source resolves it); [d0, d0+89] (equally unsupported; kept 90 as the conservative superset).
- Why: honesty about what official material specifies; the audit prevents engine/oracle drift before Phase 3.
- Trade-offs: if the hidden truth uses +89, asp shifts by boundary events — Phase 5 calibration revisits.
- Evidence/source: problem_statement.md line 178/180; AGENTS.md 6.3; README.md; audit run output.
- Revisit condition: boundary-distinguishing sample evidence or Phase 5 calibration.

## D20 — CodeRabbit review round: engine-hardening policy changes
- Date: 2026-09-13
- Decision: an independent CodeRabbit review of the Phase 2 engine (agent review + fix verification, two passes) drove these policy/behavior changes, all regression-tested in tests/test_phase2_review_fixes.py:
  (a) cyclic/self `linked_event_id` chains raise DataError (fail-fast; previously hung);
  (b) credit representative amount is the exact numeric Decimal median (was a lexicographic string median — misstated mixed-magnitude income);
  (c) a series silent for more than `max_silent_cadences` (default 2) cadences before request_date no longer projects (no phantom income; request_12's minimum_projected_balance corrected 185,979.44 -> 102,817.10);
  (d) projected occurrences strictly after request_date only (a same-day projected credit is never available cash; applies to debits too — documented marginally anti-conservative);
  (e) UNSAFE outranks UNRESOLVED (a proven floor violation is certain information);
  (f) out-of-window hypothetical payments raise DataError (never silently ignored);
  (g) lifecycle terminal-drop requires direction+amount match; duplicate-substance collapse includes pending rows (documented under-count safety net);
  (h) fixed-gap cadences (7/10/14/21d observed) now actually implemented via the dominant-gap rule (monthly band checked first). This legitimately flipped request_09's baseline to UNSAFE (groceries 10d / dining 21d series now detected; zero actual/projection clashes).
- Status: DECIDED; independent re-verification verdict: "engine is now sound to build Phase 3 on".
- Alternatives: leave findings to Phase 5 (rejected — C2/C3 corrupt the numbers Phase 3 plans against).
- Why: review findings were empirically demonstrated on real dataset users.
- Trade-offs: none beyond documented safety nets; 14 new regression tests lock the fixes.
- Evidence/source: CodeRabbit review + fix-verification reports (2026-09-13); commit history.
- Revisit condition: Phase 5 calibration may tune max_silent_cadences and the same-day rules.

## D19 — Starting-balance snapshot interpretation
- Date: 2026-09-13
- Decision: `current_available_balance` is the balance AS OF request_date (day 0). Settled/scheduled events effective BEFORE request_date are already inside it and are never re-applied; only cash movements with effective date in [request_date, request_date+90] are applied. Historical blank-amount events are therefore out of scope (not UNRESOLVED).
- Status: DECIDED (engineering interpretation — official wording says only "current available balance")
- Alternatives: re-applying all settled history (double-counts); unknown snapshot date (unimplementable).
- Why: the only reading consistent with "current" plus a 90-day forward forecast; validated by diagnostics (no double-count anomalies across the 25 sample users).
- Trade-offs: if hidden ground truth uses a different snapshot convention, asp shifts — Phase 5 will expose.
- Evidence/source: problem_statement.md; AGENTS.md 6.1; user Phase 2 directive sections 7/17.
- Revisit condition: Phase 5 regression contradiction.

## D12 — Project GitHub repository and branch strategy
- Date: 2026-09-13
- Decision: use `https://github.com/iamshivam017/SafeSpend` (public, default branch `main`, empty at adoption) as the project repository; develop on branch `buildathon-production`; keep `origin` = the official challenge repo (upstream change checks) and add `github` = SafeSpend as the push remote.
- Status: DECIDED
- Context: user directive to continuously manage the associated GitHub repository; official README expects `log.txt` gitignored (uploaded separately as chat_transcript).
- Alternatives considered: develop on SafeSpend `main` (rejected — violates no-development-on-default-branch rule); fork the official repo (unnecessary — SafeSpend designated by user).
- Chosen approach: `buildathon-production` branch created from official-repo history (starter files + dataset + docs), pushed to SafeSpend; no PRs/merges to `main` without explicit authorization; no force pushes/history rewrites.
- Why: preserves official challenge files as the base, isolates development, keeps the official upstream reachable for mid-event change detection.
- Trade-offs: SafeSpend `main` stays empty until an authorized merge/final submission.
- Evidence/source: user repository-management instructions; SafeSpend GitHub API inspection (empty, 0 commits).
- Revisit condition: if the user designates a different repository or requests a different branch name.

## D13 — Audit correction: decouple earliest-date/status and safety/deadline
- Date: 2026-09-13
- Decision: (a) `earliest_date_for_full_payment = request_date` is treated as a **one-directional** implication of `affordable_now`, never as an equivalence — earliest reflects raw financial capacity independent of payment-method preferences (sample request_12). (b) Financial *safety* is defined solely by the minimum-balance / cash-flow rules over the forecast horizon; `desired_completion_date` is a separate plan-eligibility / ranking constraint and is never folded into the safety computation for asp or earliest-date.
- Status: DECIDED
- Context: Phase 0/0.5 audit found docs/07 stated an incorrect `earliest = request_date iff affordable_now` invariant, and docs/00/01 phrased safety as including completion by the deadline.
- Alternatives considered: keeping the biconditional as a validator (rejected — would reject valid rows like request_12's pattern); treating the deadline as a safety input (rejected — would corrupt asp/earliest computation).
- Chosen approach: corrected docs/00, docs/01, docs/03 R17, docs/07; Phase 1 validators assert the one-directional form.
- Why: matches the official wording ("measures financial capacity independently of the user's payment-method preferences") and the official ranking structure where the deadline is criterion 1 of plan choice.
- Trade-offs: none.
- Evidence/source: problem_statement.md "Allowed values"/"90-Day Safety Check"/"Choosing Between Safe Plans"; sample request_12; user audit instruction.
- Revisit condition: only if official material changes.

## D14 — Package layout: `code/` package + repo-root `tests/`
- Date: 2026-09-13
- Decision: solution lives in the `code` package (`code/main.py` entry point per official convention); automated tests live in repo-root `tests/` with a `_bootstrap.py` sys.path shim.
- Status: DECIDED
- Context: Phase 1 directive proposed this layout; official README documents `python3 code/main.py` as the run command.
- Alternatives considered: renaming the package to `safespend` (cleaner namespacing — `code` shadows the stdlib `code` module — but breaks the documented official entry point); `pytest` (adds a dependency; D15).
- Chosen approach: keep `code` as the package name; our modules never import the stdlib `code` module, so the shadowing is inert; record the risk here.
- Why: official run-command compatibility outweighs naming aesthetics.
- Trade-offs: `import code` shadowing — monitored; if a future dependency imports stdlib `code`, revisit.
- Evidence/source: README.md quick start; AGENTS.md 6.6.
- Revisit condition: any dependency requiring stdlib `code`, or organizer push changing the entry-point convention.

## D15 — Test runner: stdlib unittest (no pytest dependency)
- Date: 2026-09-13
- Decision: `python -m unittest discover -s tests -v`; tests are unittest classes (also pytest-compatible if pytest is present locally).
- Status: DECIDED
- Context: dependency discipline: stdlib suffices for unit tests.
- Alternatives considered: pytest (richer fixtures/assertions; not needed yet).
- Chosen approach: unittest.
- Why: zero dependencies, deterministic CI-free local runs under the hackathon deadline.
- Trade-offs: less ergonomic fixtures; revisit only if test complexity demands it.
- Evidence/source: engineering; user dependency rules.
- Revisit condition: test suite complexity grows beyond unittest ergonomics.

## D16 — Rounding policy: none applied; exact scale preserved (OPEN for Phase 3)
- Date: 2026-09-13
- Decision: parsers never round; parsed Decimal scale is preserved end-to-end ("100.50" stays 2 dp); all comparisons exact. Where ground truth might demand rounding (e.g. installment per-payment amounts are supplied pre-rounded by options — we adopt their exact values), no independent rounding is invented.
- Status: OPEN (revisit when sample regression reveals whether hidden ground truth rounds asp or plan amounts)
- Context: official materials specify no rounding rule.
- Alternatives: ROUND_HALF_UP/EVEN at 2 dp (invented — rejected).
- Chosen approach: exact preservation; sample regression will expose any rounding expectation.
- Why: no silent invention of policy; wrong rounding would fail exact scoring either way.
- Trade-offs: potential future mismatch with hidden ground truth; mitigation is the Phase 5 regression loop.
- Evidence/source: problem_statement.md (silent on rounding); Phase 1 directive section 6.
- Revisit condition: Phase 5 sample regression evidence.

## D17 — Loader strictness: exact header-set equality; fail-fast enums
- Date: 2026-09-13
- Decision: loaders require the exact expected header set (missing AND unexpected columns both raise); controlled-value fields parse via StrEnum with the observed official sets and raise on unknown values; benign surrounding whitespace in scalar fields is stripped before validation (documented, deterministic).
- Status: DECIDED
- Context: Phase 1 directive: fail-fast for structural data, surface unknown values clearly.
- Alternatives: tolerant header subset matching (hides upstream schema changes); silent enum fallback (forbidden).
- Chosen approach: strict.
- Why: hidden eval data surprises must surface immediately, not corrupt predictions silently.
- Trade-offs: an organizer-added column mid-event would fail loads until we update the header contract — acceptable (risk R23 covers detecting upstream changes; the error message names the exact column delta).
- Evidence/source: Phase 1 directive sections 21/8; user Phase 1 prompt.
- Revisit condition: organizer dataset schema change (then extend header sets deliberately).

## D11 — FX policy — RESOLVED IN PHASE 2: direct rates only
- Date: 2026-09-13 (resolved)
- Decision: convert using ONLY the direct same-date official rate row for the stated from->to direction (official rule). A missing rate raises MissingRateError with a clear diagnostic — no chaining, no inverse rates, no nearest-date borrowing, no invention.
- Status: DECIDED (implemented in code/finance/currency.py)
- Context: empirical proof over the full participant dataset (Phase 2): the only conversion pairs actually required are EUR->USD (16 events), EUR->ZAR (20), USD->EUR (22), USD->IDR (28), USD->INR (53) — ALL five have direct rate rows in exchange_rates.csv. Chaining is unnecessary for this dataset.
- Alternatives: chain composition (unnecessary now; documented future option if organizers add data requiring it); inverse-rate math (rejected — not needed, not officially provided).
- Why: simplest deterministic policy fully covering the real data; hard failure beats silent guessing.
- Trade-offs: an organizer dataset update adding a pair without direct rates raises errors — visible immediately (risk R23), fixable deliberately.
- Evidence/source: AGENTS.md section 6.1; exchange_rates.csv; Phase 2 empirical pair analysis.
- Revisit condition: official dataset adds a conversion pair lacking a direct rate.

