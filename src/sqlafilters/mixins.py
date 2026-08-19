from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, not_, or_
from sqlalchemy.orm import DeclarativeBase

from .exceptions import BadRelationshipError, FilterCompilationError
from .filters import Filter, Match
from .types import FilterClause

if TYPE_CHECKING:
    from typing import Any

    from sqlalchemy.orm import InstrumentedAttribute
    from sqlalchemy.orm.relationships import RelationshipProperty

    from .filters import Related
    from .types import Property


type Dynamic = Callable[[type[DeclarativeBase], Match], FilterClause | None]


def _normal_property(model: type[DeclarativeBase], name: str) -> Property[Any]:
    if name in model.__mapper__.relationships:
        raise FilterCompilationError(
            f"Property {name!r} on model {model.__name__} is a relationship"
        )

    try:
        return cast("Property[Any]", getattr(model, name))
    except Exception as error:
        raise FilterCompilationError(
            f"Unknown or unreadable property {name!r} on model {model.__name__}"
        ) from error


def _compile_match(
    model: type[DeclarativeBase], match: Match, dynamic: Dynamic | None
) -> FilterClause:
    if dynamic is not None:
        try:
            dynamic_clause = dynamic(model, match)
        except Exception as error:
            raise FilterCompilationError(
                f"Dynamic property {match.property!r} failed on model {model.__name__}"
            ) from error

        if dynamic_clause is not None:
            return dynamic_clause

    property_ = _normal_property(model, match.property)
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
    model: type[DeclarativeBase], related: Related, dynamic: Dynamic | None
) -> FilterClause:
    relationship = _relationship_for(model, related.relationship)
    child_clause = _compile_filter(relationship.mapper.class_, related.where, dynamic)
    attribute = cast("InstrumentedAttribute[Any]", getattr(model, related.relationship))

    return (
        attribute.any(child_clause)
        if relationship.uselist
        else attribute.has(child_clause)
    )


def _compile_filter(
    model: type[DeclarativeBase], filter_: Filter, dynamic: Dynamic | None
) -> FilterClause:
    if filter_.via:
        clause = _compile_related(model, filter_.via, dynamic)
    elif filter_.and_:
        clause = and_(
            *(_compile_filter(model, child, dynamic) for child in filter_.and_)
        )
    elif filter_.or_:
        clause = or_(*(_compile_filter(model, child, dynamic) for child in filter_.or_))
    else:
        clause = _compile_match(model, cast("Match", filter_.match), dynamic)

    return not_(clause) if filter_.negate else clause


class FilterableMixin:
    """Add immutable Filter compilation to a SQLAlchemy declarative model."""

    @classmethod
    def as_filtered_by(  # type: ignore[misc]
        cls: type[DeclarativeBase], filter_: Filter, *, dynamic: Dynamic | None = None
    ) -> FilterClause:
        """Compile ``filter_`` into one SQLAlchemy Boolean where clause."""

        return _compile_filter(cls, filter_, dynamic)
