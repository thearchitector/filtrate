from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

import pytest
from sqlalchemy import (
    JSON,
    ForeignKey,
    Integer,
    String,
    and_,
    create_engine,
    func,
    select,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    column_property,
    mapped_column,
    relationship,
)
from sqlalchemy.sql.elements import ColumnElement

from filtrate import (
    BadRelationshipError,
    Between,
    Contains,
    ContainsExact,
    Dynamic,
    EndsWith,
    EndsWithExact,
    Equals,
    Exists,
    Filter,
    FilterableMixin,
    FilterClause,
    FilterCompilationError,
    GreaterThan,
    GreaterThanOrEqual,
    InvalidFilterError,
    LessThan,
    LessThanOrEqual,
    Match,
    OneOf,
    Predicate,
    Property,
    Related,
    StartsWith,
    StartsWithExact,
)


class Base(DeclarativeBase):
    pass


class Parent(FilterableMixin, Base):
    __tablename__ = "parent"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    score: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    upper_name: Mapped[str] = column_property(func.upper(name, type_=String))
    children: Mapped[list[Child]] = relationship(back_populates="parent")
    profile: Mapped[Profile | None] = relationship(back_populates="parent")
    tags: Mapped[list[Tag]] = relationship(back_populates="parent")
    tag_values = association_proxy("tags", "value")

    @hybrid_property
    def name_length(self) -> int:
        return len(self.name)

    @name_length.inplace.expression
    @classmethod
    def _name_length_expression(cls) -> ColumnElement[int]:
        return cast("ColumnElement[int]", func.length(cls.name, type_=Integer))

    @hybrid_property
    def broken(self) -> int:
        return self.score

    @broken.inplace.expression
    @classmethod
    def _broken_expression(cls) -> ColumnElement[int]:
        raise RuntimeError("broken descriptor")


class Child(Base):
    __tablename__ = "child"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"))
    color: Mapped[str] = mapped_column(String)
    score: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String)
    value: Mapped[str] = mapped_column(String)
    parent: Mapped[Parent] = relationship(back_populates="children")
    grandchildren: Mapped[list[Grandchild]] = relationship(back_populates="child")


class Grandchild(Base):
    __tablename__ = "grandchild"

    id: Mapped[int] = mapped_column(primary_key=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("child.id"))
    label: Mapped[str] = mapped_column(String)
    child: Mapped[Child] = relationship(back_populates="grandchildren")


