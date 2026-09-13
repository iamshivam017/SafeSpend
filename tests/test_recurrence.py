import unittest
from datetime import date, timedelta
from decimal import Decimal

from _finance_fixture import D, ev
from code.finance.recurrence import (RecurrenceParams, detect_recurring_patterns,
                                     project_occurrences)


def monthly_series(start=date(2025, 6, 15), n=6, amount="4365000", category="salary",
                   direction=None, user="user_x"):
    from code.schemas import EventDirection
    direction = direction or EventDirection.CREDIT
    return [ev(f"{category}_{i}", category=category, direction=direction, amount=amount,
               event_date=start + timedelta(days=30 * i + (1 if i % 2 else 0)),
               settlement=start + timedelta(days=30 * i + (1 if i % 2 else 0)))
            for i in range(n)]


class DetectionTests(unittest.TestCase):
    def test_monthly_salary_detected(self):
        patterns = detect_recurring_patterns(monthly_series())
        self.assertEqual(len(patterns), 1)
        p = patterns[0]
        self.assertTrue(p.is_monthly)
        self.assertEqual(p.direction.value, "credit")
        self.assertIn("monthly", p.classification_reason)

    def test_weekly_series_detected(self):
        from code.schemas import EventDirection
        es = [ev(f"g{i}", category="groceries", direction=EventDirection.DEBIT,
                 amount=str(500 + i * 10), event_date=D - timedelta(days=7 * (6 - i)),
                 settlement=D - timedelta(days=7 * (6 - i)))
              for i in range(6)]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].cadence_days, 7)

    def test_requires_minimum_observations(self):
        patterns = detect_recurring_patterns(monthly_series(n=2))
        self.assertEqual(patterns, [])

    def test_irregular_series_not_recurring(self):
        from code.schemas import EventDirection
        dates = [date(2025, 7, 1), date(2025, 9, 14), date(2025, 12, 25), date(2026, 1, 3)]
        es = [ev(f"x{i}", category="shopping", direction=EventDirection.DEBIT, amount="80",
                 event_date=d, settlement=d) for i, d in enumerate(dates)]
        self.assertEqual(detect_recurring_patterns(es), [])

    def test_one_off_adjustment_tolerated(self):
        # real pattern: monthly salary with a one-off small adjustment 5 days later
        from code.schemas import EventDirection
        es = [ev("s0", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2025, 4, 15), settlement=date(2025, 4, 15)),
              ev("s1", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2025, 5, 15), settlement=date(2025, 5, 15)),
              ev("s2", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2025, 6, 15), settlement=date(2025, 6, 15)),
              ev("s3", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2025, 7, 15), settlement=date(2025, 7, 15)),
              ev("adj", category="salary", direction=EventDirection.CREDIT, amount="1964250",
                 event_date=date(2025, 7, 20), settlement=date(2025, 7, 20)),
              ev("s4", category="salary", direction=EventDirection.CREDIT, amount="4365000",
                 event_date=date(2025, 8, 15), settlement=date(2025, 8, 15))]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0].amount, Decimal("4365000"))  # median of recent window

    def test_conservative_amount_debit_uses_recent_max(self):
        from code.schemas import EventDirection
        es = [ev(f"u{i}", category="utilities", direction=EventDirection.DEBIT,
                 amount=str(100 + i * 50), event_date=D - timedelta(days=30 * (4 - i)),
                 settlement=D - timedelta(days=30 * (4 - i))) for i in range(4)]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(patterns[0].amount, Decimal("250"))  # max of last 3

    def test_flexibility_metadata_from_sources(self):
        from code.schemas import EventDirection, Flexibility
        es = [ev(f"f{i}", category="dining", direction=EventDirection.DEBIT, amount="20",
                 flexibility=Flexibility.REDUCIBLE if i % 2 else Flexibility.FIXED,
                 event_date=D - timedelta(days=14 * (5 - i)),
                 settlement=D - timedelta(days=14 * (5 - i))) for i in range(5)]
        patterns = detect_recurring_patterns(es)
        self.assertEqual(patterns[0].flexibility, "fixed")  # dominant (3 of 5)

    def test_no_recurrence_from_category_name_alone(self):
        # a single 'rent' event with no history must NOT be projected
        self.assertEqual(detect_recurring_patterns([ev(category="rent", amount="1000")]), [])


class ProjectionTests(unittest.TestCase):
    def test_monthly_projection_clamps_day_of_month(self):
        from code.schemas import EventDirection
        from code.finance.recurrence import RecurringPattern
        p = RecurringPattern(category="salary", direction=EventDirection.CREDIT,
                             currency="USD", cadence_days=30, is_monthly=True,
                             amount=Decimal("4000"), flexibility="fixed",
                             source_event_ids=("s",), last_occurrence=date(2026, 1, 15),
                             classification_reason="test")
        projected, _ = project_occurrences([p], D, date(2026, 4, 10), [])
        self.assertEqual([o.effective_date for o in projected],
                         [date(2026, 2, 15), date(2026, 3, 15)])
        self.assertTrue(all(o.effective_date <= date(2026, 4, 10) for o in projected))

    def test_projection_stops_at_horizon_end(self):
        from code.schemas import EventDirection
        from code.finance.recurrence import RecurringPattern
        p = RecurringPattern(category="rent", direction=EventDirection.DEBIT,
                             currency="USD", cadence_days=30, is_monthly=True,
                             amount=Decimal("1000"), flexibility="fixed",
                             source_event_ids=("r",), last_occurrence=date(2025, 12, 31),
                             classification_reason="test")
        projected, _ = project_occurrences([p], D, date(2026, 4, 1), [])
        self.assertTrue(projected)
        self.assertTrue(all(o.effective_date <= date(2026, 4, 1) for o in projected))

    def test_projection_dropped_near_actual_record(self):
        from code.schemas import EventDirection
        from code.finance.recurrence import RecurringPattern
        from code.finance.lifecycle import ResolvedCashEvent
        from code.schemas import EventDirection as ED
        p = RecurringPattern(category="salary", direction=EventDirection.CREDIT,
                             currency="USD", cadence_days=30, is_monthly=True,
                             amount=Decimal("4000"), flexibility="fixed",
                             source_event_ids=("s",), last_occurrence=date(2026, 1, 15),
                             classification_reason="test")
        actual = ResolvedCashEvent(amount=Decimal("4200"), currency="USD",
                                   direction=ED.CREDIT, effective_date=date(2026, 2, 16),
                                   category="salary", event_type="income",
                                   flexibility="fixed", source_event_ids=("actual",),
                                   basis="scheduled")
        projected, diags = project_occurrences([p], D, date(2026, 3, 31), [actual])
        self.assertTrue(any("dropped" in d for d in diags))
        self.assertFalse(any(o.effective_date == date(2026, 2, 15) for o in projected))


if __name__ == "__main__":
    unittest.main()
