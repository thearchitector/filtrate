from collections.abc import Callable
from typing import Any, cast

import pytest
from sqlalchemy import ForeignKey, Integer, String, column
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from sqlafilters import (
    Between,
    Contains,
    ContainsExact,
    EndsWith,
    EndsWithExact,
    Equals,
    Filter,
    GreaterThan,
    GreaterThanOrEqual,
    InvalidFilterError,
    LessThan,
    LessThanOrEqual,
    Match,
    OneOf,
    Related,
    StartsWith,
    StartsWithExact,
)


class ValidationBase(DeclarativeBase):
    pass


class ValidationParent(ValidationBase):
    __tablename__ = "validation_parent"

    id: Mapped[int] = mapped_column(primary_key=True)
    tags: Mapped[list[ValidationTag]] = relationship()
    tag_values = association_proxy("tags", "value")


class ValidationTag(ValidationBase):
    __tablename__ = "validation_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("validation_parent.id"))
    value: Mapped[str] = mapped_column(String)


VALID_MATCH = Match(property="id", using=Equals(1))
VALID_LEAF = Filter(match=VALID_MATCH)
VALID_RELATED = Related(relationship="tags", where=VALID_LEAF)


def test_filter_rejects_missing_clause() -> None:
    with pytest.raises(InvalidFilterError, match="Filters require"):
        Filter()


@pytest.mark.parametrize(
    "arguments",
    [
        {"match": VALID_MATCH, "and_": (VALID_LEAF,)},
        {"and_": (VALID_LEAF,), "or_": (VALID_LEAF,)},
        {"or_": (VALID_LEAF,), "via": VALID_RELATED},
    ],
)
def test_filter_rejects_multiple_clauses(arguments: dict[str, object]) -> None:
    with pytest.raises(InvalidFilterError, match="Filters require"):
        Filter(**cast("Any", arguments))


@pytest.mark.parametrize(
    ("operator", "operand", "msg"),
    [
        (LessThan, "invalid", "violates type hint ~Orderable"),
        (LessThanOrEqual, "invalid", "violates type hint ~Orderable"),
        (GreaterThan, "invalid", "violates type hint ~Orderable"),
        (GreaterThanOrEqual, "invalid", "violates type hint ~Orderable"),
        (Between, "invalid", r"violates type hint tuple\[~Orderable"),
        (Contains, 1, "not instance of str"),
        (StartsWith, 1, "not instance of str"),
        (EndsWith, 1, "not instance of str"),
        (ContainsExact, 1, "not instance of str"),
        (StartsWithExact, 1, "not instance of str"),
        (EndsWithExact, 1, "not instance of str"),
        (OneOf, [1], "not instance of tuple"),
    ],
)
def test_operators_reject_incompatible_operands(
    operator: Callable[[Any], object], operand: object, msg: str
) -> None:
    with pytest.raises(InvalidFilterError, match=msg):
        operator(operand)


def test_string_operator_rejects_non_string_property() -> None:
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        Contains("value").apply(cast("Any", column("score", Integer)))


def test_ordering_operator_rejects_non_orderable_property() -> None:
    with pytest.raises(InvalidFilterError, match="violates type hint"):
        LessThan(1).apply(cast("Any", column("name", String)))


def test_string_operator_accepts_association_proxy_remote_attribute() -> None:
    clause = Contains("value").apply(ValidationParent.tag_values)

    assert isinstance(clause, ColumnElement)
