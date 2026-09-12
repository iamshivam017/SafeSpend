import unittest

from _bootstrap import ROOT  # noqa: F401  (sys.path bootstrap)

from code.errors import DateParseError, IntParseError, MoneyParseError
from code.parsing import (format_date, format_money, parse_bool, parse_date, parse_int,
                          parse_money, parse_pipe_list)
from decimal import Decimal


class MoneyParsingTests(unittest.TestCase):
    def test_integer_amount(self):
        self.assertEqual(parse_money("100", field="f"), Decimal("100"))

    def test_decimal_amount_preserves_scale(self):
        self.assertEqual(parse_money("100.50", field="f"), Decimal("100.50"))
        self.assertEqual(format_money(parse_money("100.50", field="f")), "100.50")

    def test_negative_amount(self):
        self.assertEqual(parse_money("-100.50", field="f"), Decimal("-100.50"))

    def test_zero_vs_blank_vs_zero_decimal(self):
        self.assertEqual(parse_money("0", field="f"), Decimal("0"))
        self.assertEqual(parse_money("0.00", field="f"), Decimal("0.00"))
        self.assertIsNone(parse_money("", field="f"))          # blank is None, never 0
        self.assertIsNone(parse_money(None, field="f"))
        self.assertIsNot(parse_money("0.00", field="f"), parse_money("", field="f"))

    def test_malformed_rejected(self):
        for bad in ("1,000", "1e5", "abc", "10.", ".5", "NaN", "Infinity"):
            with self.assertRaises(MoneyParseError, msg=bad):
                parse_money(bad, field="f")
        # benign surrounding whitespace is stripped before validation (documented)
        self.assertEqual(parse_money(" 100.50 ", field="f"), Decimal("100.50"))

    def test_error_carries_context(self):
        with self.assertRaises(MoneyParseError) as ctx:
            parse_money("abc", field="amount", file="x.csv", row=7, identifier="event_1")
        self.assertIn("x.csv", str(ctx.exception))
        self.assertIn("row=7", str(ctx.exception))
        self.assertIn("event_1", str(ctx.exception))

    def test_no_scientific_notation_on_format(self):
        self.assertEqual(format_money(Decimal("1E+7")), "10000000")


class DateParsingTests(unittest.TestCase):
    def test_valid_date(self):
        from datetime import date
        self.assertEqual(parse_date("2026-09-13", field="f"), date(2026, 9, 13))

    def test_blank_nullable(self):
        self.assertIsNone(parse_date("", field="f"))
        self.assertIsNone(parse_date(None, field="f"))

    def test_blank_required_raises(self):
        with self.assertRaises(DateParseError):
            parse_date("", field="f", nullable=False)

    def test_malformed_raises(self):
        for bad in ("2026/09/13", "13-09-2026", "2026-13-01", "20260913", "2026-02-30"):
            with self.assertRaises(DateParseError, msg=bad):
                parse_date(bad, field="f")

    def test_format_roundtrip(self):
        from datetime import date
        self.assertEqual(format_date(date(2026, 9, 13)), "2026-09-13")
        self.assertEqual(format_date(None), "")


class IntParsingTests(unittest.TestCase):
    def test_valid_and_blank(self):
        self.assertEqual(parse_int("12", field="f"), 12)
        self.assertIsNone(parse_int("", field="f"))

    def test_malformed(self):
        for bad in ("-1", "1.5", "abc", "1e2"):
            with self.assertRaises(IntParseError, msg=bad):
                parse_int(bad, field="f")


class ListParsingTests(unittest.TestCase):
    def test_blank(self):
        self.assertEqual(parse_pipe_list(""), [])
        self.assertEqual(parse_pipe_list(None), [])
        self.assertNotEqual(parse_pipe_list(""), [""])  # never [""]

    def test_single_and_multiple(self):
        self.assertEqual(parse_pipe_list("food"), ["food"])
        self.assertEqual(parse_pipe_list("food|rent"), ["food", "rent"])

    def test_whitespace_and_empty_items(self):
        self.assertEqual(parse_pipe_list(" food | rent "), ["food", "rent"])
        self.assertEqual(parse_pipe_list("food||rent"), ["food", "rent"])


class BoolParsingTests(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(parse_bool("true", field="f"))
        self.assertFalse(parse_bool("false", field="f"))
        self.assertTrue(parse_bool("True", field="f"))

    def test_invalid(self):
        from code.errors import EnumValueError
        with self.assertRaises(EnumValueError):
            parse_bool("yes", field="f")


if __name__ == "__main__":
    unittest.main()
