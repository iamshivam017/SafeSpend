"""Integration tests: real official datasets load, sane counts, no mutation."""
import hashlib
import unittest
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401

from code import config
from code.data_loader import (load_all, load_events, load_exchange_rates, load_images,
                              load_messages, load_payment_options, load_profiles,
                              load_requests, load_sample_requests, validate_relationships)
from code.errors import HeaderError
from code.schemas import EventStatus


class DatasetLoadTests(unittest.TestCase):
    def test_all_datasets_load_and_official_counts_hold(self):
        bundle = load_all()
        self.assertEqual(len(bundle.requests), 250)
        self.assertEqual(len(bundle.samples), 25)
        self.assertEqual(len(bundle.profiles), 275)
        self.assertEqual(len(bundle.events), 25342)
        self.assertEqual(len(bundle.options), 790)
        self.assertEqual(len(bundle.rates), 134)
        self.assertEqual(len(bundle.messages), 215)
        self.assertEqual(len(bundle.images), 16)

    def test_requests_shape(self):
        requests = load_requests()
        first = requests[0]
        self.assertEqual(first.request_id, "request_26")
        self.assertEqual(first.user_id, "user_26")
        self.assertIsInstance(first.requested_amount, Decimal)
        self.assertTrue(all(r.request_text for r in requests))

    def test_blank_event_amounts_stay_none(self):
        events = load_events()
        blanks = [e for e in events if e.amount is None]
        self.assertEqual(len(blanks), 16)  # officially valid; image-resolvable
        for event in blanks:
            self.assertIsNone(event.amount)
        # every blank-amount event is resolvable via the official images mapping
        images = load_images()
        linked = {im.related_event_id for im in images}
        self.assertEqual({e.event_id for e in blanks}, linked)

    def test_sample_answers_parse(self):
        samples = load_sample_requests()
        r02 = next(s for s in samples if s.request.request_id == "request_02")
        self.assertEqual(r02.recommended_payment_method.value, "installments")
        self.assertEqual(r02.amount_safe_to_pay, Decimal("17229139.2"))
        self.assertEqual(r02.affordability_status.value, "affordable_with_plan")
        r19 = next(s for s in samples if s.request.request_id == "request_19")
        self.assertEqual(r19.recommended_payment_method.value, "partial_payment")

    def test_nullable_fields_preserved(self):
        events = load_events()
        blank_settlement = [e for e in events if e.settlement_date is None]
        self.assertEqual(len(blank_settlement), 10)  # all unrealized/valuation rows
        linked = [e for e in events if e.linked_event_id is not None]
        self.assertEqual(len(linked), 58)
        messages = load_messages()
        self.assertEqual(sum(1 for m in messages if m.related_event_id is not None), 39)

    def test_status_and_flexibility_domain_holds_on_real_data(self):
        events = load_events()
        statuses = {e.status for e in events}
        self.assertEqual(statuses, set(EventStatus))
        flex = {e.flexibility.value for e in events}
        self.assertEqual(flex, {"fixed", "reducible", "stoppable", "reducible_or_stoppable"})

    def test_profile_preferences_parse(self):
        profiles = load_profiles()
        u02 = next(p for p in profiles if p.user_id == "user_02")
        self.assertEqual([m.value for m in u02.payment_methods_user_will_consider],
                         ["partial_payment", "installments"])
        self.assertEqual(u02.max_installment_months, 7)
        blank_max = [p for p in profiles if p.max_installment_months is None]
        self.assertEqual(len(blank_max), 119)  # blank = will not consider installments
        self.assertEqual(u02.expense_categories_to_protect,
                         ["housing", "utilities", "education"])

    def test_image_files_exist(self):
        images = load_images()
        self.assertTrue(all(im.file_exists for im in images))
        self.assertTrue(all(im.image_path.endswith(".png") for im in images))

    def test_relationship_validation_passes_on_official_data(self):
        bundle = load_all()
        self.assertEqual(validate_relationships(bundle), [])

    def test_loaders_do_not_mutate_source_files(self):
        def snapshot():
            return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in config.ALL_DATASET_FILES}
        before = snapshot()
        load_all()
        self.assertEqual(snapshot(), before)

    def test_wrong_header_fails_fast(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "requests.csv"
            bad.write_text("wrong,header\n1,2\n", encoding="utf-8")
            with self.assertRaises(HeaderError) as ctx:
                load_requests(bad)
            self.assertIn("missing columns", str(ctx.exception))

    def test_exchange_rate_lookup_shape(self):
        rates = load_exchange_rates()
        sample = rates[0]
        self.assertEqual(sample.from_currency, "EUR")
        self.assertEqual(sample.to_currency, "ZAR")
        self.assertEqual(sample.rate, Decimal("20"))


if __name__ == "__main__":
    unittest.main()
