# 08 — Token, Cost, and Observability

Purpose: support the mandatory `evaluation/usage_report.md` (official requirement,
AGENTS.md §6.5, README.md, problem_statement.md) with measured — never fabricated — values.

## Requirement (official)

The report must summarize the **final full-dataset run that produced the submitted
`output.csv`**: model providers and names; model calls; input tokens; output tokens; total
and average tokens per request; estimated total and per-request cost; per-model AND overall
totals if more than one model is used. No API keys, credentials, or sensitive configuration.

## Instrumentation design (proposed module `code/usage.py`)

- **Metering wrapper** around every AI call. Records one JSONL row per call:
  ```json
  {"ts": "...", "provider": "...", "model": "...", "purpose": "image|message",
   "source_id": "image_01", "input_tokens": 0, "output_tokens": 0, "cache_hit": false,
   "latency_ms": 0, "status": "ok|retry|failed", "attempt": 1}
  ```
  Token counts come from the provider's usage field in the response — never estimated
  locally unless the provider omits them, in which case the estimation method is stated in
  the report.
- **Persistence**: `evaluation/usage_raw.jsonl` (gitignored-optional artifact, kept out of
  code.zip if it contains sensitive metadata; the aggregate report contains no secrets).
- **Aggregation** (`usage.py report`): reads the JSONL rows belonging to the final
  full-dataset run (run tagged with a `run_id`; final run = the one whose outputs are in
  `output.csv`), and emits `evaluation/usage_report.md`:

| Section | Content |
|---|---|
| Per-model table | provider, model, calls, input tokens, output tokens, total tokens, est. cost |
| Overall totals | calls, input, output, total tokens |
| Per-request averages | total tokens ÷ 250; cost ÷ 250 |
| Failures/retries | extraction failures, retry counts, cache hits |
| Cost basis | model price table (input/output per 1M tokens) with the date it was taken, stated explicitly |

- **Caching**: evidence extraction results are cached (`evidence_cache.json`). A cached
  call is recorded with `cache_hit: true` and **0 billed tokens** (no API call made). The
  final full-dataset run should therefore show a small, honestly-reported token count for
  the extraction pass only; if the final run is executed on a warm cache the report says so
  explicitly.
- **Model/provider**: **TBD — MODEL SELECTION**. Price table entry is added when chosen.
- **Latency**: recorded per call (useful for debugging), reported only as aggregate max/mean
  if useful — not an official requirement.

## Rules

1. Never fabricate token/cost values; only measured values from the actual final run appear
   in the final report.
2. No secrets in the report or raw logs (API keys live in environment variables only —
   official constraint).
3. If the final `output.csv` is regenerated, the usage report is regenerated from the new
   run's `run_id` — the two artifacts must always correspond (official requirement).
4. Zero-AI degradation path: if the final run makes no AI calls (warm cache), the report
   states this and shows the cached-call counts.

## Other observability

- Per-request decision trace (optional debug mode): chosen plan, ranking key values,
  simulator minimum balance, evidence claims applied — written to a debug log, not shipped
  except when diagnosing sample mismatches.
- Extraction failure counters feed risk-register R21 monitoring.
