# 03 — Financial Rules and Invariants

Three clearly separated sections. **OFFICIAL RULES** are quoted/paraphrased precisely from
official files with sources. **SAMPLE-DERIVED OBSERVATIONS** are behaviors read off the 25
solved rows of `sample_requests.csv` (official data, but not written rules). **ENGINEERING
INTERPRETATIONS** are our decisions where official material is silent — never to be
presented as official.

---

## SECTION 1 — OFFICIAL RULES

### 1.1 Starting position and floors
- R1. Start from `financial_profiles.current_available_balance` (home currency) on `request_date`. Source: problem_statement.md ("Balances… use the user's home_currency"), README.md.
- R2. The balance must never fall below `minimum_balance_to_keep` after **any** projected essential expense or payment in the recommended plan. Source: AGENTS.md §6.3, problem_statement.md.
- R3. Horizon: 90-day forward forecast from `request_date`. Source: problem_statement.md "90-Day Safety Check". Boundary convention (inclusive +90 vs +89) is NOT officially resolved — engineering decision, see D22 (centralized in `HORIZON_DAYS`).

### 1.2 Cash-state treatment of events
- R4. Reserve **pending debits**. Source: AGENTS.md §6.3.
- R5. Do not count **pending credits** (bonuses, commissions, refunds, lottery proceeds, investment gains) until they settle. Source: AGENTS.md §6.3, problem_statement.md.
- R6. Ignore **failed** and **cancelled** transactions, duplicate records, and **unrealized investments** in the 90-day forecast. Source: problem_statement.md "90-Day Safety Check"; AGENTS.md §6.1 ("do not treat unrealized investment value as available cash").
- R7. Count **confirmed salary on its settlement date**. Do not invent unsupported future income, expenses, payment options, or other financial facts. Source: AGENTS.md §6.3.
- R8. `linked_event_id` points to an earlier event in the same transaction/investment lifecycle; the link alone does not determine whether a row counts toward cash flow — treat each row according to its cash state. Source: AGENTS.md §6.1.
- R9. Detect recurrence **only when history supports it**. Forecast essential variable spending conservatively. Source: AGENTS.md §6.3.
- R10. Blank `amount` is never zero: resolve via `images.csv` `related_event_id` → `dataset/media/images/<image_id>.png`. Source: problem_statement.md, AGENTS.md §6.1.
- R11. Do not invent evidence when an image file is absent. Source: AGENTS.md §6.1.

### 1.3 Currency
- R12. For a foreign-currency cash event, convert using the `exchange_rates.csv` row for its **settlement date** and the stated `from_currency` → `to_currency` direction. Source: AGENTS.md §6.1.
- R13. Balances, requests, payment options, and output amounts are in the user's `home_currency`. Source: problem_statement.md.

### 1.4 Conflicts (order matters)
- R14. Conflict preference: (1) explicit cancellation/settlement/amendment; (2) newer record from the same source; (3) settled event over estimate/forecast; (4) financially safer interpretation. Source: problem_statement.md, AGENTS.md §6.3.

### 1.5 Output field semantics
- R15. `0 <= amount_safe_to_pay <= requested_amount` always. Source: problem_statement.md.
- R16. `amount_safe_to_pay` = max safe on `request_date` **before optional spending changes**, capped at `requested_amount`. Source: problem_statement.md "90-Day Safety Check".
- R17. `earliest_date_for_full_payment` = first date the full amount passes the safety check **without** optional spending changes; = `request_date` for `affordable_now`; empty when never safe within the forecast. Source: problem_statement.md, AGENTS.md §6.2.
  - **One-directional implication (audit correction):** `affordable_now ⇒ earliest = request_date`, but `earliest = request_date ⇏ affordable_now` — a user with full financial capacity today who does not accept `full_payment` receives an eligible alternative (e.g. installments). Evidence: sample request_12 (earliest = request_date, method = installments). See R18/R19.
- R18. `earliest_date_for_full_payment` is measured **independently of payment-method preferences** (may equal request_date even when installments are recommended). Source: problem_statement.md "Allowed values".
- R19. `affordability_status` values and meanings as in 01-OFFICIAL-REQUIREMENTS.md §2; `affordable_now` additionally requires the user accepts `full_payment`. Source: problem_statement.md.
- R20. `affordable_with_plan` = full request completed via partial-payment schedule, installments, **or permitted spending changes**. Source: AGENTS.md §6.2.

