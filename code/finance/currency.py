"""Deterministic FX conversion using only the official dated rate table.

Policy (D11, resolved in Phase 2): use the DIRECT same-date rate row for the
stated from->to direction (official rule, AGENTS.md §6.1). Empirical dataset
analysis proved every conversion pair required by the participant data has a
direct same-date rate, so no chaining or inverse-rate invention exists here.
A missing rate raises MissingRateError (clear diagnostic) rather than guessing.

Decimal only; no rounding applied (D16).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from ..errors import DataError
from ..indexes import Indexes


class MissingRateError(DataError):
    """No official rate row exists for the requested pair and date."""


class CurrencyConverter:
    def __init__(self, indexes: Indexes) -> None:
        self._indexes = indexes

    def convert(self, amount: Decimal, from_currency: str, to_currency: str,
                on_date: date, *, context: str | None = None) -> Decimal:
        """Convert exactly using the same-date official rate for the stated direction."""
        if from_currency == to_currency:
            return amount
        rate = self._indexes.get_rate(on_date, from_currency, to_currency)
        if rate is None:
            raise MissingRateError(
                f"no official {from_currency}->{to_currency} rate on {on_date.isoformat()} "
                f"(direct rates only; chaining/inverses are not invented)",
                identifier=context)
        return amount * rate
