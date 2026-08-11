# sqlafilters

[![bear-ified](https://raw.githubusercontent.com/beartype/beartype-assets/main/badge/bear-ified.svg)](https://beartype.readthedocs.io)

`sqlafilters` lets you arbitrarily filter declarative SQLAlchemy models.

Requires Python 3.14 and SQLAlchemy `>=2,<2.1`. Type checked.

## Quick start

```python
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlafilters import Equals, Filter, FilterableMixin, Match


class Base(DeclarativeBase):
    pass


class User(FilterableMixin, Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
    age: Mapped[int]


filter_ = Filter(match=Match(property="age", using=Equals(42)))
statement = select(User).where(User.as_filtered_by(filter_))
```

Filters compose with `and_`, `or_`, and `negate` at any depth:

```python
from sqlafilters import Contains, GreaterThan, OneOf

filter_ = Filter(
    and_=(
        Filter(match=Match(property="age", using=GreaterThan(17))),
        Filter(
            or_=(
                Filter(match=Match(property="email", using=Contains("@example"))),
                Filter(match=Match(property="id", using=OneOf((1, 2, 3)))),
            )
        ),
    )
)

not_42 = Filter(match=Match(property="age", using=Equals(42)), negate=True)
```

`Filter`, `Match`, `Related`, and built-in Predicates are frozen, hashable values.

## Relationships

`Related` applies its complete inner filter to one related row. Collections use
SQLAlchemy's `.any()` and scalar relationships use `.has()`:

```python
from sqlafilters import Related

filter_ = Filter(
    via=Related(
        relationship="orders",
        where=Filter(
            and_=(
                Filter(match=Match(property="status", using=Equals("open"))),
                Filter(match=Match(property="total", using=GreaterThan(100))),
            )
        ),
    )
)
```

Nest `Related` for multiple hops. Dotted property names do not imply traversal.

Direct column-targeted association proxies work like ordinary properties:

```python
filter_ = Filter(match=Match(property="tag_names", using=Equals("python")))
```

## Fallback matches

When normal property resolution fails, `fallback` receives the active model and
the complete `Match`, and returns a Boolean clause. A computed property is one line:

```python
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from sqlafilters import Contains, FilterClause


def fallback(
    model: type[DeclarativeBase], match: Match
) -> FilterClause | None:
    if model is User and match.property == "email_domain":
        domain = func.substr(User.email, func.instr(User.email, "@") + 1)
        return match.using.apply(domain)
    return None


filter_ = Filter(match=Match(property="email_domain", using=Contains("example")))
clause = User.as_filtered_by(filter_, fallback=fallback)
```

The same hook can compile dynamic key/value children. Given `Parent.children` and
`Child(field, value)`:

```python
from sqlalchemy import and_


def child_fields(
    model: type[DeclarativeBase], match: Match
) -> FilterClause | None:
    if model is not Parent:
        return None

    return Parent.children.any(
        and_(
            Child.field == match.property,
            match.using.apply(Child.value),
        )
    )


filter_ = Filter(match=Match(property="foo", using=Contains("hi")))
clause = Parent.as_filtered_by(filter_, fallback=child_fields)
```

This produces one correlated `EXISTS`, so `field == "foo"` and the value predicate
must match the same child. Readable mapped properties always win; returning `None`
preserves the original `FilterCompilationError`.

## Predicates

| Family | Predicates |
| --- | --- |
| Comparison | `Equals`, `OneOf` |
| Ordering | `LessThan`, `LessThanOrEqual`, `GreaterThan`, `GreaterThanOrEqual`, `Between` |
| Text | `Contains`, `StartsWith`, `EndsWith` and their `Exact` variants |
| Presence | `Exists` |

Text predicates escape `%` and `_`. The default variants are case-insensitive;
`Exact` variants use SQLAlchemy's case-sensitive operations. Negate a containing
`Filter` instead of using separate not-equal or not-exists predicates.

Custom Predicates implement `apply`:

```python
from dataclasses import dataclass
from sqlafilters import Operator, Property


@dataclass(frozen=True, slots=True)
class IsDivisibleBy(Operator[int]):
    operand: int

    def apply(self, property: Property[int]) -> FilterClause:
        return property % self.operand == 0
```

## Errors and safety

Unknown properties raise `FilterCompilationError`; invalid `Related` names raise
`BadRelationshipError`. Predicate errors propagate unchanged, while fallback errors
are chained from the original property-resolution error.

Treat custom Predicates and fallbacks as trusted SQL construction. Applications
accepting untrusted filters should allowlist properties and relationships and bound
tree depth, width, and match count.
