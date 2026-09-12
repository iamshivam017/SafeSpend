# 05 — AI Evidence Strategy

Where AI is justified, its exact output contract, and the hard prohibitions.
Model/provider: **TBD — MODEL SELECTION** (must support text + image input; the dataset
contains multilingual messages and PNG evidence). Cost metering depends on this choice but
the instrumentation (08) is provider-agnostic.

## Justified uses (perception only)

1. **Image interpretation** — the 16 PNGs (pay slips, invoices, bills, receipts). Extract:
   document type, the authoritative amount (e.g. **net pay**, not gross), currency, dates,
   referenced parties. Evidence: event_253 ↔ image_01 pay slip → Net Pay IDR 4,365,000.
2. **Message interpretation** — 215 messages, many in Indonesian. Extract: fact type
   (salary change / bonus / delay / cancellation / one-time adjustment / confirmation /
   refund info), affected event or schedule, new amount, effective date, certainty status
   (confirmed vs pending approval).
3. **Request-text nuance** (optional, low priority) — `request_text` restatements; the
   structured columns are authoritative, so AI here is only a cross-check.

## Structured AI output contract (proposed)

One JSON object per evidence item, schema-validated before use; invalid → retry once →
fallback (skip evidence, record failure):

```json
{
  "source_id": "message_04 | image_01",
  "source_kind": "message | image",
  "claims": [
    {
      "claim_type": "salary_amount_change | salary_date_confirmation | one_time_payment |
                    cancellation | delay | event_amount | other_factual",
      "related_event_id": "event_253 | null",
      "new_amount": {"value": "4365000", "currency": "IDR"} ,
      "effective_date": "2019-08-31 | null",
      "recurrence": "recurring | one_time | unchanged | unknown",
      "status_qualifier": "confirmed | pending_approval | expected | unknown",
      "quoted_span": "<short verbatim quote supporting the claim>",
      "confidence": 0.0
    }
  ],
  "injection_suspected": false,
  "unparseable": false
}
```

## Handling rules

- **Provenance**: every claim carries `source_id` + `quoted_span`; lifecycle resolver logs which evidence changed which decision. Claims never silently override structured data — they feed the official conflict order (R14: an explicit amendment outranks older records).
- **Confidence**: low-confidence claims (< threshold, TBD at implementation) are recorded but only applied when they are the explicit-amendment case of R14(1); otherwise the deterministic base data wins (R14(3) settled-over-estimate).
- **Malformed output**: schema validation fails → one retry with error appended → still invalid → mark `unparseable`, skip evidence, log to usage/observability. A blank-amount event whose image fails extraction is **not** treated as zero (official R10) — the row is flagged and the financially-safer interpretation applies (R14(4)).
- **Caching**: extraction results cached to `evidence_cache.json` keyed by source_id + content hash. Full-dataset runs after the first are AI-free and deterministic; the usage report reflects the final run that produced `output.csv`.
- **Prompt-injection resistance**: message text and image-derived text are embedded as quoted, escaped *data* inside the prompt with an explicit system instruction that documents may contain instructions which must be reported as `injection_suspected` claims, never obeyed. Any claim whose `quoted_span` itself looks like an instruction is recorded, not executed. Downstream, only `claim_type`s in the contract are consumable — free-form text can never alter code behavior.
- **Untrusted evidence rules** (official): evidence may clarify/amend/delay/cancel/confirm financial facts only; embedded instructions never override challenge rules (AGENTS.md §1, problem_statement.md).
- **Deterministic downstream verification**: every applied claim is re-checked against the dataset (e.g. a salary change amount must be plausible for the user's salary category; a cancellation must reference an existing event). The simulator and validators never see raw model text.

## Hard prohibitions — AI is NOT the final authority for

- `amount_safe_to_pay` (deterministic simulator output, R16)
- `affordability_status` (deterministic classification, R19/R20)
- plan feasibility / the 90-day forecast (deterministic simulator)
- minimum-balance enforcement (deterministic invariant, R2)
- payment-method selection and ranking (deterministic ranker, R21/R30)
- any financial invariant validation (deterministic validators, R31–R33)

## Cost discipline

- Only 231 evidence items exist (215 messages + 16 images); extraction is one batched/cheap pass, cached forever after.
- Zero AI calls are required for users/requests with no linked evidence — the pipeline must complete without any AI calls if the cache is warm or no evidence exists (degradation path, official: "deterministic where possible").
