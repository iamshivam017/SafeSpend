"""Phase 2.1 regression tests: sample-grounded corrections.

Evidence base: official solved samples request_09 (affordable_now contradicted
by over-projection + missed interleaved income) and request_13 (wait plan),
plus the sample-plan safety audit (code/evaluation/plan_safety_audit.py).
"""
import unittest
from datetime import date, timedelta
from decimal import Decimal

from _finance_fixture import D, ev, profile

from code.errors import DataError
from code.schemas import EventStatus
from code.finance.lifecycle import resolve_lifecycle
from code.finance.recurrence import (detect_recurring_patterns, essential_provisions,
                                     project_occurrences, RecurrenceParams)
from code.finance.simulator import Payment, SafetyState, simulate
from code.finance.timeline import CashFlow


def salary_dom(dom, day, amount):
    """A salary event on a given date (day-of-month series member)."""
    return ev(f"s{dom}_{day.day}_{day.month}", category="salary",
              direction=__import__("code.schemas", fromlist=["EventDirection"]).EventDirection.CREDIT,
              amount=str(amount), event_date=day, settlement=day)


class InterleavedSalaryClusteringTests(unittest.TestCase):
    """Twice-monthly salary on the 15th and 20th: one combined series has
    irregular 5/25-day gaps and defeats naive gap detection; day-of-month
    clustering must find BOTH monthly series (request_13 evidence)."""

    def _twice_monthly(self):
        es = []
        for month in range(1, 6):
            es.append(salary_dom(15, date(2025, month, 15), "1343.54"))
            es.append(salary_dom(20, date(2025, month, 20), str(800 + month * 10)))
        return es

    def test_both_paychecks_detected(self):
        patterns = detect_recurring_patterns(self._twice_monthly())
        salary = [p for p in patterns if p.category == "salary"]
        self.assertEqual(len(salary), 2)
        self.assertTrue(all(p.is_monthly for p in salary))
        amounts = sorted(p.amount for p in salary)
        self.assertEqual(amounts[0], Decimal("840"))    # median of last-3 variable series
        self.assertEqual(amounts[1], Decimal("1343.54"))  # constant series

    def test_single_paycheck_unchanged(self):
        es = [salary_dom(15, date(2025, m, 15), "1000") for m in range(1, 6)]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)

    def test_no_clustering_false_positive_on_irregular(self):
        # genuinely irregular dates (dom 3, 14, 25, 7) must stay non-recurring
        from code.schemas import EventDirection
        dates = [date(2025, 1, 3), date(2025, 2, 14), date(2025, 3, 25),
                 date(2025, 4, 7), date(2025, 5, 20)]
        es = [ev(f"x{i}", category="shopping", direction=EventDirection.DEBIT,
                 amount="80", event_date=d, settlement=d) for i, d in enumerate(dates)]
        self.assertEqual(detect_recurring_patterns(es), [])


class DominantAnchorTests(unittest.TestCase):
    """A one-off adjustment must not hijack the monthly projection anchor
    (request_03 evidence: salary on the 15th + one-off on the 20th)."""

    def test_anchor_is_dominant_day_of_month(self):
        from code.schemas import EventDirection
        es = [ev("a", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2019, 4, 15), settlement=date(2019, 4, 15)),
              ev("b", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2019, 5, 15), settlement=date(2019, 5, 15)),
              ev("c", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2019, 6, 15), settlement=date(2019, 6, 15)),
              ev("d", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2019, 7, 15), settlement=date(2019, 7, 15)),
              ev("e", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2019, 8, 15), settlement=date(2019, 8, 15)),
              ev("f", category="salary", direction=EventDirection.CREDIT, amount="1964250",
                 event_date=date(2019, 8, 20), settlement=date(2019, 8, 20))]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].last_occurrence, date(2019, 8, 15))  # not 08-20
        request_date = date(2019, 9, 3)
        projected, _ = project_occurrences(patterns, request_date,
                                           request_date + timedelta(days=90), [])
        self.assertEqual([p.effective_date for p in projected],
                         [date(2019, 9, 15), date(2019, 10, 15), date(2019, 11, 15)])


