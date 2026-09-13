import unittest
from datetime import date, timedelta
from decimal import Decimal

from _finance_fixture import D, ev
from code.finance.lifecycle import resolve_lifecycle


class LifecycleStatusRuleTests(unittest.TestCase):
    def test_settled_past_ignored_already_in_balance(self):
        r = resolve_lifecycle([ev(amount="100", event_date=date(2025, 12, 1),
                                  settlement=date(2025, 12, 1))], D)
        self.assertEqual(r.cash_events, [])
        self.assertIn("already in starting balance", r.ignored[0].reason)

    def test_settled_future_counts_on_settlement(self):
        r = resolve_lifecycle([ev(amount="100", event_date=date(2026, 1, 5),
                                  settlement=date(2026, 1, 10))], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertEqual(r.cash_events[0].effective_date, date(2026, 1, 10))
        self.assertEqual(r.cash_events[0].basis, "settled")

    def test_cancelled_ignored(self):
        r = resolve_lifecycle([ev(status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.CANCELLED)], D)
        self.assertEqual(r.cash_events, [])

    def test_failed_ignored(self):
        from code.schemas import EventStatus
        r = resolve_lifecycle([ev(status=EventStatus.FAILED)], D)
        self.assertEqual(r.cash_events, [])

    def test_unrealized_not_cash(self):
        from code.schemas import EventDirection, EventStatus, EventType
        r = resolve_lifecycle([ev(type=EventType.INVESTMENT_VALUATION,
                                  direction=EventDirection.NON_CASH,
                                  status=EventStatus.UNREALIZED, settlement=None,
                                  event_date=date(2026, 2, 1))], D)
        self.assertEqual(r.cash_events, [])
        self.assertIn("unrealized", r.ignored[0].reason)

    def test_scheduled_counts_on_settlement(self):
        r = resolve_lifecycle([ev(status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.SCHEDULED,
                                  event_date=date(2026, 1, 5), settlement=date(2026, 1, 8))], D)
        self.assertEqual(r.cash_events[0].effective_date, date(2026, 1, 8))
        self.assertEqual(r.cash_events[0].basis, "scheduled")


class PendingTests(unittest.TestCase):
    def test_pending_debit_reserved_day0_when_already_incurred(self):
        r = resolve_lifecycle([ev(status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.PENDING,
                                  event_date=date(2025, 12, 30), settlement=date(2026, 1, 3))], D)
        self.assertEqual(r.cash_events[0].basis, "pending_debit_reserved")
        self.assertEqual(r.cash_events[0].effective_date, D)  # reserved today, not later

    def test_pending_debit_future_event_reserved_on_event_date(self):
        from code.schemas import EventStatus
        r = resolve_lifecycle([ev(status=EventStatus.PENDING,
                                  event_date=date(2026, 1, 20), settlement=date(2026, 1, 25))], D)
        self.assertEqual(r.cash_events[0].effective_date, date(2026, 1, 20))

    def test_pending_credit_ignored(self):
        from code.schemas import EventDirection, EventStatus
        r = resolve_lifecycle([ev(direction=EventDirection.CREDIT,
                                  status=EventStatus.PENDING,
                                  event_date=date(2025, 12, 30))], D)
        self.assertEqual(r.cash_events, [])
        self.assertIn("pending credit", r.ignored[0].reason)


class LifecycleGroupTests(unittest.TestCase):
    def test_pending_to_settled_group_counts_once(self):
        # pending debit reserved, then a settled representation appears in the
        # same lifecycle: settled wins, pending dropped (double-count prevention)
        settled = ev("e_settled", amount="100", event_date=date(2026, 1, 5),
                     settlement=date(2026, 1, 6))
        pending = ev("e_pending", amount="100", event_date=date(2026, 1, 4),
                     settlement=date(2026, 1, 7),
                     status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.PENDING,
                     linked="e_settled")
        r = resolve_lifecycle([settled, pending], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertEqual(r.cash_events[0].source_event_ids, ("e_settled",))
        self.assertTrue(any("e_pending" in i.event_id for i in r.ignored))

    def test_pending_to_cancelled_group_drops_pending(self):
        from code.schemas import EventStatus
        cancelled = ev("e_c", status=EventStatus.CANCELLED, event_date=date(2025, 12, 20),
                       settlement=date(2025, 12, 22))
        pending = ev("e_p", status=EventStatus.PENDING, event_date=date(2025, 12, 19),
                     settlement=date(2026, 1, 5), linked="e_c")
        r = resolve_lifecycle([cancelled, pending], D)
        self.assertEqual(r.cash_events, [])

    def test_pending_to_failed_group_drops_pending(self):
        from code.schemas import EventStatus
        failed = ev("e_f", status=EventStatus.FAILED, event_date=date(2025, 12, 20),
                    settlement=date(2025, 12, 20))
        pending = ev("e_p2", status=EventStatus.PENDING, event_date=date(2025, 12, 19),
                     settlement=date(2026, 1, 5), linked="e_f")
        r = resolve_lifecycle([failed, pending], D)
        self.assertEqual(r.cash_events, [])

    def test_settled_to_pending_refund_ignores_refund_keeps_parent(self):
        from code.schemas import EventDirection, EventStatus, EventType
        parent = ev("e_par", amount="500", event_date=date(2025, 12, 1),
                    settlement=date(2025, 12, 2))
        refund = ev("e_ref", type=EventType.REFUND, direction=EventDirection.CREDIT,
                    amount="500", event_date=date(2026, 1, 2), settlement=date(2026, 1, 12),
                    status=EventStatus.PENDING, linked="e_par")
        r = resolve_lifecycle([parent, refund], D)
        self.assertEqual(r.cash_events, [])  # parent pre-request (in balance); refund pending credit ignored

    def test_settled_to_settled_refund_counts_both(self):
        from code.schemas import EventDirection, EventType
        parent = ev("e_par2", amount="500", event_date=date(2026, 1, 2),
                    settlement=date(2026, 1, 3))
        refund = ev("e_ref2", type=EventType.REFUND, direction=EventDirection.CREDIT,
                    amount="500", event_date=date(2026, 1, 20),
                    settlement=date(2026, 1, 21), linked="e_par2")
        r = resolve_lifecycle([parent, refund], D)
        self.assertEqual(len(r.cash_events), 2)

    def test_cancelled_to_settled_retry_counts_child_only(self):
        from code.schemas import EventStatus
        parent = ev("e_old", amount="816.2", status=EventStatus.CANCELLED,
                    event_date=date(2026, 1, 14), settlement=date(2026, 1, 16))
        child = ev("e_new", amount="816.2", event_date=date(2026, 1, 16),
                   settlement=date(2026, 1, 17), linked="e_old")
        r = resolve_lifecycle([parent, child], D)
        self.assertEqual([c.source_event_ids for c in r.cash_events], [("e_new",)])

    def test_settled_to_pending_expense_representation_dropped(self):
        # observed dataset shape: identical amount 11 days later = re-presentation
        parent = ev("e_shop", amount="134.75", event_date=date(2025, 12, 26),
                    settlement=date(2025, 12, 27))
        child = ev("e_shop2", amount="134.75",
                   status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.PENDING,
                   event_date=date(2026, 1, 6), settlement=date(2026, 1, 10),
                   linked="e_shop")
        r = resolve_lifecycle([parent, child], D)
        self.assertEqual(r.cash_events, [])
        self.assertTrue(any("re-presentation" in i.reason for i in r.ignored))

    def test_distinct_pending_movement_still_reserved(self):
        # settled parent + pending child with a DIFFERENT amount = distinct movement
        parent = ev("e_p1", amount="100", event_date=date(2025, 12, 26),
                    settlement=date(2025, 12, 27))
        child = ev("e_p2", amount="999",
                   status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.PENDING,
                   event_date=date(2026, 1, 6), settlement=date(2026, 1, 10),
                   linked="e_p1")
        r = resolve_lifecycle([parent, child], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertEqual(r.cash_events[0].amount, Decimal("999"))

    def test_duplicate_substance_collapsed(self):
        a = ev("dup_a", amount="50", event_date=date(2026, 1, 2), settlement=date(2026, 1, 3))
        b = ev("dup_b", amount="50", event_date=date(2026, 1, 2), settlement=date(2026, 1, 3))
        r = resolve_lifecycle([a, b], D)
        self.assertEqual(len(r.cash_events), 1)
        self.assertTrue(any("duplicate substance" in i.reason for i in r.ignored))


class UnresolvedAmountTests(unittest.TestCase):
    def test_in_horizon_blank_amount_is_unresolved_not_zero(self):
        r = resolve_lifecycle([ev(amount=None, status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.SCHEDULED,
                                  event_date=date(2026, 1, 4), settlement=date(2026, 1, 6))], D)
        self.assertEqual(r.cash_events, [])
        self.assertEqual(len(r.unresolved), 1)
        self.assertEqual(r.unresolved[0].effective_date, date(2026, 1, 6))

    def test_historical_blank_amount_ignored_as_in_balance(self):
        r = resolve_lifecycle([ev(amount=None, event_date=date(2025, 12, 30),
                                  settlement=date(2025, 12, 30))], D)
        self.assertEqual(r.cash_events, [])
        self.assertEqual(len(r.unresolved), 0)
        self.assertTrue(any("already in balance" in i.reason for i in r.ignored))

    def test_resolved_amounts_interface_supplies_value(self):
        # Phase 4 hook: external evidence resolves the blank amount without engine rewrite
        r = resolve_lifecycle([ev("blank1", amount=None,
                                  status=__import__("code.schemas", fromlist=["EventStatus"]).EventStatus.SCHEDULED,
                                  event_date=date(2026, 1, 4), settlement=date(2026, 1, 6))], D,
                              resolved_amounts={"blank1": Decimal("123.45")})
        self.assertEqual(len(r.cash_events), 1)
        self.assertEqual(r.cash_events[0].amount, Decimal("123.45"))
        self.assertTrue(r.cash_events[0].resolved_from_evidence)

    def test_provenance_preserved(self):
        r = resolve_lifecycle([ev("prov1", amount="10", event_date=date(2026, 1, 2),
                                  settlement=date(2026, 1, 3))], D)
        self.assertEqual(r.cash_events[0].source_event_ids, ("prov1",))
        self.assertTrue(r.ignored or r.cash_events)  # trace always explains every record


if __name__ == "__main__":
    unittest.main()
