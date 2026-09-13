"""Financial boundary oracle audit (Phase 2.3, EVALUATION-ONLY).

Uses the 25 solved samples as the public oracle to test the simulator's
financial boundaries:

  Test A: zero-payment baseline must not be UNSAFE when official asp > 0
  Test B: paying exactly the official amount_safe_to_pay today must be SAFE
  Test C: simulator-implied max safe today amount vs official asp (delta report)
  Test D: paying requested_amount at the official earliest_date must be SAFE
  Test E: paying one day before the official earliest date must be UNSAFE
  Test F: full-amount-today safety must agree with earliest == request_date

ISOLATION: evaluation-only; production code must never import this module
(AST-enforced by tests). Reads sample answer columns.

KNOWN LIMITATION (documented, D24): the official asp/earliest values were
produced by the reference implementation against its internal future event
stream (the generated true future, including income streams whose history is
too short for participant-side detection). Six candidate projection policies
were tested; none reproduces the non-capped official asp values exactly, with
deltas in both directions. The audit therefore reports deltas transparently
instead of hiding them, and treats the plan-safety audit (Phase 2.1/2.2) plus
the provable monotonicity property as the engine's consistency guarantees.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from decimal import Decimal

from ..config import REPO_ROOT
from ..data_loader import load_all, validate_relationships
from ..errors import SafeSpendError
from ..finance.lifecycle import resolve_lifecycle
from ..finance.recurrence import detect_recurring_patterns
from ..finance.simulator import Payment, SafetyState, simulate
from ..finance.timeline import build_cash_timeline
from ..indexes import Indexes
from ..schemas import SampleRequest


@dataclass
class BoundaryRow:
    request_id: str
    test: str
    official: str
    simulated: str
    minimum: str
    floor: str
    first_violation: str
    verdict: str
    detail: str = ""

    def line(self) -> str:
        return (f"{self.request_id:<12}{self.test:<8}{self.official:>16}"
                f"{self.simulated:>16}{self.minimum:>16}{self.floor:>14}"
                f"{self.first_violation:<12}{self.verdict:<14}{self.detail}")


class BoundaryAuditor:
    def __init__(self) -> None:
        self.bundle = load_all()
        problems = validate_relationships(self.bundle)
        if problems:
            raise SafeSpendError("structural problems: " + "; ".join(problems))
        self.indexes = Indexes.build(self.bundle)
        from ..evidence.apply import collect_claims
        self.all_claims = collect_claims(self.bundle)

    def _state(self, sample: SampleRequest, payments: list[Payment]):
        request = sample.request
        from ..evidence.apply import build_request_state
        profile, lifecycle, patterns, timeline, evidence, unresolved = \
            build_request_state(self.bundle, self.indexes, request,
                                all_claims=self.all_claims)
        sim = simulate(profile, request.request_date, timeline.flows,
                       hypothetical_payments=payments,
                       unresolved_evidence=unresolved, include_trace=False)
        return sim, lifecycle, timeline

    def _resolvable(self, sample: SampleRequest, lifecycle) -> str | None:
        """DEFER reason, or None when Phase 2 can evaluate deterministically."""
        if sample.recommended_payment_method.value == "not_recommended" \
                and not sample.earliest_date_for_full_payment:
            return None  # not_affordable: still boundary-testable (asp > 0 possible)
        return None  # unresolved handling moved into build_request_state

    # Test A/B: zero-payment and official-asp payment
    def test_baseline_and_asp(self) -> list[BoundaryRow]:
        rows = []
        for sample in self.bundle.samples:
            request = sample.request
            profile = self.indexes.profiles_by_user_id[request.user_id]
            lifecycle = resolve_lifecycle(
                self.indexes.events_by_user_id.get(request.user_id, []),
                request.request_date)
            defer = self._resolvable(sample, lifecycle)
            if defer:
                for test in ("A", "B", "C", "F"):
                    rows.append(BoundaryRow(request.request_id, test, "-", "-", "-",
                                            "-", "-", "DEFERRED", defer))
                continue

            sim0, _, _ = self._state(sample, [])
            asp = sample.amount_safe_to_pay

            # Test A: zero-payment baseline
            if asp > 0 and sim0.state is SafetyState.UNSAFE:
                rows.append(BoundaryRow(
                    request.request_id, "A", str(asp), "UNSAFE",
                    str(sim0.minimum_projected_balance), str(profile.minimum_balance_to_keep),
                    sim0.first_floor_violation_date.isoformat()
                    if sim0.first_floor_violation_date else "-",
                    "CONTRADICTION",
                    "official asp>0 requires a safe zero-payment baseline"))
            else:
                rows.append(BoundaryRow(
                    request.request_id, "A", str(asp), sim0.state.value,
                    str(sim0.minimum_projected_balance), str(profile.minimum_balance_to_keep),
                    "-", "PASS", "baseline consistent with official asp"))

            # Test B: official asp payment today
            simA, _, _ = self._state(sample, [Payment(request.request_date, asp)])
            if simA.state is SafetyState.UNSAFE:
                rows.append(BoundaryRow(
                    request.request_id, "B", str(asp), "UNSAFE",
                    str(simA.minimum_projected_balance), str(profile.minimum_balance_to_keep),
                    simA.first_floor_violation_date.isoformat()
                    if simA.first_floor_violation_date else "-",
                    "CONTRADICTION",
                    "official asp payment today violates the floor"))
            else:
                rows.append(BoundaryRow(
                    request.request_id, "B", str(asp), simA.state.value,
                    str(simA.minimum_projected_balance), str(profile.minimum_balance_to_keep),
                    "-", "PASS",
                    f"margin {simA.minimum_projected_balance - profile.minimum_balance_to_keep}"))

            # Test C: simulator-implied max safe today (evaluation-only headroom)
            implied = self._implied_asp(sample)
            rows.append(BoundaryRow(
                request.request_id, "C", str(asp), str(implied), "-", "-", "-",
                "PASS" if implied == asp else "MISMATCH",
                f"delta {implied - asp} (official internals not derivable; see D24)"))

            # Test F: full-today consistency with earliest == request_date
            full_today = self._state(sample, [Payment(request.request_date,
                                                      request.requested_amount)])[0]
            earliest_is_today = (sample.earliest_date_for_full_payment == request.request_date)
            expected_safe = earliest_is_today
            actual_safe = full_today.state is not SafetyState.UNSAFE
            if expected_safe == actual_safe:
                rows.append(BoundaryRow(
                    request.request_id, "F", str(request.requested_amount),
                    full_today.state.value, str(full_today.minimum_projected_balance),
                    str(profile.minimum_balance_to_keep), "-",
                    "PASS" if actual_safe else "PASS",
                    f"earliest==request_date:{earliest_is_today} full-today-safe:{actual_safe}"))
            else:
                rows.append(BoundaryRow(
                    request.request_id, "F", str(request.requested_amount),
                    full_today.state.value, str(full_today.minimum_projected_balance),
                    str(profile.minimum_balance_to_keep), "-",
                    "CONTRADICTION",
                    f"earliest==request_date:{earliest_is_today} but full-today-safe:{actual_safe}"))
        return rows

    # Test D/E: earliest-date safety and minimality
    def test_earliest(self) -> list[BoundaryRow]:
        rows = []
        for sample in self.bundle.samples:
            request = sample.request
            profile = self.indexes.profiles_by_user_id[request.user_id]
            lifecycle = resolve_lifecycle(
                self.indexes.events_by_user_id.get(request.user_id, []),
                request.request_date)
            defer = self._resolvable(sample, lifecycle)
            earliest = sample.earliest_date_for_full_payment
            if defer:
                for test in ("D", "E"):
                    rows.append(BoundaryRow(request.request_id, test, "-", "-", "-",
                                            "-", "-", "DEFERRED", defer))
                continue
            if earliest is None:
                for test in ("D", "E"):
                    rows.append(BoundaryRow(request.request_id, test, "-", "-", "-",
                                            "-", "-", "DEFERRED",
                                            "official earliest empty (full payment never "
                                            "safe within horizon)"))
                continue

            # Test D: requested amount on the official earliest date
            simD = self._state(sample, [Payment(earliest, request.requested_amount)])[0]
            rows.append(BoundaryRow(
                request.request_id, "D", str(request.requested_amount),
                simD.state.value, str(simD.minimum_projected_balance),
                str(profile.minimum_balance_to_keep),
                simD.first_floor_violation_date.isoformat()
                if simD.first_floor_violation_date else "-",
                "PASS" if simD.state is not SafetyState.UNSAFE else "CONTRADICTION",
                f"payment on official earliest {earliest.isoformat()}"))

            # Test E: one day earlier must be UNSAFE (minimality), if in window
            prev_day = earliest - timedelta_one()
            if prev_day < request.request_date:
                rows.append(BoundaryRow(
                    request.request_id, "E", "-", "-", "-", "-", "-", "PASS",
                    "earliest == request_date; no earlier in-window date"))
                continue
            simE = self._state(sample, [Payment(prev_day, request.requested_amount)])[0]
            unresolved_prev = any(u.effective_date == prev_day for u in lifecycle.unresolved)
            if unresolved_prev:
                rows.append(BoundaryRow(
                    request.request_id, "E", "-", "-", "-", "-", "-", "DEFERRED",
                    "unresolved evidence on the preceding day"))
            elif simE.state is SafetyState.UNSAFE:
                rows.append(BoundaryRow(
                    request.request_id, "E", "-", "UNSAFE", "-", "-", "-", "PASS",
                    f"{prev_day.isoformat()} unsafe: {earliest.isoformat()} is minimal"))
            else:
                rows.append(BoundaryRow(
                    request.request_id, "E", "-", simE.state.value, "-", "-", "-",
                    "CONTRADICTION",
                    f"{prev_day.isoformat()} is also safe: official earliest not minimal"))
        return rows

    def _implied_asp(self, sample: SampleRequest) -> Decimal:
        """Evaluation-only simulator headroom: max p in [0, requested] with
        pay-today safe. Bisection over Decimal amounts (cent granularity)."""
        request = sample.request
        lo, hi = Decimal("0"), request.requested_amount
        if self._state(sample, [Payment(request.request_date, hi)])[0].state \
                is not SafetyState.UNSAFE:
            return hi
        if self._state(sample, [Payment(request.request_date, Decimal("0.01"))])[0].state \
                is SafetyState.UNSAFE:
            return Decimal("0")
        for _ in range(40):  # 2^-40 of requested: below any monetary granularity
            mid = (lo + hi) / 2
            state = self._state(sample, [Payment(request.request_date, mid)])[0].state
            if state is SafetyState.UNSAFE:
                hi = mid
            else:
                lo = mid
        return lo.quantize(Decimal("0.01"))


def timedelta_one():
    from datetime import timedelta
    return timedelta(days=1)


def run() -> list[BoundaryRow]:
    auditor = BoundaryAuditor()
    return auditor.test_baseline_and_asp() + auditor.test_earliest()


def main(argv: list[str] | None = None) -> int:
    rows = run()
    print(f"{'request':<12}{'test':<8}{'official':>16}{'simulated':>16}"
          f"{'minimum':>16}{'floor':>14}{'violation':<12}{'verdict':<14}detail")
    for row in rows:
        print(row.line())
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.verdict] = counts.get(row.verdict, 0) + 1
    print(f"\nverdicts: {counts}")
    print("BOUNDARY AUDIT " + ("PASS (no unexplained contradictions)"
                               if counts.get("CONTRADICTION", 0) == 0
                               else f"FAIL ({counts.get('CONTRADICTION', 0)} contradiction(s))"))
    return 0 if counts.get("CONTRADICTION", 0) == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
