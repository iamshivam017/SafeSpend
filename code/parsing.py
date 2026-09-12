"""Centralized parsing/formatting utilities: money (Decimal), dates, ints, lists, bools.

Rules (docs/03 §3, DECISIONS D2/D16):
- Money is Decimal; binary floats are never used on the financial path.
- Blank != zero: blank parses to None, zero parses to Decimal("0").
- Parsed scale is preserved exactly ("100.50" stays 2 decimal places); no rounding
  is ever applied here (rounding policy is officially unspecified — OPEN, D16).
- Non-empty malformed values raise; no silent coercion, no defaults.
"""
import re
from datetime import date
from decimal import Decimal

from .errors import DateParseError, IntParseError, MoneyParseError

_MONEY_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_INT_RE = re.compile(r"^\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_money(raw: str | None, *, field: str, file: str | None = None,
                row: int | None = None, identifier: str | None = None) -> Decimal | None:
    """Parse a monetary CSV string to an exact Decimal.

    Blank/whitespace-only -> None (officially valid missing value; MUST NOT become 0).
    Raises MoneyParseError on anything else that is not a plain decimal literal
    (rejects thousands separators, scientific notation, currency symbols, NaN/Inf).
    """
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    if not _MONEY_RE.match(text):
        raise MoneyParseError(
            f"invalid monetary value {raw!r} for field {field!r} "
            f"(expected plain decimal like 100, 100.50, -100.50)",
            file=file, row=row, identifier=identifier)
    value = Decimal(text)
    if not value.is_finite():
        raise MoneyParseError(f"non-finite monetary value {raw!r} for field {field!r}",
                              file=file, row=row, identifier=identifier)
    return value


def format_money(value: Decimal) -> str:
    """Format a Decimal without scientific notation, preserving its scale.

    Decimal("100.50") -> "100.50"; Decimal("100") -> "100"; Decimal("0.00") -> "0.00".
    """
    return format(value, "f")


def parse_date(raw: str | None, *, field: str, file: str | None = None,
               row: int | None = None, identifier: str | None = None,
               nullable: bool = True) -> date | None:
    """Parse an official YYYY-MM-DD date. Blank -> None when nullable, else raises."""
    if raw is None or raw.strip() == "":
        if nullable:
            return None
        raise DateParseError(f"missing required date for field {field!r}",
                             file=file, row=row, identifier=identifier)
    text = raw.strip()
    if not _DATE_RE.match(text):
        raise DateParseError(f"invalid date {raw!r} for field {field!r} "
                             f"(expected YYYY-MM-DD)", file=file, row=row, identifier=identifier)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DateParseError(f"invalid date {raw!r} for field {field!r}: {exc}",
                             file=file, row=row, identifier=identifier) from None


def format_date(value: date | None) -> str:
    """Serialize a date back to the official YYYY-MM-DD string; None -> empty."""
    return value.isoformat() if value is not None else ""


def parse_int(raw: str | None, *, field: str, file: str | None = None,
              row: int | None = None, identifier: str | None = None) -> int | None:
    """Parse a non-negative integer field; blank -> None."""
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    if not _INT_RE.match(text):
        raise IntParseError(f"invalid integer {raw!r} for field {field!r}",
                            file=file, row=row, identifier=identifier)
    return int(text)


def parse_pipe_list(raw: str | None) -> list[str]:
    """Parse the canonical `|`-separated list field.

    "" -> []; "food" -> ["food"]; "food|rent" -> ["food", "rent"].
    Items are whitespace-trimmed; empty items (including from blank input) are dropped.
    """
    if raw is None or raw.strip() == "":
        return []
    return [item.strip() for item in raw.split("|") if item.strip() != ""]


def parse_bool(raw: str, *, field: str, file: str | None = None,
               row: int | None = None, identifier: str | None = None) -> bool:
    """Parse an official true/false field; anything else raises."""
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    from .errors import EnumValueError
    raise EnumValueError(f"invalid boolean {raw!r} for field {field!r} (expected true/false)",
                         file=file, row=row, identifier=identifier)
