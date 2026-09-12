import unittest
from datetime import date
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401

from code.errors import EnumValueError
from code.schemas import (OUTPUT_COLUMNS, AffordabilityStatus, EventDirection, EventStatus,
                          EventType, FinancialEvent, Flexibility, OutputRow, RecommendedPaymentMethod,
                          RequestType, _StrictEnum)


class EnumTests(unittest.TestCase):
    def test_official_affordability_values(self):
        self.assertEqual({s.value for s in AffordabilityStatus},
                         {"affordable_now", "affordable_with_plan",
                          "affordable_later", "not_affordable"})

    def test_official_method_values(self):
        self.assertEqual({s.value for s in RecommendedPaymentMethod},
                         {"full_payment", "partial_payment", "installments",
                          "wait", "not_recommended"})

    def test_event_status_parse(self):
        self.assertEqual(EventStatus.parse("settled", field_name="s"), EventStatus.SETTLED)
        self.assertIsNone(EventStatus.parse("", field_name="s", nullable=True))

    def test_unknown_value_raises(self):
        with self.assertRaises(EnumValueError):
            EventStatus.parse("archived", field_name="status")

    def test_nullable_missing_raises_when_required(self):
        with self.assertRaises(EnumValueError):
            EventStatus.parse("", field_name="status")

    def test_direction_and_flexibility_sets(self):
        self.assertEqual({d.value for d in EventDirection},
                         {"debit", "credit", "non_cash"})
        self.assertEqual({f.value for f in Flexibility},
                         {"fixed", "reducible", "stoppable", "reducible_or_stoppable"})

    def test_request_type_official_nine(self):
        self.assertEqual({t.value for t in RequestType},
                         {"purchase", "travel", "education", "family_transfer",
                          "debt_repayment", "investment", "housing",
                          "emergency_expense", "other"})

    def test_event_type_observed_set(self):
        self.assertEqual({t.value for t in EventType},
                         {"expense", "subscription", "income", "debt_payment",
                          "investment_purchase", "refund", "investment_valuation",
                          "investment_sale"})


class OutputRowTests(unittest.TestCase):
    def test_column_order_is_official(self):
        self.assertEqual(OUTPUT_COLUMNS, (
            "request_id", "amount_safe_to_pay", "affordability_status",
            "recommended_payment_method", "payment_plan",
            "earliest_date_for_full_payment", "spending_changes_needed",
            "decision_explanation"))

    def test_to_csv_row_serialization(self):
        row = OutputRow(
            request_id="request_26",
            amount_safe_to_pay=Decimal("15656000"),
            affordability_status=AffordabilityStatus.AFFORDABLE_LATER,
            recommended_payment_method=RecommendedPaymentMethod.WAIT,
            payment_plan="2025-10-07:15656000",
            earliest_date_for_full_payment=date(2025, 10, 7),
            spending_changes_needed="none",
            decision_explanation="Wait until funds are safe.")
        self.assertEqual(row.to_csv_row(), [
            "request_26", "15656000", "affordable_later", "wait",
            "2025-10-07:15656000", "2025-10-07", "none",
            "Wait until funds are safe."])

    def test_money_serialization_has_no_scientific_notation_and_keeps_scale(self):
        row = OutputRow(
            request_id="r", amount_safe_to_pay=Decimal("17229139.20"),
            affordability_status=AffordabilityStatus.AFFORDABLE_WITH_PLAN,
            recommended_payment_method=RecommendedPaymentMethod.INSTALLMENTS,
            payment_plan="none", earliest_date_for_full_payment=None,
            spending_changes_needed="none", decision_explanation="x")
        self.assertEqual(row.to_csv_row()[1], "17229139.20")

    def test_event_amount_blank_is_none_not_zero(self):
        event = FinancialEvent(
            event_id="event_253", user_id="user_03", event_type=EventType.INCOME,
            description="August 2019 net salary", category="salary",
            direction=EventDirection.CREDIT, amount=None, currency="IDR",
            event_date=date(2019, 8, 31), settlement_date=date(2019, 8, 31),
            status=EventStatus.SETTLED, linked_event_id=None,
            flexibility=Flexibility.FIXED, minimum_allowed_amount=None)
        self.assertIsNone(event.amount)  # officially valid blank; must stay None
        self.assertNotEqual(event.amount, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