class MonthlyOnlyProjectionTests(unittest.TestCase):
    """Phase 2.1 (requests 02/03/04/08/12/17/22 evidence): sub-monthly purchase
    series are history, not forecast commitments."""

    def test_fixed_gap_pattern_detected_but_not_projected(self):
        from code.schemas import EventDirection
        es = [ev(f"g{i}", category="groceries", direction=EventDirection.DEBIT,
                 amount="50", event_date=D - timedelta(days=10 * (5 - i)),
                 settlement=D - timedelta(days=10 * (5 - i))) for i in range(5)]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)  # still detected (traceability)
        projected, diags = project_occurrences(patterns, D, D + timedelta(days=90), [])
        self.assertEqual(projected, [])
        self.assertTrue(any("monthly-commitments-only" in d for d in diags))

    def test_monthly_pattern_still_projects(self):
        from code.schemas import EventDirection
        es = [ev(f"r{i}", category="rent", direction=EventDirection.DEBIT, amount="800",
                 event_date=D - timedelta(days=30 * (5 - i)),
                 settlement=D - timedelta(days=30 * (5 - i))) for i in range(5)]
        patterns = detect_recurring_patterns(es)
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [])
        self.assertTrue(projected)

    def test_opt_in_non_monthly_projection(self):
        from code.schemas import EventDirection
        es = [ev(f"g{i}", category="groceries", direction=EventDirection.DEBIT,
                 amount="50", event_date=D - timedelta(days=10 * (5 - i)),
                 settlement=D - timedelta(days=10 * (5 - i))) for i in range(5)]
        patterns = detect_recurring_patterns(es)
        params = RecurrenceParams(project_non_monthly=True)
        projected, _ = project_occurrences(patterns, D, D + timedelta(days=90), [],
                                           params=params)
        self.assertTrue(projected)


class EodFloorTests(unittest.TestCase):
    """D6 rev. 2: floor checked on end-of-day balance (sample evidence:
    requests 18/23 pay official plans on payday)."""

    def flow(self, amount, on_date, category="rent"):
        return CashFlow(amount_home=Decimal(amount), effective_date=on_date,
                        category=category,
                        direction_value="debit" if Decimal(amount) < 0 else "credit",
                        basis="settled", source_event_ids=("t",), essential=False,
                        flexibility="fixed", certainty="actual", event_type="test")

    def test_same_day_salary_covers_payment(self):
        p = profile(balance="100", minimum="90")
        r = simulate(p, D, [self.flow("500", D, category="salary"),
                            self.flow("-450", D)])
        self.assertEqual(r.state, SafetyState.SAFE)  # EOD 150 >= 90

    def test_eod_below_floor_still_unsafe(self):
        p = profile(balance="100", minimum="90")
        r = simulate(p, D, [self.flow("500", D, category="salary"),
                            self.flow("-550", D)])
        self.assertEqual(r.state, SafetyState.UNSAFE)  # EOD 50 < 90


class EssentialProvisionTests(unittest.TestCase):
    """D21 safety net: irregular sustained essential spend gets a conservative
    monthly provision. Never fires on the official dataset (verified in
    test_realdata_provisions_never_fire)."""

    def test_irregular_sustained_essential_provisioned(self):
        from code.schemas import EventDirection
        # healthcare: 3 purchases per 30d window, irregular dates, no cadence
        es = []
        offsets = (5, 14, 29, 36, 52, 63, 69, 83, 88)  # gaps 9,15,7,16,11,6,14,5
        for n, off in enumerate(offsets, start=1):
            d = D - timedelta(days=off)
            es.append(ev(f"h{n}", category="healthcare",
                         direction=EventDirection.DEBIT, amount="40",
                         event_date=d, settlement=d))
        patterns = detect_recurring_patterns(es)
        self.assertEqual(patterns, [])  # irregular
        provisions = essential_provisions(es, {"healthcare"}, D, patterns)
        self.assertEqual(len(provisions), 2)  # +30d, +60d
        self.assertEqual(provisions[0].amount, Decimal("120"))  # trailing-30d total
        self.assertEqual(provisions[0].effective_date, D + timedelta(days=30))
        self.assertEqual(provisions[1].effective_date, D + timedelta(days=60))

    def test_not_fired_for_non_protected_or_patterned(self):
        from code.schemas import EventDirection
        es = [ev(f"h{i}", category="healthcare",
                 direction=EventDirection.DEBIT, amount="40",
                 event_date=D - timedelta(days=30 * (5 - i)),
                 settlement=D - timedelta(days=30 * (5 - i))) for i in range(5)]
        # periodic -> detected -> no provision
        patterns = detect_recurring_patterns(es)
        self.assertEqual(essential_provisions(es, {"healthcare"}, D, patterns), [])
        # irregular but non-protected -> no provision
        irregular = [ev(f"i{n}", category="hobbies",
                        direction=EventDirection.DEBIT, amount="40",
                        event_date=D - timedelta(days=11 * n),
                        settlement=D - timedelta(days=11 * n)) for n in range(6)]
        self.assertEqual(essential_provisions(irregular, {"healthcare"}, D, []), [])

    def test_realdata_provisions_never_fire(self):
        # empirical dataset fact: every essential series is periodic after
        # clustering, so the safety net must never fire on official data
        from _bootstrap import ROOT  # noqa: F401
        from code.data_loader import load_all
        from code.indexes import Indexes
        bundle = load_all()
        indexes = Indexes.build(bundle)
        fired = 0
        for s in bundle.samples:
            r = s.request
            ue = indexes.events_by_user_id.get(r.user_id, [])
            p = indexes.profiles_by_user_id[r.user_id]
            pats = detect_recurring_patterns(ue)
            provisions = essential_provisions(
                ue, set(p.expense_categories_to_protect), r.request_date, pats)
            fired += len(provisions)
        self.assertEqual(fired, 0)


