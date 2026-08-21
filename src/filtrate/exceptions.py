class InvalidFilterError(ValueError):
    """Base error for a filter that cannot be compiled."""


class FilterCompilationError(InvalidFilterError):
    """A valid filter cannot be compiled for the active model."""


class BadRelationshipError(FilterCompilationError):
    """A Related node does not name a usable direct relationship."""
