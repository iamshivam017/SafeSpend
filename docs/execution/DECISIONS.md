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

## D6 — Event-ordering policy (same-day)
- Date: 2026-09-13
- Decision: within a simulation day, apply debits (incl. plan payments) before credits.
- Status: DECIDED (validated in Phase 5)
- Context: official conflict rule (4) "financially safer interpretation" when order is otherwise unspecified.
- Alternatives: credits-first (optimistic, rejected), interleaved (undefined).
- Chosen approach: debits-first.
- Why: conservative floor enforcement.
- Trade-offs: may understate same-day capacity; samples will confirm.
- Evidence/source: problem_statement.md conflict rules; docs/03 §E5.
- Revisit condition: if 25-sample regression shows credit-first behavior (STATUS: OPEN until pinned).

## D7 — Model / provider selection
- Date: —
- Decision: **STATUS: OPEN** (TBD — MODEL SELECTION). Requirement: text+image input, JSON- reliable output, low cost; usage metering is provider-agnostic.
- Context: 215 messages (multilingual) + 16 images to extract; one-time cached pass.
- Alternatives considered: pending.
- Chosen approach: pending.
- Why: —
- Trade-offs: —
- Evidence/source: docs/05, docs/08.
- Revisit condition: decide at Phase 4 start; record price table then.

## D8 — `max_installment_months` month convention
- Date: —
- Decision: **STATUS: OPEN**. Working interpretation (docs/03 §E2): option span ≤ N × 30 days; to be pinned by the 25-sample regression before Phase 6.
- Context: official field semantics not defined beyond rejection rule.
- Evidence/source: AGENTS.md §6.1; sample user_02 (max 7, accepted 3×30d option).
- Revisit condition: Phase 5 regression outcome.

## D9 — Reduce-target policy (spending changes)
- Date: —
- Decision: **STATUS: OPEN**. Working interpretation (docs/03 §E3): minimal sufficient reduction, floored at `minimum_allowed_amount`; samples O4 show reductions landing exactly on the floor — regression will discriminate minimal-vs-floor.
- Evidence/source: sample_requests.csv rows 11/21.
- Revisit condition: Phase 5 regression outcome.

## D10 — Recurrence policy
- Date: —
- Decision: **STATUS: OPEN** (core approach decided, parameters not). Approach: periodicity detection on same user+category+direction settled history; one-time flags from evidence; conservative amount selection. Exact conservative rule (last vs max vs trimmed mean) pinned in Phase 5.
- Evidence/source: official R9; observed message_02 one-time adjustment; user_03 salary history.
- Revisit condition: Phase 5 regression outcome.

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
- Chosen approach: corrected docs/00 §Core objective, docs/01 §2/§3, docs/03 R17, docs/07 §3; Phase 1 validators will assert the one-directional form.
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
- Evidence/source: README.md quick start; AGENTS.md §6.6.
- Revisit condition: any dependency requiring stdlib `code`, or organizer push changing the entry-point convention.

## D15 — Test runner: stdlib unittest (no pytest dependency)
- Date: 2026-09-13
- Decision: `python -m unittest discover -s tests -v`; tests are unittest classes (also pytest-compatible if pytest is present locally).
- Status: DECIDED
- Context: dependency discipline (Phase 1 §26): stdlib suffices for xAssert-style unit tests.
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
- Evidence/source: problem_statement.md (silent on rounding); Phase 1 directive §6.
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
- Evidence/source: Phase 1 directive §21, §8; user Phase 1 prompt.
- Revisit condition: organizer dataset schema change (then extend header sets deliberately).

## D11 — FX chain conversion fallback
- Date: 2026-09-13
- Decision: if no direct same-date rate row exists for an event's currency pair, compose a chain through an intermediate currency using same-date rows; if impossible, flag and treat financially safer.
- Status: DECIDED (mechanism; necessity confirmed during Phase 6 data audit)
- Context: only 5 directional pairs exist; events occur in all 5 currencies for all home currencies.
- Alternatives: drop such events (silently wrong), invent rates (forbidden).
- Chosen approach: chain composition.
- Why: official rule fixes rate *source* and *date*, not path; chaining stays within provided data.
- Trade-offs: path choice ambiguity → prefer the chain minimizing hops then maximizing rate-date exactness.
- Evidence/source: exchange_rates.csv pair census (docs/02); AGENTS.md §6.1.
- Revisit condition: if sample regression reveals per-pair ground truth contradicting chains.
