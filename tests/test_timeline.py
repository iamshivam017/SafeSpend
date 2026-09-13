import unittest
from datetime import date, timedelta
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, ev, profile

from code.data_loader import load_all
from code.finance.lifecycle import resolve_lifecycle
from code.finance.recurrence import detect_recurring_patterns
from code.finance.timeline import (CashFlow, build_cash_timeline, horizon_end)
from code.indexes import Indexes


class HorizonTests(unittest.TestCase):
    def test_horizon_boundaries(self):
        self.assertEqual(horizon_end(D), D + timedelta(days=90))
        self.assertEqual(horizon_end(date(2026, 2, 7)), date(2026, 5, 8))

    def test_flow_outside_horizon_excluded(self):
        idx = Indexes.build(load_all())
        p = profile()
        lifecycle = resolve_lifecycle(
            [ev(amount="10", event_date=D + timedelta(days=91),
                settlement=D + timedelta(days=91))], D)
        patterns = detect_recurring_patterns([])
        tl = build_cash_timeline(p, D, lifecycle, patterns, idx)
        self.assertEqual(tl.flows, [])

    def test_flow_on_day0_and_day90_included(self):
        idx = Indexes.build(load_all())
        p = profile()
        lifecycle = resolve_lifecycle(
            [ev("d0", amount="10", event_date=D, settlement=D),
             ev("d90", amount="10", event_date=D + timedelta(days=90),
                settlement=D + timedelta(days=90))], D)
        tl = build_cash_timeline(p, D, lifecycle, detect_recurring_patterns([]), idx)
        self.assertEqual(len(tl.flows), 2)


class NormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.indexes = Indexes.build(load_all())

    def test_same_currency_passes_through_signed(self):
        p = profile(home="USD")
        lifecycle = resolve_lifecycle([ev(amount="25", event_date=date(2026, 1, 2),
                                          settlement=date(2026, 1, 3))], D)
        tl = build_cash_timeline(p, D, lifecycle, [], self.indexes)
        self.assertEqual(tl.flows[0].amount_home, Decimal("-25"))
        self.assertEqual(tl.flows[0].direction_value, "debit")

    def test_fx_conversion_to_home_currency(self):
        p = profile(home="ZAR")
        # 2 EUR on 2023-10-15 at EUR->ZAR 20 => 40 ZAR debit
        lifecycle = resolve_lifecycle([ev(amount="2", currency="EUR",
                                          event_date=date(2023, 10, 15),
                                          settlement=date(2023, 10, 15))],
                                      date(2023, 10, 10))
        tl = build_cash_timeline(p, date(2023, 10, 10), lifecycle, [], self.indexes)
        self.assertEqual(tl.flows[0].amount_home, Decimal("-40"))

    def test_missing_fx_path_raises_clear_error(self):
        p = profile(home="JPY")  # no JPY rates exist at all
        lifecycle = resolve_lifecycle([ev(amount="5", currency="USD",
                                          event_date=date(2026, 1, 2),
                                          settlement=date(2026, 1, 3))], D)
        from code.finance.currency import MissingRateError
        with self.assertRaises(MissingRateError):
            build_cash_timeline(p, D, lifecycle, [], self.indexes)

    def test_essential_metadata_from_profile(self):
        p = profile(protected=("rent",))
        lifecycle = resolve_lifecycle(
            [ev("r", category="rent", amount="100", event_date=date(2026, 1, 2),
                settlement=date(2026, 1, 3)),
             ev("s", category="streaming", amount="10", event_date=date(2026, 1, 2),
                settlement=date(2026, 1, 3))], D)
        tl = build_cash_timeline(p, D, lifecycle, [], self.indexes)
        by_cat = {f.category: f for f in tl.flows}
        self.assertTrue(by_cat["rent"].essential)
        self.assertFalse(by_cat["streaming"].essential)

    def test_deterministic_ordering(self):
        p = profile()
        lifecycle = resolve_lifecycle(
            [ev(f"o{i}", amount=str(10 + i), event_date=date(2026, 1, 2),
                settlement=date(2026, 1, 3)) for i in range(5)], D)
        tl1 = build_cash_timeline(p, D, lifecycle, [], self.indexes)
        lifecycle2 = resolve_lifecycle(
            [ev(f"o{i}", amount=str(10 + i), event_date=date(2026, 1, 2),
                settlement=date(2026, 1, 3)) for i in range(5)], D)
        tl2 = build_cash_timeline(p, D, lifecycle2, [], self.indexes)
        self.assertEqual(tl1.flows, tl2.flows)


if __name__ == "__main__":
    unittest.main()