class Profile(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"), unique=True)
    status: Mapped[str] = mapped_column(String)
    parent: Mapped[Parent] = relationship(back_populates="profile")


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parent.id"))
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    parent: Mapped[Parent] = relationship(back_populates="tags")


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA case_sensitive_like=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        alpha = Parent(id=1, name="Alpha %_", score=1, payload={"x": 1})
        alpha.children = [
            Child(
                color="red",
                score=1,
                field="foo",
                value="hello",
                grandchildren=[Grandchild(label="leaf")],
            ),
            Child(color="blue", score=3, field="bar", value="hi"),
        ]
        alpha.profile = Profile(status="active")
        beta = Parent(id=2, name="beta", score=5, payload={"x": 2})
        beta.children = [Child(color="red", score=3, field="foo", value="say hi")]
        gamma = Parent(id=3, name="GAMMA", score=10, payload={"x": 3})
        null_tags = Parent(id=4, name="null tags", score=4, payload={})
        null_tags.tags = [Tag(value=None), Tag(value=None)]
        mixed_tags = Parent(id=5, name="mixed tags", score=5, payload={})
        mixed_tags.tags = [Tag(value=None), Tag(value="x")]
        values = Parent(id=6, name="values", score=6, payload={})
        values.tags = [Tag(value="x"), Tag(value="y")]
        db.add_all([alpha, beta, gamma, null_tags, mixed_tags, values])
        db.commit()
        yield db
    engine.dispose()


def leaf(property_: str, using: Predicate[Any], *, negate: bool = False) -> Filter:
    return Filter(match=Match(property=property_, using=using), negate=negate)


def ids(
    session: Session, filter_: Filter, *, dynamic: Dynamic | None = None
) -> list[int]:
    clause = Parent.as_filtered_by(filter_, dynamic=dynamic)
    return list(session.scalars(select(Parent.id).where(clause).order_by(Parent.id)))


@dataclass(frozen=True, slots=True)
class IsPositive(Predicate[int]):
    def apply(self, property: Property[int]) -> FilterClause:
        return property > 0


def test_equivalent_filters_used_as_cache_keys_retrieve_cached_values() -> None:
    first = leaf("id", Equals(1))
    second = leaf("name", Equals("Alpha %_"))
    ordered = Filter(and_=(first, second, first))
    cache = {
        ordered: "ordered group",
        leaf("score", Between((1, 5))): "range",
        leaf("id", OneOf((1, 1, 2))): "membership",
        leaf("id", Equals(1), negate=True): "negated leaf",
    }

    assert cache[Filter(and_=(first, second, first))] == "ordered group"
    assert cache[leaf("score", Between((1, 5)))] == "range"
    assert cache[leaf("id", OneOf((1, 1, 2)))] == "membership"
    assert Filter(and_=(second, first, first)) not in cache
    assert leaf("id", Equals(1)) not in cache


@pytest.mark.parametrize(
    ("property_", "predicate", "expected"),
    [
        ("score", Equals(5), [2, 5]),
        ("score", LessThan(5), [1, 4]),
        ("score", LessThanOrEqual(5), [1, 2, 4, 5]),
        ("score", GreaterThan(5), [3, 6]),
        ("score", GreaterThanOrEqual(5), [2, 3, 5, 6]),
        ("score", Between((1, 5)), [1, 2, 4, 5]),
        ("score", OneOf((1, 1, 10)), [1, 3]),
        ("score", Exists(), [1, 2, 3, 4, 5, 6]),
        ("name", EndsWith("TA"), [2]),
        ("name", StartsWithExact("GAM"), [3]),
        ("name", EndsWithExact("%_"), [1]),
    ],
)
def test_parent_rows_filtered_by_scalar_predicates_return_expected_ids(
    session: Session, property_: str, predicate: Predicate[Any], expected: list[int]
) -> None:
    assert ids(session, leaf(property_, predicate)) == expected


def test_name_filtered_by_builtin_starts_with_returns_matching_parent_id(
    session: Session,
) -> None:
    assert ids(session, leaf("name", StartsWith("G"))) == [3]


def test_score_filtered_by_custom_positive_predicate_returns_all_parent_ids(
    session: Session,
) -> None:
    assert ids(session, leaf("score", IsPositive())) == [1, 2, 3, 4, 5, 6]


def test_scalar_matches_with_negate_true_return_complementary_parent_ids(
    session: Session,
) -> None:
    assert ids(session, leaf("score", Equals(5), negate=True)) == [1, 3, 4, 6]
    assert ids(session, leaf("score", Exists(), negate=True)) == []


def test_names_filtered_by_containment_predicates_respect_case_and_literal_wildcards(
    session: Session,
) -> None:
    assert ids(session, leaf("name", Contains("alpha"))) == [1]
    assert ids(session, leaf("name", ContainsExact("Alpha"))) == [1]
    assert ids(session, leaf("name", ContainsExact("alpha"))) == []
    assert ids(session, leaf("name", Contains("%_"))) == [1]
    assert ids(session, leaf("name", Contains("%"))) == [1]
    assert ids(session, leaf("name", Contains("_"))) == [1]


def test_grouped_matches_against_column_and_hybrid_properties_return_parent_ids(
    session: Session,
) -> None:
    grouped = Filter(
        and_=(
            Filter(or_=(leaf("score", Equals(1)), leaf("score", Equals(10)))),
            leaf("name", Contains("a")),
        )
    )
    assert ids(session, grouped) == [1, 3]
    assert ids(session, leaf("upper_name", Equals("BETA"))) == [2]
    assert ids(session, leaf("name_length", GreaterThan(5))) == [1, 4, 5, 6]


def test_root_and_nested_groups_with_negate_true_return_complementary_parent_ids(
    session: Session,
) -> None:
    scores = (leaf("score", Equals(1)), leaf("score", Equals(10)))
    assert ids(session, Filter(or_=scores, negate=True)) == [2, 4, 5, 6]

    nested = Filter(and_=(Filter(or_=scores, negate=True), leaf("name", Contains("a"))))
    assert ids(session, nested) == [2, 4, 5, 6]


def test_dynamic_can_override_existing_property(session: Session) -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        if model is Parent and match.property == "name":
            return match.using.apply(Parent.score)
        return None

    assert ids(session, leaf("name", Equals(5)), dynamic=dynamic) == [2, 5]


def test_declining_dynamic_uses_existing_property(session: Session) -> None:
    calls: list[tuple[type[DeclarativeBase], Match]] = []

    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        calls.append((model, match))
        return None

    filter_ = leaf("name", Equals("beta"))
    assert ids(session, filter_, dynamic=dynamic) == [2]
    assert calls == [(Parent, filter_.match)]


@pytest.mark.parametrize("name", ["missing", "children", "broken"])
def test_missing_or_unusable_properties_with_dynamic_return_dynamic_matches(
    session: Session, name: str
) -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        if model is Parent and match.property == name:
            return match.using.apply(Parent.score)
        return None

    assert ids(session, leaf(name, Equals(5)), dynamic=dynamic) == [2, 5]


@pytest.mark.parametrize("name", ["missing", "children", "broken"])
def test_unusable_property_with_declining_dynamic_raises_compilation_error(
    name: str,
) -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        return None

    with pytest.raises(FilterCompilationError, match=name):
        Parent.as_filtered_by(leaf(name, Equals(1)), dynamic=dynamic)


def test_repeated_dynamic_match_in_and_group_returns_matching_parent_ids(
    session: Session,
) -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        if model is Parent and match.property == "alias":
            return match.using.apply(Parent.score)
        return None

    duplicated = Filter(
        and_=(leaf("alias", GreaterThan(0)), leaf("alias", LessThan(3)))
    )
    assert ids(session, duplicated, dynamic=dynamic) == [1]


def test_raising_dynamic_immediately_raises_compilation_error() -> None:
    def exploding(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        raise RuntimeError("dynamic exploded")

    with pytest.raises(FilterCompilationError, match=r"name.*Parent") as exc_info:
        Parent.as_filtered_by(leaf("name", Equals("beta")), dynamic=exploding)

    assert isinstance(exc_info.value.__cause__, RuntimeError)


def test_dynamic_can_compile_child_fields_against_the_same_row(
    session: Session,
) -> None:
    def dynamic_fields(
        model: type[DeclarativeBase], match: Match
    ) -> FilterClause | None:
        if model is not Parent:
            return None

        return Parent.children.any(
            and_(Child.field == match.property, match.using.apply(Child.value))
        )

    dynamic_filter = leaf("foo", Contains("hi"))
    assert ids(session, dynamic_filter, dynamic=dynamic_fields) == [2]
    assert ids(
        session, Filter(match=dynamic_filter.match, negate=True), dynamic=dynamic_fields
    ) == [1, 3, 4, 5, 6]


def related(name: str, where: Filter) -> Filter:
    return Filter(via=Related(relationship=name, where=where))


def test_collection_and_scalar_related_filters_return_matching_parent_ids(
    session: Session,
) -> None:
    assert ids(session, related("children", leaf("color", Equals("red")))) == [1, 2]
    assert ids(session, related("profile", leaf("status", Equals("active")))) == [1]
    assert ids(session, related("children", leaf("color", Equals("missing")))) == []
    assert ids(session, related("profile", leaf("status", Equals("missing")))) == []


def test_outer_and_inner_relationship_negation_return_scope_specific_parent_ids(
    session: Session,
) -> None:
    outer_collection = Filter(
        via=Related(relationship="children", where=leaf("color", Equals("red"))),
        negate=True,
    )
    inner_collection = related("children", leaf("color", Equals("red"), negate=True))
    assert ids(session, outer_collection) == [3, 4, 5, 6]
    assert ids(session, inner_collection) == [1]

    outer_scalar = Filter(
        via=Related(relationship="profile", where=leaf("status", Equals("active"))),
        negate=True,
    )
    inner_scalar = related("profile", leaf("status", Equals("active"), negate=True))
    assert ids(session, outer_scalar) == [2, 3, 4, 5, 6]
    assert ids(session, inner_scalar) == []


def test_related_matches_grouped_in_one_scope_return_parent_with_same_related_row(
    session: Session,
) -> None:
    same_row = related(
        "children",
        Filter(and_=(leaf("color", Equals("red")), leaf("score", Equals(3)))),
    )
    assert ids(session, same_row) == [2]


def test_sibling_related_matches_in_and_group_return_parents_with_independent_rows(
    session: Session,
) -> None:
    siblings = Filter(
        and_=(
            related("children", leaf("color", Equals("red"))),
            related("children", leaf("score", Equals(3))),
        )
    )
    assert ids(session, siblings) == [1, 2]


def test_related_filters_nested_across_two_hops_return_matching_parent_ids(
    session: Session,
) -> None:
    nested = related(
        "children", related("grandchildren", leaf("label", Equals("leaf")))
    )
    assert ids(session, nested) == [1]


def test_related_match_with_target_model_dynamic_returns_matching_parent_ids(
    session: Session,
) -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        if model is Child and match.property == "shade":
            return match.using.apply(Child.color)
        return None

    clause = related("children", leaf("shade", Equals("blue")))
    assert ids(session, clause, dynamic=dynamic) == [1]


def test_missing_or_non_relationship_names_used_as_related_raise_relationship_error() -> (
    None
):
    for name in ("missing", "name"):
        with pytest.raises(BadRelationshipError, match=r"Parent|relationship"):
            Parent.as_filtered_by(related(name, leaf("id", Equals(1))))


def test_unknown_nested_property_used_in_related_filter_raises_compilation_error() -> (
    None
):
    with pytest.raises(FilterCompilationError, match=r"Child.*missing|missing.*Child"):
        Parent.as_filtered_by(related("children", leaf("missing", Equals(1))))


def test_invalid_relationship_does_not_invoke_dynamic() -> None:
    def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
        raise AssertionError("dynamic is only for Match properties")

    with pytest.raises(BadRelationshipError):
        Parent.as_filtered_by(
            related("missing", leaf("id", Equals(1))), dynamic=dynamic
        )


def test_association_proxy_with_equals_exists_and_negation_returns_parent_ids(
    session: Session,
) -> None:
    assert ids(session, leaf("tag_values", Equals("x"))) == [5, 6]
    assert ids(session, leaf("tag_values", Equals("x"), negate=True)) == [1, 2, 3, 4]
    assert ids(session, leaf("tag_values", Exists())) == [5, 6]
    assert ids(session, leaf("tag_values", Exists(), negate=True)) == [1, 2, 3, 4]


def test_proxy_equality_and_negated_related_match_return_parent_with_both_values(
    session: Session,
) -> None:
    independent = Filter(
        and_=(
            leaf("tag_values", Equals("x")),
            related("tags", leaf("value", Equals("x"), negate=True)),
        )
    )
    assert ids(session, independent) == [6]


def test_invalid_property_and_relationship_compiled_via_public_api_raise_base_error() -> (
    None
):
    with pytest.raises(InvalidFilterError):
        Parent.as_filtered_by(leaf("missing", Equals(1)))
    with pytest.raises(InvalidFilterError):
        Parent.as_filtered_by(related("missing", leaf("id", Equals(1))))
