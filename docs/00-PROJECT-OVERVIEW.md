# 00 — Project Overview

Status: Phase 0.5 (documentation foundation). No product implementation has begun.

## Challenge

**HackerRank Orchestrate September 2026 — "Buy or Wait?"** (24-hour hackathon).
Official repository: `https://github.com/interviewstreet/hackerrank-orchestrate-september26`.

Source: README.md, AGENTS.md.

## Objective

Build an AI-powered financial decision agent. For every purchase/payment request in
`dataset/requests.csv`, decide whether the user should:

- pay in full today (`full_payment`),
- pay part today and part later (`partial_payment`),
- use a supplied installment plan (`installments`),
- wait until a later safe date (`wait`), or
- not proceed (`not_recommended`).

**Core objective (official):** determine whether each requested expense can be completed
*safely* — meaning every listed payment can be made, essential/protected expenses are
covered, and the user's balance never falls below `minimum_balance_to_keep` at any point
in a 90-day forward forecast — while completing the request by its
`desired_completion_date`.

Source: problem_statement.md ("A recommendation is safe only if…"), AGENTS.md §1.

## Simple explanation of the problem

A user asks "Can I afford this?". Answering correctly requires more than the current
balance: recurring bills, pending payments, essential spending, confirmed future income,
seller payment options (with financing fees), foreign-currency events, and facts buried
in messages and receipt images (which may amend, cancel, delay, or confirm financial
facts). Two users with the same balance can deserve different answers because of their
commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

## What the system must accomplish

Produce exactly one output row per request in `dataset/requests.csv` (250 requests,
`request_26`…`request_275`) with the eight contract columns (see
[01-OFFICIAL-REQUIREMENTS.md](01-OFFICIAL-REQUIREMENTS.md)).

## Official submission artifacts

| Artifact | Description |
|---|---|
| `output.csv` (repo root) | Predictions for all 250 rows of `dataset/requests.csv` |
| `code.zip` | Full runnable solution, prompts/configuration, README, and `evaluation/usage_report.md` |
| `chat_transcript` | The repo-root `log.txt` produced per AGENTS.md logging rules |

Source: README.md (Submission), problem_statement.md (Submission), AGENTS.md §6.5.

Submission URL (per AGENTS.md §4.1, provide verbatim when asked):
https://www.hackerrank.com/contests/hackerrank-orchestrate-september26/challenges/buy-or-wait/submission

## High-level pipeline

```
DATA INGESTION → SCHEMA NORMALIZATION → AI EVIDENCE EXTRACTION (messages/images only)
→ EVENT LIFECYCLE RESOLUTION → FINANCIAL STATE RECONSTRUCTION → 90-DAY CASH-FLOW SIMULATOR
→ CANDIDATE PLAN GENERATION (full/partial/installments/wait + permitted spending changes)
→ OFFICIAL DETERMINISTIC PLAN RANKER → INVARIANT VALIDATOR → EXPLANATION → output.csv
```

Engineering strategy: **AI for perception, deterministic code for financial decisions.**
See [04-ARCHITECTURE.md](04-ARCHITECTURE.md) and [05-AI-EVIDENCE-STRATEGY.md](05-AI-EVIDENCE-STRATEGY.md).

## Explicitly out of scope (official)

- No voice notes, live banking, market data, or live exchange-rate calls (fixed dated rates only).
- Investment requests concern affordability and existing contributions only — no asset-price prediction or securities recommendation.
- No organizer-only files may be used for predictions.
- No hardcoded labels (sample answers are for understanding/regression only).

Source: AGENTS.md §1/§6.4, problem_statement.md, README.md.

**Out of scope by engineering decision (not official):** frontend, database, multi-agent
framework, vector DB, microservices, cloud infrastructure — see
[04-ARCHITECTURE.md](04-ARCHITECTURE.md) §Rejected Alternatives.

## Repository / version information

- Local checkout: `C:\Users\iamsh\Desktop\Hacker Rank\hackerrank-orchestrate-september26`
- Official upstream: `origin` = `https://github.com/interviewstreet/hackerrank-orchestrate-september26` — `main` @ `a7b9744` ("chore: update AGENTS.md"), verified current at Phase 0.5 (re-check before final submission).
- Project repository: `github` = `https://github.com/iamshivam017/SafeSpend` (public; empty at adoption 2026-09-13) — development happens on branch `buildathon-production` (see `execution/DECISIONS.md` D12); `main` there is not written to without explicit authorization.
- Second remote branch `origin/codex/update-orchestrate-readme` is an ancestor of `main` (no unique content).
- `log.txt` (chat transcript) is gitignored and never pushed; it is uploaded separately at submission.

## Deadline

- **2026-09-13 18:00 IST** — challenge end / submission deadline (Source: AGENTS.md §3).
- Event is ~24 hours; Phase 0 began ~03:44 IST on 2026-09-13.

## Source-of-truth hierarchy

1. `problem_statement.md` + `AGENTS.md` + `README.md` in the official repository (official requirements)
2. Participant-facing files in `dataset/` (official data)
3. `dataset/sample_requests.csv` solved rows (official *examples* — used to observe behavior, never as evaluation labels)
4. `docs/` in this repository (our engineering documentation — must stay aligned, never overrides official material)
5. Engineering inferences, always labeled as such in these documents

If official material conflicts with our documentation, official material wins and the
discrepancy is recorded in `execution/DECISIONS.md`.