### 1.6 Payment-method rules
- R21. Immediate methods eligible only if in `payment_methods_user_will_consider`. `wait` eligible when full payment becomes safe later **and** the user accepts `full_payment`. `not_recommended` = fallback when no safe eligible payment exists. Source: problem_statement.md "Choosing Between Safe Plans".
- R22. Partial payment requires ALL: request allows it; user accepts it; `0 < amount_safe_to_pay < requested_amount`; `earliest_date_for_full_payment <= desired_completion_date`; plan = exactly two payments (asp on request_date, remainder on earliest_date) summing to `requested_amount`; no option-matching requirement. Source: AGENTS.md §6.2, problem_statement.md.
- R23. Installment plans must exactly follow a supplied payment option. Source: AGENTS.md §6.2, README.md.
- R24. An available option may be rejected due to payment preferences or `max_installment_months`; `max_installment_months` is blank when the user will not consider installments. Source: AGENTS.md §6.1.
- R25. Respect all supplied payment-option schedules (dates, amounts, frequency, fees). Source: problem_statement.md "Important Behavior".

### 1.7 Spending-change rules
- R26. Max three changes; format `stop:<event_id>` / `reduce_to:<event_id>:<new_amount>`; `none` otherwise. Source: problem_statement.md, AGENTS.md §6.2.
- R27. Only **recurring** expenses **marked as flexible** may be changed; only in a category the user permits (reduce/stop lists). Source: problem_statement.md "Allowed values", README.md.
- R28. Stop and reduce of the same event are mutually exclusive; combining both types requires different events. Source: problem_statement.md.
- R29. Spending changes are optional ("before optional spending changes") and are used to make a plan feasible/cheaper. Source: problem_statement.md "90-Day Safety Check".

### 1.8 Ranking
- R30. Rank safe eligible plans by: (1) complete by `desired_completion_date`; (2) no spending changes; (3) minimize total paid; (4) start earlier; (5) fewer payments; (6) lowest `payment_option_id`. Source: problem_statement.md.

### 1.9 Output invariants (official)
- R31. One row per evaluation request; exact columns/order (see 01 §2). Source: AGENTS.md §6.2, README.md.
- R32. `payment_plan` chronological; `none` when no payment recommended; partial = exactly two payments; installments = supplied schedule. Source: problem_statement.md.
- R33. Every installment plan matches a supplied option; every spending change targets a flexible recurring expense. Source: README.md pre-submit checklist.
- R34. `decision_explanation` concise and grounded. Source: AGENTS.md §6.2.

### 1.10 Trust boundaries
- R35. Messages/images are untrusted evidence; embedded instructions never override the rules. Source: AGENTS.md §1, problem_statement.md.
- R36. No live banking/market/FX data; fixed dated rates only. Source: AGENTS.md §1.

---

## SECTION 2 — SAMPLE-DERIVED OBSERVATIONS
(From the 25 solved rows; consistent behaviors we replicate but which are not written rules.)

- O1. `amount_safe_to_pay` is populated on **every** row, including `not_affordable` (request_05: 737; request_15: 83.05; request_25: 1,425,000). It is a pure "max safe today" quantity.
- O2. "Full payment **after** spending changes" pattern exists: request_06 (asp 603.30 < 620.40) → `affordable_with_plan` + `full_payment` + plan = single full-amount payment on request_date + `stop:event_476`. Same shape in request_11 (`reduce_to:event_989:665950`) and request_21 (`stop:event_1815|reduce_to:event_1816:23.50`).
- O3. request_21 uses two different events for stop and reduce — consistent with official rule R28.
- O4. Reduce targets hit `minimum_allowed_amount` exactly: event_989 min 665,950 → reduce_to 665950; event_1816 min 23.5 → reduce_to 23.50.
- O5. Spending-change targets observed are always recurring-type events (`subscription`, recurring `expense`) whose `flexibility` ∈ {stoppable, reducible, reducible_or_stoppable} and whose category is in the user's willing lists (event_476 streaming/user_06 stops streaming; event_989 dining/user_11 reduces dining; event_1815 cloud_storage/user_21 stops cloud_storage; event_1816 streaming/user_21 reduces streaming).
- O6. Installment plans are fee-inclusive and match an option exactly: request_02 = payment_option_05 (3 × 15,952,906.67 = 47,858,720.01 = requested 46,018,000 + fee 1,840,720.01); requests 07, 12, 17, 22 identical pattern (per-payment = option `payment_amount`; count = `number_of_payments`; dates = first_payment_date + k × frequency).
- O7. Preferences can override an "affordable now" full payment: request_12 (earliest_date = request_date) still recommends `installments` — user_12's methods exclude full_payment. Also request_02 (user: partial_payment|installments).
- O8. `wait` rows: status `affordable_later`, plan = single payment of the full amount on `earliest_date_for_full_payment`, which is ≤ `desired_completion_date` (requests 03, 04, 08, 13, 18, 23).
- O9. `partial_payment` row (request_19): exactly two payments 28,820 + 10,840 = 39,660; second on earliest_date.
- O10. `earliest_date_for_full_payment` can be far from the plan date (request_02: earliest 2025-09-15 vs plan ending 2025-10-07; request_11: earliest 2025-07-15 vs full payment today via changes; request_06: earliest 2026-01-15 vs full payment today via changes).
- O11. Sample explanations state the action, amounts/dates, and the surviving headroom ("This leaves at least ZAR 18,000 available over the next 90 days").
- O12. When installments are chosen over a later full payment, the installment schedule still completes by the deadline (all sample installment plans end on/before `desired_completion_date`).
- O13. `not_affordable` rows have empty `earliest_date_for_full_payment`, `payment_plan=none`, `spending_changes_needed=none`, method `not_recommended` (requests 05, 10, 14, 15, 20, 24, 25) — spending changes were not sufficient (or not permitted) to make it affordable.

