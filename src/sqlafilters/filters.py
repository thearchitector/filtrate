from dataclasses import dataclass
from typing import Any

from .exceptions import InvalidFilterError
from .operators import Predicate
from .types import beartype


@beartype
@dataclass(frozen=True, slots=True, kw_only=True)
class Match:
    property: str
    using: Predicate[Any]


@beartype
@dataclass(frozen=True, slots=True, kw_only=True)
class Related:
    relationship: str
    where: Filter


@beartype
@dataclass(frozen=True, slots=True, kw_only=True)
class Filter:
    match: Match | None = None
    and_: tuple[Filter, ...] | None = None
    or_: tuple[Filter, ...] | None = None
    via: Related | None = None
    negate: bool = False

    def __post_init__(self) -> None:
        if (
            sum(arg is not None for arg in (self.match, self.and_, self.or_, self.via))
            != 1
        ):
            raise InvalidFilterError(
                "Filters require a match, and set, or set, or via relation."
            )
