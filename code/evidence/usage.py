"""Evidence-extraction usage tracking (Phase 4, directive section 10).

Records every extraction action honestly. Phase 4's extraction used:
- a deterministic message parser (no model calls, zero cost);
- a one-time coding-agent vision transcription of the 16 images (agent =
  the interactive ZCode/GLM harness during development; no external API,
  zero billed cost), cached in code/evidence/cache.json.

No token/cost values are fabricated: fields that do not apply are recorded
as 0/not-applicable, never as invented numbers.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

USAGE_LOG = Path(__file__).resolve().parent / "usage_log.jsonl"


def record(provider: str, model: str, evidence_id: str, context: str,
           input_tokens: int = 0, output_tokens: int = 0, latency_ms: int = 0,
           estimated_cost: str = "0.00", cache_hit: bool = False,
           method: str = "deterministic") -> None:
    entry = {
        "ts": datetime.now().isoformat(),
        "provider": provider,
        "model": model,
        "evidence_id": evidence_id,
        "context": context,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "estimated_cost": estimated_cost,
        "cache_hit": cache_hit,
        "method": method,
    }
    with USAGE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def summarize() -> dict:
    if not USAGE_LOG.exists():
        return {"entries": 0}
    entries = [json.loads(line) for line in
               USAGE_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_method: dict[str, int] = {}
    for e in entries:
        by_method[e["method"]] = by_method.get(e["method"], 0) + 1
    return {"entries": len(entries), "by_method": by_method,
            "total_input_tokens": sum(e["input_tokens"] for e in entries),
            "total_output_tokens": sum(e["output_tokens"] for e in entries),
            "total_estimated_cost": sum(float(e["estimated_cost"]) for e in entries)}
