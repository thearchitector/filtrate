from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any, TypeVar, dataclass_transform

from .capabilities import Capability, IsCapable
from .types import FilterClause, Property, beartype

Orderable = TypeVar("Orderable", int, float, Decimal, date, time, datetime, timedelta)

OrderableProperty = Annotated[Property[Orderable], IsCapable(Capability.ORDERED)]
StrProperty = Annotated[Property[str], IsCapable(Capability.TEXTUAL)]


class Predicate[T](ABC):
    @abstractmethod
    def apply(self, property: Property[T]) -> FilterClause:
        raise NotImplementedError()


@dataclass_transform(frozen_default=True)
def register[O: Predicate[Any]](type: type[O]) -> type[O]:
    return beartype(dataclass(type, frozen=True, slots=True))


@dataclass(frozen=True, slots=True)
class Operator[T, OT = T](Predicate[T], ABC):
    operand: OT


@register
class Exists(Predicate[object]):
    def apply(self, property: Property[object]) -> FilterClause:
        return property.is_not(None)


@register
class Equals(Operator[object]):
    operand: object

    def apply(self, property: Property[object]) -> FilterClause:
        return property == self.operand


@register
class LessThan(Operator[Orderable]):
    operand: Orderable

    def apply(self, property: OrderableProperty[Orderable]) -> FilterClause:
        return property < self.operand


@register
class LessThanOrEqual(Operator[Orderable]):
    operand: Orderable

    def apply(self, property: OrderableProperty[Orderable]) -> FilterClause:
        return property <= self.operand


@register
class GreaterThan(Operator[Orderable]):
    operand: Orderable

    def apply(self, property: OrderableProperty[Orderable]) -> FilterClause:
        return property > self.operand


@register
class GreaterThanOrEqual(Operator[Orderable]):
    operand: Orderable

    def apply(self, property: OrderableProperty[Orderable]) -> FilterClause:
        return property >= self.operand


@register
class Between(Operator[Orderable, tuple[Orderable, Orderable]]):
    operand: tuple[Orderable, Orderable]

    def apply(self, property: OrderableProperty[Orderable]) -> FilterClause:
        return property.between(*self.operand)


@register
class Contains(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.icontains(self.operand, autoescape=True)


@register
class StartsWith(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.istartswith(self.operand, autoescape=True)


@register
class EndsWith(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.iendswith(self.operand, autoescape=True)


@register
class ContainsExact(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.contains(self.operand, autoescape=True)


@register
class StartsWithExact(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.startswith(self.operand, autoescape=True)


@register
class EndsWithExact(Operator[str]):
    operand: str

    def apply(self, property: StrProperty) -> FilterClause:
        return property.endswith(self.operand, autoescape=True)


@register
class OneOf(Operator[object, tuple[object, ...]]):
    operand: tuple[object, ...]

    def apply(self, property: Property[object]) -> FilterClause:
        return property.in_(self.operand)
