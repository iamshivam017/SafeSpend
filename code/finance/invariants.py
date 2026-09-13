"""Invariant/property helpers for the financial engine (used by tests).

Each helper encodes a monotonicity property that must hold for ANY valid
input; a violation indicates a hidden logic bug rather than a fixture mismatch.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..schemas import FinancialProfile
from .simulator import SimulationResult, simulate
from .timeline import CashFlow


def min_balance(profile: FinancialProfile, request_date: date,
                flows: list[CashFlow], payments=None) -> Decimal:
    return simulate(profile, request_date, flows,
                    hypothetical_payments=payments, include_trace=False
                    ).minimum_projected_balance


def adding_debit_cannot_increase_safety(profile: FinancialProfile, request_date: date,
                                        flows: list[CashFlow],
                                        extra_debit: CashFlow) -> bool:
    """min_balance(with extra debit) <= min_balance(without)."""
    return min_balance(profile, request_date, flows + [extra_debit]) \
        <= min_balance(profile, request_date, flows)


def larger_payment_cannot_increase_minimum(profile: FinancialProfile, request_date: date,
                                           flows: list[CashFlow],
                                           payment_date: date,
                                           amount_small: Decimal,
                                           amount_large: Decimal) -> bool:
    from .simulator import Payment
    small = min_balance(profile, request_date, flows, [Payment(payment_date, amount_small)])
    large = min_balance(profile, request_date, flows, [Payment(payment_date, amount_large)])
    return large <= small


def removing_credit_cannot_improve_minimum(profile: FinancialProfile, request_date: date,
                                           flows: list[CashFlow],
                                           credit: CashFlow) -> bool:
    """Removing a settled credit must not raise the minimum projected balance."""
    return min_balance(profile, request_date, flows) \
        <= min_balance(profile, request_date, [f for f in flows if f != credit])


def moving_income_later_cannot_help_earlier_days(profile: FinancialProfile,
                                                 request_date: date,
                                                 credit: CashFlow,
                                                 later_date: date) -> bool:
    """Balance on any day <= credit date must not improve when the credit moves later."""
    early = simulate(profile, request_date, [credit], include_trace=True)
    moved = CashFlow(amount_home=credit.amount_home, effective_date=later_date,
                     category=credit.category, direction_value=credit.direction_value,
                     basis=credit.basis, source_event_ids=credit.source_event_ids,
                     essential=credit.essential, flexibility=credit.flexibility,
                     certainty=credit.certainty, event_type=credit.event_type)
    late = simulate(profile, request_date, [moved], include_trace=True)

    def min_until(result: SimulationResult, upto: date) -> Decimal:
        balances = [e.ending_balance for e in result.timeline if e.date <= upto]
        return min(balances) if balances else result.starting_balance

    return min_until(early, credit.effective_date) >= min_until(late, credit.effective_date)
