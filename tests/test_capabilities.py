from collections.abc import Callable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any, cast

import pytest
from sqlalchemy import (
    CHAR,
    DECIMAL,
    NCHAR,
    NVARCHAR,
    VARCHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    Float,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    Unicode,
    UnicodeText,
    column,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

from filtrate import (
    Between,
    Capability,
    Contains,
    ContainsExact,
    EndsWith,
    EndsWithExact,
    Equals,
    Exists,
    GreaterThan,
    GreaterThanOrEqual,
    InvalidFilterError,
    LessThan,
    LessThanOrEqual,
    OneOf,
    Predicate,
    StartsWith,
    StartsWithExact,
    filter_capabilities,
)


class Choice(Enum):
    FIRST = "first"
    SECOND = "second"


@filter_capabilities(Capability.TEXTUAL)
class TextChoiceType(TypeDecorator[Choice]):
    impl = String
    cache_ok = True


@filter_capabilities(Capability.ORDERED)
class OrderedChoiceType(TypeDecorator[Choice]):
    impl = Integer
    cache_ok = True


class OpaqueStringType(TypeDecorator[str]):
    impl = String
    cache_ok = True


class OpaqueIntegerType(TypeDecorator[int]):
    impl = Integer
    cache_ok = True


@filter_capabilities(Capability.TEXTUAL)
class TextCapableType(TypeDecorator[str]):
    impl = String
    cache_ok = True


@filter_capabilities(Capability.ORDERED)
class TextAndOrderingType(TextCapableType):
    pass


class UnknownType(TypeEngine[str]):
    pass


@pytest.mark.parametrize(
    "type_",
    [
        pytest.param(String(), id="string"),
        pytest.param(Text(), id="text"),
        pytest.param(Unicode(), id="unicode"),
        pytest.param(UnicodeText(), id="unicode-text"),
        pytest.param(CHAR(), id="char"),
        pytest.param(VARCHAR(), id="varchar"),
        pytest.param(NCHAR(), id="nchar"),
        pytest.param(NVARCHAR(), id="nvarchar"),
    ],
)
@pytest.mark.parametrize(
    "predicate",
    [
        pytest.param(Contains("value"), id="contains"),
        pytest.param(StartsWith("value"), id="starts-with"),
        pytest.param(EndsWith("value"), id="ends-with"),
        pytest.param(ContainsExact("value"), id="contains-exact"),
        pytest.param(StartsWithExact("value"), id="starts-with-exact"),
        pytest.param(EndsWithExact("value"), id="ends-with-exact"),
    ],
)
def test_string_family_supports_all_text_predicates(
    type_: TypeEngine[Any], predicate: Predicate[str]
) -> None:
    property_ = cast("Any", column("value", type_))

    assert isinstance(predicate.apply(property_), ColumnElement)


@pytest.mark.parametrize(
    ("type_", "operand"),
    [
        pytest.param(Integer(), 1, id="integer"),
        pytest.param(SmallInteger(), 1, id="small-integer"),
        pytest.param(BigInteger(), 1, id="big-integer"),
        pytest.param(Float(), 1.5, id="float"),
        pytest.param(Double(), 1.5, id="double"),
        pytest.param(Numeric(), Decimal("1.5"), id="numeric"),
        pytest.param(DECIMAL(), Decimal("1.5"), id="decimal"),
        pytest.param(Date(), date(2026, 1, 2), id="date"),
        pytest.param(
            DateTime(timezone=True),
            datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
            id="datetime",
        ),
        pytest.param(Time(), time(3, 4), id="time"),
    ],
)
@pytest.mark.parametrize(
    "predicate_factory",
    [
        pytest.param(lambda operand: LessThan(operand), id="less-than"),
        pytest.param(lambda operand: LessThanOrEqual(operand), id="less-than-equal"),
        pytest.param(lambda operand: GreaterThan(operand), id="greater-than"),
        pytest.param(
            lambda operand: GreaterThanOrEqual(operand), id="greater-than-equal"
        ),
        pytest.param(lambda operand: Between((operand, operand)), id="between"),
    ],
)
def test_orderable_families_support_all_ordered_predicates(
    type_: TypeEngine[Any], operand: object, predicate_factory: Callable[[Any], Any]
) -> None:
    property_ = cast("Any", column("value", type_))
    predicate = predicate_factory(operand)

    assert isinstance(predicate.apply(property_), ColumnElement)


def test_restricted_predicates_reject_cross_family_properties() -> None:
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        Contains("value").apply(cast("Any", column("count", Integer())))

    with pytest.raises(InvalidFilterError, match="violates type hint"):
        LessThan(1).apply(cast("Any", column("value", String())))

    with pytest.raises(InvalidFilterError, match="violates type hint"):
        Between((1, 2)).apply(cast("Any", column("value", String())))


def test_plain_sqlalchemy_enum_has_no_restricted_capabilities() -> None:
    property_ = cast("Any", column("choice", SQLAlchemyEnum(Choice)))

    with pytest.raises(InvalidFilterError, match="violates type hint"):
        Contains("first").apply(property_)
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        LessThan(1).apply(property_)


def test_decorated_type_decorators_support_declared_capabilities() -> None:
    text_property = cast("Any", column("choice", TextChoiceType()))
    ordered_property = cast("Any", column("choice", OrderedChoiceType()))

    assert isinstance(Contains("first").apply(text_property), ColumnElement)
    assert isinstance(LessThan(1).apply(ordered_property), ColumnElement)


@pytest.mark.parametrize(
    ("type_", "predicate"),
    [(OpaqueStringType(), Contains("value")), (OpaqueIntegerType(), LessThan(1))],
)
def test_undecorated_type_decorator_is_opaque(
    type_: TypeEngine[Any], predicate: object
) -> None:
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        cast("Any", predicate).apply(cast("Any", column("value", type_)))


def test_capability_declarations_are_additive_and_inherited() -> None:
    property_ = cast("Any", column("value", TextAndOrderingType()))

    assert isinstance(Contains("value").apply(property_), ColumnElement)
    assert isinstance(LessThan(1).apply(property_), ColumnElement)


def test_stacked_and_duplicate_capability_declarations_are_additive() -> None:
    @filter_capabilities(Capability.TEXTUAL)
    @filter_capabilities(Capability.ORDERED, Capability.TEXTUAL, Capability.ORDERED)
    class StackedType(TypeDecorator[str]):
        impl = String
        cache_ok = True

    property_ = cast("Any", column("value", StackedType()))

    assert isinstance(Contains("value").apply(property_), ColumnElement)
    assert isinstance(LessThan(1).apply(property_), ColumnElement)


def test_capability_decorator_preserves_class_identity() -> None:
    class IdentityType(TypeEngine[str]):
        pass

    decorated = filter_capabilities(Capability.TEXTUAL)(IdentityType)

    assert decorated is IdentityType


def test_capability_decorator_can_replace_inherited_capabilities() -> None:
    @filter_capabilities(Capability.ORDERED, replace=True)
    class ReplacedCapabilitiesType(TextCapableType):
        pass

    property_ = cast("Any", column("value", ReplacedCapabilitiesType()))

    assert isinstance(LessThan(1).apply(property_), ColumnElement)
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        Contains("value").apply(property_)


@pytest.mark.parametrize("type_", [Boolean(), UnknownType()])
def test_unrestricted_predicates_accept_types_without_capabilities(
    type_: TypeEngine[Any],
) -> None:
    property_ = cast("Any", column("value", type_))

    assert isinstance(Equals("value").apply(property_), ColumnElement)
    assert isinstance(OneOf(("value",)).apply(property_), ColumnElement)
    assert isinstance(Exists().apply(property_), ColumnElement)
