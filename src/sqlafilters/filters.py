from dataclasses import dataclass
from typing import Any

from .operators import Predicate


@dataclass(frozen=True, slots=True, kw_only=True)
class Match:
    property: str
    using: Predicate[Any]


@dataclass(frozen=True, slots=True, kw_only=True)
class Related:
    relationship: str
    where: Filter


@dataclass(frozen=True, slots=True, kw_only=True)
class Filter:
    match: Match | None = None
    and_: tuple[Filter, ...] | None = None
    or_: tuple[Filter, ...] | None = None
    via: Related | None = None
    negate: bool = False
