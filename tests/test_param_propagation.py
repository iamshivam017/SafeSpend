"""Phase 5 reconciliation: parameter-propagation regression test.

Proves that ProvisionParams scope/occurrences/statistic changes measurably
affect reserve flows through the production build_cash_timeline path.
This test would FAIL under the old shadowing implementation (where
timeline.py constructed a fresh ProvisionParams() ignoring module globals).
"""
import unittest

from _bootstrap import ROOT  # noqa: F401
from _finance_fixture import D, ev, profile

from code.data_loader import load_all
from code.evidence.apply import collect_claims
from code.indexes import Indexes
from code.evidence.apply import build_request_state
from code.finance import recurrence as rec
from code.finance.timeline import build_cash_timeline
from code.schemas import EventDirection


class ParamPropagationTests(unittest.TestCase):
    """Changing ProvisionParams must measurably change reserve flows."""

    @classmethod
    def setUpClass(cls):
        cls.bundle = load_all()
        cls.indexes = Indexes.build(cls.bundle)
        cls.claims = collect_claims(cls.bundle)

    def _request_and_profile(self, request_id):
        s = next(x for x in self.bundle.samples
                 if x.request.request_id == request_id)
        profile = self.indexes.profiles_by_user_id[s.request.user_id]
        return s.request, profile

    def _lifecycle(self, request, user_events):
        from code.finance.lifecycle import resolve_lifecycle
        return resolve_lifecycle(user_events, request.request_date)

    def _patterns(self, request, user_events):
        from code.finance.recurrence import detect_recurring_patterns
        return detect_recurring_patterns(user_events)

    def test_scope_changes_reserve_count(self):
        """request_13 has non-protected variable streams (dining, transport).
        scope=all must produce more reserves than scope=protected."""
        request, _ = self._request_and_profile("request_13")
        user_events = self.indexes.events_by_user_id.get(request.user_id, [])
        profile = self.indexes.profiles_by_user_id[request.user_id]

        results = {}
        for scope in ("protected", "all"):
            pp = rec.ProvisionParams(scope=scope, occurrences=1, statistic="median")
            saved = rec.DEFAULT_PROVISION_PARAMS
            rec.DEFAULT_PROVISION_PARAMS = pp
            try:
                lc = self._lifecycle(request, user_events)
                pats = self._patterns(request, user_events)
                tl = build_cash_timeline(profile, request.request_date,
                                         lc, pats, self.indexes)
                reserves = [f for f in tl.flows
                            if f.basis == "essential_provision"]
                results[scope] = len(reserves)
            finally:
                rec.DEFAULT_PROVISION_PARAMS = saved

        self.assertGreater(results["all"], results["protected"],
                           f"scope=all should produce more reserves: {results}")

    def test_occurrences_change_reserve_count(self):
        """request_13 has 2 protected variable streams (groceries, transport);
        occurrences=2 should produce 2x the reserves of occurrences=1."""
        request, _ = self._request_and_profile("request_13")
        user_events = self.indexes.events_by_user_id.get(request.user_id, [])
        profile = self.indexes.profiles_by_user_id[request.user_id]

        results = {}
        for occ in (1, 2):
            pp = rec.ProvisionParams(scope="protected", occurrences=occ, statistic="median")
            saved = rec.DEFAULT_PROVISION_PARAMS
            rec.DEFAULT_PROVISION_PARAMS = pp
            try:
                lc = self._lifecycle(request, user_events)
                pats = self._patterns(request, user_events)
                tl = build_cash_timeline(profile, request.request_date,
                                         lc, pats, self.indexes)
                reserves = [f for f in tl.flows
                            if f.basis == "essential_provision"]
                results[occ] = len(reserves)
            finally:
                rec.DEFAULT_PROVISION_PARAMS = saved

        self.assertEqual(results[2], results[1] * 2,
                         "occurrences=2 should double the reserve count")

    def test_variable_discretionary_reserve_present_when_scope_all(self):
        """request_13 has dining (variable, discretionary, willing-to-reduce).
        Under scope=all, a dining reserve must appear (it doesn't under
        scope=protected since dining is not a protected category)."""
        request, _ = self._request_and_profile("request_13")
        user_events = self.indexes.events_by_user_id.get(request.user_id, [])
        profile = self.indexes.profiles_by_user_id[request.user_id]

        pp = rec.ProvisionParams(scope="all", occurrences=1, statistic="median")
        saved = rec.DEFAULT_PROVISION_PARAMS
        rec.DEFAULT_PROVISION_PARAMS = pp
        try:
            lc = self._lifecycle(request, user_events)
            pats = self._patterns(request, user_events)
            tl = build_cash_timeline(profile, request.request_date,
                                     lc, pats, self.indexes)
            reserve_cats = {f.category for f in tl.flows
                            if f.basis == "essential_provision"}
            self.assertIn("dining", reserve_cats,
                          "scope=all should include dining reserve for user_13")
        finally:
            rec.DEFAULT_PROVISION_PARAMS = saved

    def test_no_reserve_leakage_between_variants(self):
        """After running a variant, the next variant must start from clean state."""
        request, _ = self._request_and_profile("request_13")
        user_events = self.indexes.events_by_user_id.get(request.user_id, [])
        profile = self.indexes.profiles_by_user_id[request.user_id]

        # run scope=all first
        pp_all = rec.ProvisionParams(scope="all", occurrences=2, statistic="median")
        saved = rec.DEFAULT_PROVISION_PARAMS
        rec.DEFAULT_PROVISION_PARAMS = pp_all
        try:
            lc = self._lifecycle(request, user_events)
            pats = self._patterns(request, user_events)
            build_cash_timeline(profile, request.request_date,
                                lc, pats, self.indexes)
        finally:
            rec.DEFAULT_PROVISION_PARAMS = saved

        # now run scope=protected: must produce fewer reserves (no leakage)
        pp_prot = rec.ProvisionParams(scope="protected", occurrences=1,
                                      statistic="median")
        rec.DEFAULT_PROVISION_PARAMS = pp_prot
        try:
            lc = self._lifecycle(request, user_events)
            pats = self._patterns(request, user_events)
            tl = build_cash_timeline(profile, request.request_date,
                                     lc, pats, self.indexes)
            reserves = [f for f in tl.flows if f.basis == "essential_provision"]
            for f in reserves:
                self.assertIn(f.category,
                              profile.expense_categories_to_protect)
        finally:
            rec.DEFAULT_PROVISION_PARAMS = saved


if __name__ == "__main__":
    unittest.main()
