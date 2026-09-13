# Usage Report — Final 250-Request Production Run

## Run Identity

- **Date/Time**: 2026-09-13 (Phase 6 final production run)
- **Production commit SHA**: 95a722b (Phase 3 final) -> 8cdf4dd (Phase 5 freeze) -> Phase 6 serialization
- **output.csv SHA-256**: `8d948c5f42b834588445c1f492892ea71342b04503d185f42c37d420ebd1925b`
- **Request count**: 250

## External Model Providers Invoked in Final Run

**None.**

## Explanation

The production architecture makes zero external model/inference calls during the final run:

- **Message interpretation** is performed by a deterministic EN/ID regex parser (`code/evidence/message_parser.py`), not by an LLM. The 215 messages are parsed into typed claims using whitelisted patterns; no model inference is invoked at runtime.
- **Image evidence** is loaded from a pre-validated, committed cache (`code/evidence/cache.json`) containing amounts transcribed during the Phase 4 development phase by the interactive coding agent. No new image extraction is invoked during the production run.
- **All financial decisions** (ASP, earliest date, candidate selection, ranking, status mapping) are computed by deterministic Python code (`code/finance/`, `code/planning/`). No AI/LLM/VLM participates in any financial decision.

## Model/Token/Cost Summary

| Metric | Value |
|---|---|
| External model providers invoked | 0 |
| Model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Average tokens/request | 0 |
| Estimated total cost | 0.00 |
| Estimated cost/request | 0.00 |

## Development-Time Note

During Phase 4 development, the 16 evidence images were transcribed by the interactive coding agent's own vision capability (one-time, zero external API cost). The results were cached in `code/evidence/cache.json` and are loaded from that cache during production runs. This development-time activity is **not** attributed to the final production run, which makes zero external inference calls.

## Determinism

Two consecutive fresh-process runs produced **byte-identical** `output.csv` files (SHA-256 match), confirming full determinism of the pipeline.
