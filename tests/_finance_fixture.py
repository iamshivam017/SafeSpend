"""Synthetic fixture builders for Phase 2 finance-engine tests."""
import sys
from datetime import date
from decimal import Decimal

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code.schemas import (EventDirection, EventStatus, EventType, FinancialEvent,
                          FinancialProfile, Flexibility)

_seq = [0]


def ev(event_id="e", *, user="user_x", type=EventType.EXPENSE, category="groceries",
       direction=EventDirection.DEBIT, amount="100", currency="USD",
       event_date=date(2026, 1, 1), settlement=None, status=EventStatus.SETTLED,
       linked=None, flexibility=Flexibility.FIXED, min_allowed=None):
    _seq[0] += 1
    return FinancialEvent(
        event_id=event_id or f"e{_seq[0]}", user_id=user, event_type=type,
        description=f"test {category}", category=category, direction=direction,
        amount=None if amount is None else Decimal(amount), currency=currency,
        event_date=event_date, settlement_date=settlement, status=status,
        linked_event_id=linked, flexibility=flexibility,
        minimum_allowed_amount=None if min_allowed is None else Decimal(min_allowed))


def profile(user="user_x", home="USD", balance="1000", minimum="200",
            protected=("rent", "groceries"), reduce=("dining",), stop=("streaming",),
            methods=("full_payment",), max_months=None):
    return FinancialProfile(
        user_id=user, home_currency=home,
        current_available_balance=Decimal(balance),
        minimum_balance_to_keep=Decimal(minimum),
        financial_priorities=[], expense_categories_to_protect=list(protected),
        expense_categories_user_is_willing_to_reduce=list(reduce),
        expense_categories_user_is_willing_to_stop=list(stop),
        payment_methods_user_will_consider=list(methods),
        max_installment_months=max_months)


D = date(2026, 1, 1)  # canonical request date for synthetic tests
