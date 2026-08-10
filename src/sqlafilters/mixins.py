from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, not_, or_

from .exceptions import BadRelationshipError, FilterCompilationError

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.orm.relationships import RelationshipProperty

    from .filters import Filter, Match, Related
    from .types import FilterClause, Property

    type Fallback = Callable[[type[DeclarativeBase], str], Property[Any] | None]


def _normal_property(model: type[DeclarativeBase], name: str) -> Property[Any]:
    if name in model.__mapper__.relationships:
        raise FilterCompilationError(
            f"Property {name!r} on model {model.__name__} is a relationship"
        )

    try:
        return getattr(model, name)
    except Exception as error:
        raise FilterCompilationError(
            f"Unknown or unreadable property {name!r} on model {model.__name__}"
        ) from error


def _compile_match(
    model: type[DeclarativeBase], match: Match, fallback: Fallback | None
) -> FilterClause:
    try:
        property_ = _normal_property(model, match.property)
    except FilterCompilationError as original_error:
        if fallback is None:
            raise

        try:
            property_ = fallback(model, match.property)
        except Exception as error:
            raise error from original_error

        if property_ is None:
            raise

    return match.using.apply(property_)


def _relationship_for(
    model: type[DeclarativeBase], name: str
) -> RelationshipProperty[DeclarativeBase]:
    try:
        return model.__mapper__.relationships[name]
    except KeyError as error:
        raise BadRelationshipError(
            f"Unknown or non-relationship name {name!r} on model {model.__name__}"
        ) from error


def _compile_related(
    model: type[DeclarativeBase], related: Related, fallback: Fallback | None
) -> FilterClause:
    relationship = _relationship_for(model, related.relationship)
    child_clause = _compile_filter(relationship.mapper.class_, related.where, fallback)
    attribute = getattr(model, related.relationship)

    return (
        attribute.any(child_clause)
        if relationship.uselist
        else attribute.has(child_clause)
    )


def _compile_filter(
    model: type[DeclarativeBase], filter_: Filter, fallback: Fallback | None
) -> FilterClause:
    if filter_.via:
        clause = _compile_related(model, filter_.via, fallback)
    elif filter_.and_:
        clause = and_(
            *(_compile_filter(model, child, fallback) for child in filter_.and_)
        )
    elif filter_.or_:
        clause = or_(
            *(_compile_filter(model, child, fallback) for child in filter_.or_)
        )
    else:
        clause = _compile_match(model, cast("Match", filter_.match), fallback)

    return not_(clause) if filter_.negate else clause


class FilterableMixin:
    """Add immutable Filter compilation to a SQLAlchemy declarative model."""

    @classmethod
    def as_filtered_by(
        cls: type[DeclarativeBase], filter_: Filter, *, fallback: Fallback | None = None
    ) -> FilterClause:
        """Compile ``filter_`` into one SQLAlchemy Boolean where clause."""

        return _compile_filter(cls, filter_, fallback)
