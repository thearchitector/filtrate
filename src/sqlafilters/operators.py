from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from .types import FilterClause, Property

Orderable = TypeVar("Orderable", int, float, Decimal, date, time, datetime, timedelta)


class Predicate[T](ABC):
    @abstractmethod
    def apply(self, property: Property[T]) -> FilterClause: ...


@dataclass(frozen=True, slots=True)
class Operator[T, OT = T](Predicate[T], ABC):
    operand: OT


@dataclass(frozen=True, slots=True)
class Equals(Operator[Any]):
    def apply(self, property: Property[Any]) -> FilterClause:
        return property == self.operand


@dataclass(frozen=True, slots=True)
class Exists(Predicate[Any]):
    def apply(self, property: Property[Any]) -> FilterClause:
        return property.is_not(None)


@dataclass(frozen=True, slots=True)
class LessThan(Operator[Orderable]):
    def apply(self, property: Property[Orderable]) -> FilterClause:
        return property < self.operand


@dataclass(frozen=True, slots=True)
class LessThanOrEqual(Operator[Orderable]):
    def apply(self, property: Property[Orderable]) -> FilterClause:
        return property <= self.operand


@dataclass(frozen=True, slots=True)
class GreaterThan(Operator[Orderable]):
    def apply(self, property: Property[Orderable]) -> FilterClause:
        return property > self.operand


@dataclass(frozen=True, slots=True)
class GreaterThanOrEqual(Operator[Orderable]):
    def apply(self, property: Property[Orderable]) -> FilterClause:
        return property >= self.operand


@dataclass(frozen=True, slots=True)
class Between(Operator[Orderable, tuple[Orderable, Orderable]]):
    def apply(self, property: Property[Orderable]) -> FilterClause:
        return property.between(*self.operand)


@dataclass(frozen=True, slots=True)
class Contains(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.icontains(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class StartsWith(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.istartswith(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class EndsWith(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.iendswith(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class ContainsExact(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.contains(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class StartsWithExact(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.startswith(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class EndsWithExact(Operator[str]):
    def apply(self, property: Property[str]) -> FilterClause:
        return property.endswith(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class OneOf(Operator[Any, tuple[Any, ...]]):
    def apply(self, property: Property[Any]) -> FilterClause:
        return property.in_(self.operand)
