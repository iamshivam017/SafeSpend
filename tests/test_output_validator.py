import unittest
from datetime import date
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401

from code.data_loader import load_all
from code.errors import DataError
from code.indexes import Indexes
from code.output_validator import (format_payment_plan, format_spending_changes,
                                   parse_payment_plan, parse_spending_changes,
                                   validate_output_header, validate_output_rows)
from code.schemas import Request


def make_row(**overrides):
    base = {
        "request_id": "request_26",
        "amount_safe_to_pay": "15656000",
        "affordability_status": "affordable_later",
        "recommended_payment_method": "wait",
        "payment_plan": "2025-10-07:15656000",
        "earliest_date_for_full_payment": "2025-10-07",
        "spending_changes_needed": "none",
        "decision_explanation": "Wait until the transfer is safe.",
    }
    base.update(overrides)
    return base


class PaymentPlanParserTests(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertIsNone(parse_payment_plan("none"))
        self.assertIsNone(parse_payment_plan(""))
        self.assertIsNone(parse_payment_plan(None))

    def test_single_and_multiple(self):
        plan = parse_payment_plan("2026-09-07:300|2026-10-07:300|2026-11-07:300")
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0].amount, Decimal("300"))

    def test_chronological_order_enforced(self):
        with self.assertRaises(DataError):
            parse_payment_plan("2026-10-07:300|2026-09-07:300")

    def test_malformed_entries_rejected(self):
        for bad in ("2026-09-07:", "2026-09-07:abc", "07-09-2026:300", "300:2026-09-07",
                    "2026-09-07:-1"):
            with self.assertRaises(DataError, msg=bad):
                parse_payment_plan(bad)

    def test_roundtrip_format(self):
        plan = parse_payment_plan("2026-01-01:100.00|2026-02-01:100.00")
        self.assertEqual(format_payment_plan(plan), "2026-01-01:100.00|2026-02-01:100.00")
        self.assertEqual(format_payment_plan(None), "none")


class SpendingChangeParserTests(unittest.TestCase):
    def test_none_and_blank(self):
        self.assertEqual(parse_spending_changes("none"), [])
        self.assertEqual(parse_spending_changes(""), [])

    def test_official_example(self):
        changes = parse_spending_changes("stop:event_14|reduce_to:event_21:100")
        self.assertEqual(changes[0].action, "stop")
        self.assertEqual(changes[0].event_id, "event_14")
        self.assertEqual(changes[1].action, "reduce_to")
        self.assertEqual(changes[1].event_id, "event_21")
        self.assertEqual(changes[1].new_amount, Decimal("100"))

    def test_more_than_three_rejected(self):
        raw = "stop:a|stop:b|stop:c|stop:d"
        with self.assertRaises(DataError):
            parse_spending_changes(raw)

    def test_stop_and_reduce_same_event_rejected(self):
        with self.assertRaises(DataError):
            parse_spending_changes("stop:event_1|reduce_to:event_1:50")

    def test_duplicate_identical_rejected(self):
        with self.assertRaises(DataError):
            parse_spending_changes("stop:event_1|stop:event_1")

    def test_malformed_rejected(self):
        for bad in ("pause:event_1", "reduce_to:event_1", "stop:", "reduce_to:event_1:abc"):
            with self.assertRaises(DataError, msg=bad):
                parse_spending_changes(bad)

    def test_roundtrip_format(self):
        changes = parse_spending_changes("stop:event_14|reduce_to:event_21:100.50")
        self.assertEqual(format_spending_changes(changes),
                         "stop:event_14|reduce_to:event_21:100.50")
        self.assertEqual(format_spending_changes([]), "none")


class OutputRowValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_all()
        cls.indexes = Indexes.build(cls.bundle)
        # prediction-target universe = evaluation requests + solved samples
        # (samples are the regression targets used by the evaluator)
        cls.requests = dict(cls.indexes.requests_by_request_id)
        cls.requests.update({s.request.request_id: s.request
                             for s in cls.bundle.samples})
        cls.request_26 = cls.requests["request_26"]  # IDR family transfer, 15,656,000

    def test_exact_columns_and_order(self):
        self.assertEqual(validate_output_header(list(
            ("request_id", "amount_safe_to_pay", "affordability_status",
             "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
             "spending_changes_needed", "decision_explanation"))), [])
        self.assertNotEqual(validate_output_header(["request_id", "oops"]), [])

    def test_valid_row_passes(self):
        row = make_row()
        violations = validate_output_rows([row], requests_by_id=self.requests, require_full_coverage=False)
        self.assertEqual(violations, [])

    def test_amount_bounds(self):
        violations = validate_output_rows(
            [make_row(amount_safe_to_pay="-1")], requests_by_id=self.requests,
            require_full_coverage=False)
        self.assertTrue(any("negative" in v for v in violations))
        violations = validate_output_rows(
            [make_row(amount_safe_to_pay="999999999")], requests_by_id=self.requests,
            require_full_coverage=False)
        self.assertTrue(any("exceeds requested_amount" in v for v in violations))

    def test_unknown_enum_rejected(self):
        violations = validate_output_rows(
            [make_row(affordability_status="maybe")], requests_by_id=self.requests,
            require_full_coverage=False)
        self.assertTrue(any("unknown value" in v for v in violations))
        violations = validate_output_rows(
            [make_row(recommended_payment_method="borrow")], requests_by_id=self.requests,
            require_full_coverage=False)
        self.assertTrue(any("unknown value" in v for v in violations))

    def test_duplicate_missing_and_extra_request_ids(self):
        rows = [make_row(), make_row()]
        violations = validate_output_rows(rows, requests_by_id=self.requests)
        self.assertTrue(any("duplicate request_id" in v for v in violations))
        self.assertTrue(any("missing predictions" in v for v in violations))
        violations = validate_output_rows(
            [make_row(request_id="request_999")], requests_by_id=self.requests)
        self.assertTrue(any("unexpected request_id" in v for v in violations))

    def test_affordable_now_requires_earliest_equals_request_date(self):
        # request_27: 2026-07-05 request date
        row = make_row(request_id="request_27", amount_safe_to_pay="6670",
                       affordability_status="affordable_now",
                       recommended_payment_method="full_payment",
                       payment_plan="2026-07-05:6670",
                       earliest_date_for_full_payment="2026-08-01")
        violations = validate_output_rows([row], requests_by_id=self.requests, require_full_coverage=False)
        self.assertTrue(any("affordable_now requires" in v for v in violations))
        # converse must NOT be flagged (D13): earliest == request_date with a
        # non-affordable_now status is legal (request_12 pattern)
        row_ok = make_row(request_id="request_27", amount_safe_to_pay="6000",
                          affordability_status="affordable_with_plan",
                          recommended_payment_method="wait",
                          payment_plan="2026-07-05:6000",
                          earliest_date_for_full_payment="2026-07-05")
        self.assertEqual(validate_output_rows([row_ok], requests_by_id=self.requests,
                                             require_full_coverage=False), [])

    def test_partial_payment_structural_rules(self):
        # request_19 allows partial (sample: partial_payment two payments)
        row = make_row(request_id="request_19", amount_safe_to_pay="28820",
                       affordability_status="affordable_with_plan",
                       recommended_payment_method="partial_payment",
                       payment_plan="2024-09-04:28820|2024-09-15:10840",
                       earliest_date_for_full_payment="2024-09-15")
        self.assertEqual(validate_output_rows([row], requests_by_id=self.requests, require_full_coverage=False), [])
        # three payments -> violation
        bad = make_row(request_id="request_19", amount_safe_to_pay="10000",
                       affordability_status="affordable_with_plan",
                       recommended_payment_method="partial_payment",
                       payment_plan="2024-09-04:10000|2024-09-10:10000|2024-09-15:19660",
                       earliest_date_for_full_payment="2024-09-15")
        violations = validate_output_rows([bad], requests_by_id=self.requests, require_full_coverage=False)
        self.assertTrue(any("exactly two payments" in v for v in violations))
        # sum mismatch -> violation
        bad2 = make_row(request_id="request_19", amount_safe_to_pay="28820",
                        affordability_status="affordable_with_plan",
                        recommended_payment_method="partial_payment",
                        payment_plan="2024-09-04:28820|2024-09-15:999",
                        earliest_date_for_full_payment="2024-09-15")
        violations = validate_output_rows([bad2], requests_by_id=self.requests, require_full_coverage=False)
        self.assertTrue(any("add up to requested_amount" in v for v in violations))

    def test_installments_must_match_supplied_option(self):
        # request_02 option_05: 3 x 15952906.67 from 2025-08-08 every 30 days
        good = make_row(request_id="request_02", amount_safe_to_pay="17229139.2",
                        affordability_status="affordable_with_plan",
                        recommended_payment_method="installments",
                        payment_plan=("2025-08-08:15952906.67|2025-09-07:15952906.67"
                                      "|2025-10-07:15952906.67"),
                        earliest_date_for_full_payment="2025-09-15")
        self.assertEqual(validate_output_rows([good], requests_by_id=self.requests,
                                              options_by_request=self.indexes.options_by_request_id,
                                              require_full_coverage=False), [])
        bad = make_row(request_id="request_02", amount_safe_to_pay="17229139.2",
                       affordability_status="affordable_with_plan",
                       recommended_payment_method="installments",
                       payment_plan="2025-08-08:100|2025-09-07:100",
                       earliest_date_for_full_payment="2025-09-15")
        violations = validate_output_rows([bad], requests_by_id=self.requests,
                                          options_by_request=self.indexes.options_by_request_id,
                                          require_full_coverage=False)
        self.assertTrue(any("does not exactly match" in v for v in violations))

    def test_spending_change_event_must_exist(self):
        row = make_row(spending_changes_needed="stop:event_999999")
        violations = validate_output_rows([row], requests_by_id=self.requests,
                                          events_by_id=self.indexes.events_by_event_id,
                                          require_full_coverage=False)
        self.assertTrue(any("unknown event" in v for v in violations))
        row_ok = make_row(spending_changes_needed="stop:event_476")
        self.assertEqual(validate_output_rows([row_ok], requests_by_id=self.requests,
                                              events_by_id=self.indexes.events_by_event_id,
                                              require_full_coverage=False), [])

    def test_full_coverage_check(self):
        # synthetic two-request bundle: coverage violations must be precise
        from code.schemas import RequestType
        def fake_request(rid):
            return Request(rid, "u", date(2026, 1, 1), RequestType.OTHER,
                           Decimal("100"), date(2026, 3, 1), False, "t")
        requests = {"r_a": fake_request("r_a"), "r_b": fake_request("r_b")}
        rows = [make_row(request_id="r_a")]
        violations = validate_output_rows(rows, requests_by_id=requests)
        self.assertTrue(any("missing predictions" in v and "r_b" in v for v in violations))
        rows2 = [make_row(request_id="r_a"), make_row(request_id="r_b"),
                 make_row(request_id="r_z")]
        violations = validate_output_rows(rows2, requests_by_id=requests)
        self.assertTrue(any("unexpected request_id" in v for v in violations))
        self.assertFalse(any("missing predictions" in v for v in violations))

    def test_empty_explanation_flagged(self):
        violations = validate_output_rows([make_row(decision_explanation="")],
                                          requests_by_id=self.requests,
                                          require_full_coverage=False)
        self.assertTrue(any("decision_explanation" in v for v in violations))

    def test_column_mismatch_reported(self):
        bad_row = {"request_id": "x"}  # missing everything else
        violations = validate_output_rows([bad_row], requests_by_id=self.requests)
        self.assertTrue(any("column mismatch" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
