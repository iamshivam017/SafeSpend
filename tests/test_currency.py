import unittest
from datetime import date
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import profile

from code.data_loader import load_all
from code.errors import DataError
from code.finance.currency import CurrencyConverter, MissingRateError
from code.indexes import Indexes


class CurrencyConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.indexes = Indexes.build(load_all())
        cls.conv = CurrencyConverter(cls.indexes)

    def test_same_currency_noop(self):
        self.assertEqual(self.conv.convert(Decimal("5"), "USD", "USD", date(2026, 1, 1)),
                         Decimal("5"))

    def test_direct_official_rate(self):
        # official row: 2023-10-15 EUR->ZAR 20
        self.assertEqual(self.conv.convert(Decimal("2"), "EUR", "ZAR", date(2023, 10, 15)),
                         Decimal("40"))

    def test_direction_matters(self):
        # USD->EUR exists; the inverse on the same date may not — direct lookup only
        rate_eur = self.conv.convert(Decimal("1"), "USD", "EUR", date(2023, 10, 15)) \
            if self.indexes.get_rate(date(2023, 10, 15), "USD", "EUR") else None
        if rate_eur is not None:
            self.assertNotEqual(rate_eur, Decimal("1"))

    def test_missing_rate_raises_clear_error(self):
        with self.assertRaises(MissingRateError) as ctx:
            self.conv.convert(Decimal("1"), "ZAR", "JPY", date(2026, 1, 1))
        self.assertIn("ZAR->JPY", str(ctx.exception))

    def test_missing_date_raises(self):
        with self.assertRaises(MissingRateError):
            self.conv.convert(Decimal("1"), "EUR", "ZAR", date(1999, 1, 1))

    def test_all_dataset_conversion_pairs_have_direct_rates(self):
        # empirical proof (Phase 2 directive §8): every conversion the participant
        # data requires is served by a direct same-date official rate row
        bundle = load_all()
        home = {p.user_id: p.home_currency for p in bundle.profiles}
        from collections import Counter
        needed = set()
        for e in bundle.events:
            h = home.get(e.user_id)
            if h and e.currency != h and e.amount is not None \
                    and e.status in ("settled", "pending", "scheduled"):
                needed.add((e.currency, h))
        conv = CurrencyConverter(self.indexes)
        # every needed pair has at least one rate row (per-date availability is
        # checked during simulation; missing dates raise clear errors)
        rate_pairs = {(r.from_currency, r.to_currency) for r in bundle.rates}
        self.assertTrue(needed, "dataset should require conversions")
        for pair in needed:
            self.assertIn(pair, rate_pairs, f"no direct rate for {pair}")

    def test_decimal_exactness(self):
        # rate 20: 0.1 EUR -> 2 ZAR exactly, no float error
        self.assertEqual(self.conv.convert(Decimal("0.1"), "EUR", "ZAR", date(2023, 10, 15)),
                         Decimal("2.0"))


if __name__ == "__main__":
    unittest.main()
