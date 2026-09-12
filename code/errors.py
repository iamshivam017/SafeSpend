"""Deterministic error types with record-level context.

Every error carries enough context (file, row number, identifier) to debug the
exact offending record. No error is ever silently swallowed by this package.
"""


class SafeSpendError(Exception):
    """Base class for all deterministic project errors."""


class DataError(SafeSpendError):
    """A structured data problem, annotated with file/row/identifier context."""

    def __init__(self, message: str, *, file: str | None = None,
                 row: int | None = None, identifier: str | None = None) -> None:
        context = []
        if file is not None:
            context.append(f"file={file}")
        if row is not None:
            context.append(f"row={row}")
        if identifier:
            context.append(f"id={identifier}")
        super().__init__(message + (f" [{'; '.join(context)}]" if context else ""))
        self.message = message
        self.file = file
        self.row = row
        self.identifier = identifier


class HeaderError(DataError):
    """CSV header missing required columns or carrying unexpected ones."""


class DuplicateIdError(DataError):
    """A primary identifier that must be unique appears more than once."""


class MoneyParseError(DataError):
    """A non-empty monetary value could not be parsed as an exact Decimal."""


class DateParseError(DataError):
    """A non-empty date value is not a valid YYYY-MM-DD date."""


class IntParseError(DataError):
    """A non-empty integer value could not be parsed."""


class EnumValueError(DataError):
    """A value outside the official controlled set for a field."""


class RelationshipError(DataError):
    """A mandatory cross-file relationship does not resolve."""


class OutputValidationError(SafeSpendError):
    """Prediction rows violate the official output contract."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__(f"{len(self.violations)} output contract violation(s): "
                         + " | ".join(self.violations[:10]))
