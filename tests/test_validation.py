from collections.abc import Callable
from typing import Any, cast

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from filtrate import (
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
    ("operator", "operand", "hint"),
    [
        (LessThan, "invalid", "~Orderable"),
        (LessThanOrEqual, "invalid", "~Orderable"),
        (GreaterThan, "invalid", "~Orderable"),
        (GreaterThanOrEqual, "invalid", "~Orderable"),
        (Between, "invalid", r"tuple\[~Orderable"),
        (Contains, 1, "<class 'str'>"),
        (StartsWith, 1, "<class 'str'>"),
        (EndsWith, 1, "<class 'str'>"),
        (ContainsExact, 1, "<class 'str'>"),
        (StartsWithExact, 1, "<class 'str'>"),
        (EndsWithExact, 1, "<class 'str'>"),
        (OneOf, [1], r"tuple\[object"),
    ],
)
def test_operators_reject_incompatible_operands(
    operator: Callable[[Any], object], operand: object, hint: str
) -> None:
    with pytest.raises(InvalidFilterError, match=f"{hint}"):
        operator(operand)


def test_string_operator_accepts_association_proxy_remote_attribute() -> None:
    clause = Contains("value").apply(ValidationParent.tag_values)

    assert isinstance(clause, ColumnElement)