class CancellationAmendmentMatrixTests(unittest.TestCase):
    """Phase 2.1 section 7: linked pending -> cancelled/amended matrix."""

    def _pending_after(self, linked, amount="500", event_date=None):
        return ev("pd", amount=amount, status=EventStatus.PENDING,
                  event_date=event_date or date(2026, 1, 10),
                  settlement=date(2026, 1, 12), linked=linked)

    def test_linked_cancelled_same_amount_dropped(self):
        t = ev("t1", amount="500", status=EventStatus.CANCELLED,
               event_date=date(2025, 12, 20), settlement=date(2025, 12, 21))
        r = resolve_lifecycle([t, self._pending_after("t1")], D)
        self.assertEqual(r.cash_events, [])

    def test_linked_cancelled_changed_amount_pending_after_dropped(self):
        # official precedence 1: explicit cancellation resolves the lifecycle;
        # a later-dated pending is its changed-amount continuation
        t = ev("t2", amount="300", status=EventStatus.CANCELLED,
               event_date=date(2025, 12, 20), settlement=date(2025, 12, 21))
        r = resolve_lifecycle([t, self._pending_after("t2", amount="450")], D)
        self.assertEqual(r.cash_events, [])

    def test_linked_settled_changed_amount_pending_kept_as_amendment(self):
        # a settled parent + a later different-amount pending: the pending is
        # the live amended obligation (not a duplicate) -> reserved
        parent = ev("t3", amount="300", event_date=date(2025, 12, 20),
                    settlement=date(2025, 12, 21))
        r = resolve_lifecycle([parent, self._pending_after("t3", amount="450")], D)
        self.assertEqual([c.amount for c in r.cash_events], [Decimal("450")])

    def test_unrelated_cancellation_similar_attributes_keeps_pending(self):
        # no linked_event_id: a similar cancelled event never suppresses a
        # distinct pending movement (link alone is not evidence, and neither
        # is attribute similarity)
        cancelled = ev("u1", amount="500", status=EventStatus.CANCELLED,
                       event_date=date(2025, 12, 20), settlement=date(2025, 12, 21))
        pending = ev("u2", amount="500", status=EventStatus.PENDING,
                     event_date=date(2026, 1, 10), settlement=date(2026, 1, 12))
        r = resolve_lifecycle([cancelled, pending], D)
        self.assertEqual([c.amount for c in r.cash_events], [Decimal("500")])

    def test_pending_before_terminal_different_amount_kept(self):
        # distinct earlier movement: a later cancellation of a different charge
        # does not suppress it
        pending = ev("p3", amount="700", status=EventStatus.PENDING,
                     event_date=date(2025, 12, 1), settlement=date(2026, 1, 5))
        t = ev("t4", amount="300", status=EventStatus.CANCELLED,
               event_date=date(2026, 1, 20), settlement=date(2026, 1, 21),
               linked="p3")
        r = resolve_lifecycle([pending, t], D)
        self.assertEqual([c.amount for c in r.cash_events], [Decimal("700")])


class SamplePlanAuditIsolationTests(unittest.TestCase):
    """The audit reads sample labels — production code must never import it."""

    def test_production_modules_do_not_import_audit(self):
        import ast
        from pathlib import Path
        ROOT = Path(__file__).resolve().parents[1]
        production = list((ROOT / "code").glob("*.py")) + \
            [p for p in (ROOT / "code" / "finance").glob("*.py")]
        for path in production:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn("plan_safety_audit", node.module or "", str(path))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("plan_safety_audit", alias.name, str(path))

    def test_audit_runs_and_reports_no_contradictions(self):
        from code.evaluation.plan_safety_audit import run_audit
        rows = run_audit()
        self.assertEqual(len(rows), 25)
        verdicts = {}
        for row in rows:
            verdicts[row.verdict] = verdicts.get(row.verdict, 0) + 1
        self.assertEqual(verdicts.get("CONTRADICTION", 0), 0)
        self.assertGreaterEqual(verdicts.get("PASS", 0), 14)
        # the two Phase-2.1 trigger samples must PASS
        by_id = {row.request_id: row for row in rows}
        self.assertEqual(by_id["request_09"].verdict, "PASS")
        self.assertEqual(by_id["request_13"].verdict, "PASS")


if __name__ == "__main__":
    unittest.main()
