# 06 — Edge Cases and Risk Register

Probability: Low/Med/High. Impact: Low/Med/High (impact on final score).
Status: Open / Mitigated / Closed. Tests reference 07-TESTING-AND-EVALUATION.md test IDs.

| ID | Risk / issue | Source | P | I | Detection | Mitigation | Tests | Status |
|---|---|---|---|---|---|---|---|---|
| R01 | Pending debit omitted from reservation inflates asp | official rule R4; 71 pending rows | Med | High | unit test with known pending debit | lifecycle stage reserves all pending debits regardless of date | T-pend-debit | Open |
| R02 | Pending credit counted early (bonus/refund/investment gain) | official R5; messages promise future bonuses (message_03 "awaiting final approval") | High | High | regression vs samples | count credits only when `status=settled` | T-pend-credit | Open |
| R03 | Cancelled/failed event still projected (incl. cancelled→retried pairs double-counted) | official R6; 22 cancelled + 21 failed rows; observed pair event_100→event_101 | Med | High | lifecycle unit tests | cancelled/failed excluded; retried child counted once via linked_event_id | T-cancel, T-lifecycle | Open |
| R04 | Amendments misread (salary change effective date, reduced salary) | official R14; 126 employer messages | High | High | AI extraction tests + gold message set | structured claim contract w/ effective_date; conflict order | T-amend | Open |
| R05 | Linked lifecycle mishandled: refund children, investment purchase+valuation pairs | official R8; 58 linked rows | Med | High | unit tests on observed pairs | refund settled = cash in; valuation unrealized = never cash; purchase settled = already in ledger | T-unrealized, T-refund | Open |
| R06 | Duplicate representations of same transaction double-counted | official R6/R14 ("duplicate records") | Med | Med | dedup audit per user | dedup on (user, category, direction, amount, dates, lifecycle link) with conflict order | T-dup | Open |
| R07 | Blank amount treated as zero or image misread (gross vs net pay) | official R10; image_01 shows both | Med | High | 16-case image test set | AI extraction + provenance quote; net-pay heuristic on pay slips; never zero | T-image | Open |
| R08 | Conflicting evidence resolved in wrong order | official R14 | Med | High | scenario tests | implement R14 order literally | T-conflict | Open |
| R09 | Inconsistent/blank dates (10 blank settlement_dates, all unrealized) | dataset | Low | Low | parser warnings | only cash-state rows need settlement dates; validate | T-dates | Open |
| R10 | FX conversion at wrong date or wrong direction; missing direct pair | official R12; 5 directional pairs only | Med | High | FX unit tests per pair | settlement-date lookup + directional match; chain conversion fallback (03 §E4) | T-fx | Open |
| R11 | Recurrence mis-inferred (one-time spike projected, or recurring salary missed) | official R9; observed message_02 one-time adjustment | **High** | **High** | 25-sample regression + per-user audit | deterministic gap-bucket detection + day-of-month clustering (D10 rev.2); monthly-commitments-only projection; sample-plan safety audit as oracle (D22) | 10 recurrence tests + audit | Mitigated (Phase 2.1 audit: 0 contradictions; Phase 5 calibration pending) |
| R12 | Spending change targets a protected/non-flexible event | official R27; README checklist | Med | High | validator | eligibility filter: recurring + flexibility≠fixed + category in user's willing list + not protected | T-changes | Open |
| R13 | Reduce below `minimum_allowed_amount` | dataset field; sample O4 | Med | Med | validator | floor at minimum_allowed_amount; else reduce not allowed | T-reduce-floor | Open |
| R14 | Installment plan doesn't exactly match supplied option | official R23 | Med | High | validator | plans built only from option rows (dates = first + k×freq; amounts = payment_amount) | T-installment | Open |
| R15 | Preference violation: method not in `payment_methods_user_will_consider`; or `wait` recommended to a user who rejects full_payment | official R21 | Med | High | validator | eligibility filter before ranking | T-pref | Open |
| R16 | `max_installment_months` misapplied (blank = never; month convention ambiguous) | official R24; 03 §E2 | High | Med | 25-sample regression | blank → no installments; span ≤ N months (30d months, pin via regression) | T-maxmonths | Open |
| R17 | Partial-payment rule violation (extra/missing payment, sum ≠ requested, second payment after deadline, user rejects partial) | official R22 | Med | High | validator | enforce all six R22 conditions exactly | T-partial | Open |
| R18 | Same-day ordering: credit counted before same-day debit breaks floor | official safer-interpretation R14(4); 03 §E5 | Med | Med | simulator unit test | debits before credits within a day | T-sameday | Open |
| R19 | Prompt injection in message/image text obeys embedded instructions | official R35 | Low | High | adversarial test set | evidence-as-data prompts; claim-type whitelist; injection flag; deterministic downstream | T-injection | Open |
| R20 | Missing image file despite images.csv row; missing message | official R11 ("do not invent evidence") | Low | Med | file-existence check pre-run | skip evidence, log; blank amount → financially safer interpretation, flagged | T-missing-image | Open |
| R21 | Malformed AI JSON / hallucinated amounts | engineering | Med | High | schema validation + retry + provenance quotes | retry once → fallback skip; amounts re-verified against document span | T-ai-malformed | Open |
| R22 | Output formatting: wrong column order, decimal locale, missing rows, `|` separators, date formats | official R31/R32; README checklist | Med | High | end-to-end validator | writer emits exact header; Decimal→plain string; 250-row count check | T-output | Open |
| R23 | Stale official repo mid-event (organizers push updates) | event logistics | Med | High | `git fetch` before final submission | re-read official docs; update affected docs/tests per maintenance rule | process | Open |
| R24 |asp/plan disagreement: `earliest_date_for_full_payment` computed with spending changes (must be WITHOUT) | official R16/R17; sample O10 | Med | High | validator: recompute earliest from unmodified simulator | separate simulator runs: with-changes (plan) vs without-changes (asp/earliest) | T-earliest | Open |
| R25 | Timebox exhaustion (14h remaining at Phase 0.5) | logistics | Med | High | phase gates in 09 | deterministic-first ordering: core engine before AI polish; cache evidence | process | Open |

Highest-leverage risks for score: R11 (recurrence), R02, R04, R24, R16.