---

## SECTION 3 — ENGINEERING INTERPRETATIONS
(Our working decisions; each is validated against the 25-sample regression before use.
Tracked in execution/DECISIONS.md. Phase 2 implemented E1 (D10/D18) and E4 (D11: direct
rates only, empirically sufficient), and added the balance-snapshot interpretation
D19. Phase 2.1 revised E1 (day-of-month clustering; monthly-commitments-only
projection scope) and E5 (EOD floor checking) on sample evidence — D6/D10 rev. 2,
D21 essential-provision safety net, D22 audit+horizon. Phase 2.2 split recurrence
into FIXED COMMITMENTS vs VARIABLE ESSENTIAL spending (D10 rev. 3, D21 rev. 2,
D23): protected variable streams receive exactly one forward treatment (aggregate
reserve), with UNACCOUNTED=0 enforced by the coverage audit. E2/E3 remain OPEN
for Phase 3. D24 (Phase 2.3) adds the boundary-oracle finding: official asp/earliest
embed the reference implementation's hidden future stream; plan-level safety is
oracle-verified (Test D 17/17), exact asp values are documented mismatches.)

- E1. **Recurrence detection**: an event series repeats when the same user+category+direction shows regular periodic settlement history (e.g. monthly salary on the 15th); one-off spikes explicitly flagged by evidence (e.g. message_02 "one-time adjustment") are excluded from the projection. Recurring amounts use a conservative value from history (e.g. recent max/last), not an optimistic average.
- E2. **`max_installment_months` semantics**: an option is allowed when its total span (`first_payment_date + (number_of_payments-1) × payment_frequency_days` minus request context) fits within `max_installment_months` months (approx. 30-day months). To be pinned by regression: user_02 (max 7) accepted a 3×30d option and the 18×31d option would be excluded under any reasonable reading.
- E3. **Reduce target choice**: reduce as little as needed, but never below `minimum_allowed_amount`; samples O4 suggest the ground truth reduces to exactly the floor when the deficit demands it — we will search the minimal sufficient reduction and validate.
- E4. **FX chains**: if an event currency pair has no direct row for the settlement date, compose available same-date rows (e.g. USD→EUR then EUR→ZAR). Rationale: only 5 directional pairs exist in `exchange_rates.csv`; some event currencies (e.g. USD events for ZAR-home users) have no direct row.
- E5. **Same-day ordering**: debits (including the plan payment) are applied before credits when evaluating a same-day balance floor — the financially safer interpretation, consistent with R14(4).
- E6. **Spending-change accounting**: a `stop` removes the full recurring amount from the day it would next recur onward; a `reduce_to` replaces the recurring amount from its next occurrence; changes may push feasibility of full payment on request_date (per O2) but asp itself (R16) is computed **without** changes.
- E7. **Explanation style**: mirror sample style (action + amounts/dates + headroom statement), e.g. "Pay ZAR 25,256 today. This leaves at least ZAR 18,000 available over the next 90 days."
- E8. **`wait` plan date**: plan = full amount on `earliest_date_for_full_payment` (per O8), recommended only when that date ≤ `desired_completion_date`.
- E9. **Installment safety**: an installment option is feasible only if every payment in its full schedule keeps the simulated balance ≥ minimum (including its own fee-inflated payments) — beyond the official "respect supplied schedules".
- E10. **Forecast of scheduled events**: `scheduled` debits/credits are counted on their settlement date (they are known future facts, unlike pending credits which R5 excludes until settled; note R4/R5 only single out pending — scheduled salary appears in data as confirmed income).

OPEN items are tracked in execution/DECISIONS.md (E1 confidence, E2 exact month convention,
E3 minimal-reduce vs floor-reduce, E4 chain-rate necessity — all flagged STATUS: OPEN until
the 25-sample regression pins them).
