import unittest
from datetime import date
from decimal import Decimal

from _bootstrap import ROOT  # noqa: F401

from code.data_loader import load_all
from code.errors import DuplicateIdError
from code.indexes import Indexes


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_all()
        cls.indexes = Indexes.build(cls.bundle)

    def test_unique_indexes_cover_all_rows(self):
        self.assertEqual(len(self.indexes.profiles_by_user_id), len(self.bundle.profiles))
        self.assertEqual(len(self.indexes.events_by_event_id), len(self.bundle.events))
        self.assertEqual(len(self.indexes.requests_by_request_id), len(self.bundle.requests))
        self.assertEqual(len(self.indexes.samples_by_request_id), len(self.bundle.samples))
        self.assertEqual(len(self.indexes.options_by_option_id), len(self.bundle.options))

    def test_grouped_indexes(self):
        # user_01..user_03 appear in samples; events grouped per user
        u03_events = self.indexes.events_by_user_id["user_03"]
        self.assertTrue(all(e.user_id == "user_03" for e in u03_events))
        # options for request_01 (sample) grouped deterministically
        opts = self.indexes.options_by_request_id["request_01"]
        self.assertEqual([o.payment_option_id for o in opts],
                         sorted(o.payment_option_id for o in opts))
        # messages/images groups
        self.assertEqual(len(self.indexes.images_by_related_event_id), 16)
        self.assertTrue(all(im.file_exists for im in self.indexes.images_by_request_id["request_03"]))

    def test_rate_lookup_by_date_and_pair(self):
        rate = self.indexes.get_rate(date(2023, 10, 15), "EUR", "ZAR")
        self.assertEqual(rate, Decimal("20"))
        self.assertIsNone(self.indexes.get_rate(date(2023, 10, 15), "ZAR", "EUR"))  # direction matters
        self.assertIsNone(self.indexes.get_rate(date(1999, 1, 1), "EUR", "ZAR"))  # missing date

    def test_duplicate_index_detects_conflicts(self):
        from types import SimpleNamespace
        bundle = load_all()
        bundle.profiles = list(bundle.profiles) + [bundle.profiles[0]]
        with self.assertRaises(DuplicateIdError):
            Indexes.build(bundle)


if __name__ == "__main__":
    unittest.main()
