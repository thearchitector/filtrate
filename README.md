<!-- pragma: no ai -->
# filtrate

![PyPI Downloads](https://img.shields.io/pypi/dm/filtrate?style=flat)
[![bear-ified](https://raw.githubusercontent.com/beartype/beartype-assets/main/badge/bear-ified.svg)](https://beartype.readthedocs.io)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/thearchitector/filtrate/ci.yaml?style=flat)

Build reusable, composable filters for declarative SQLAlchemy models.

It supports:

- building filters with AND, OR, and negation at any depth
- filtering ORM properties
  - mapped columns
  - hybrid proprties
  - relationships
  - association proxies
- dynamic properties backed by custom SQL expressions
- a bunch of built-in operators and predicates, such as `Contains`, `OneOf`, `Exists` etc.
- a capability system to keep Predicates reusable and type-safe, and support filtering on custom ORM types

Requires Python 3.14 and SQLAlchemy `>=2,<2.1`. Type checked.

## Installation

```bash
python -m pip install filtrate
# or
uv add filtrate
```

## Quick start

Add `FilterableMixin` to a declarative model, construct a `Filter`, and use `as_filtered_by()` anywhere SQLAlchemy accepts a where clause:

```python
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from filtrate import Equals, Filter, FilterableMixin, Match


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

Filters are frozen and hashable, making them safe to reuse as cache keys or compare as values.

### Built-in predicates

Predicates describe an operation applied to a property:

| Family | Predicates |
| --- | --- |
| Comparison | `Equals`, `OneOf` |
| Ordering | `LessThan`, `LessThanOrEqual`, `GreaterThan`, `GreaterThanOrEqual`, `Between` |
| Text | `Contains`, `StartsWith`, `EndsWith` and their `Exact` variants |
| Presence | `Exists` |

Text Predicates escape `%` and `_`. The default variants are case-insensitive; `Exact` variants are case-sensitive.

## Composing filters

Filters compose with `and_`, `or_`, and `negate`:

```python
from filtrate import Contains, GreaterThan, OneOf

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
```

Filters, at any level, can be negated:

```python
not_42 = Filter(match=Match(property="age", using=Equals(42)), negate=True)
```

## Filter relationships

You can filter models by their relationships using `Related`. Its entire inner filter will apply to the same related row:

```python
from filtrate import Related

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

### Association proxies

Direct column-targeted association proxies work like ordinary properties:

```python
from sqlalchemy import ForeignKey
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship
from filtrate import Contains, Filter, FilterableMixin, Match


class Foo(Base):
    __tablename__ = "foo"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Bar(FilterableMixin, Base):
    __tablename__ = "bar"

    id: Mapped[int] = mapped_column(primary_key=True)
    foo_id: Mapped[int] = mapped_column(ForeignKey("foo.id"))
    foo: Mapped[Foo] = relationship()

    foo_name = association_proxy("foo", "name")


filter_ = Filter(match=Match(property="foo_name", using=Contains("python")))
```

## Extending the library

### Custom predicates

You can implement custom Predicates to expose more filtering logic in your applications.

Just subclass `Predicate` (or `Operator` if your custom logic takes operands) and implement  `apply`:

```python
from filtrate import FilterClause, Operator, Property, register


# you can also use @dataclass, but this decorator will do that for you AND enable runtime type checking!
@register
class IsDivisibleBy(Operator[int]):
    operand: int

    def apply(self, property: Property[int]) -> FilterClause:
        return property % self.operand == 0
```

### Dynamic properties

Pass `dynamic` to support filter names that are not ordinary model attributes. For example, a filter can expose
the domain portion of an email address without adding a mapped property:

```python
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from filtrate import Contains, FilterClause


def dynamic(model: type[DeclarativeBase], match: Match) -> FilterClause | None:
    if match.property == "email_domain":
        domain = func.substr(User.email, func.instr(User.email, "@") + 1)
        return match.using.apply(domain)


filter_ = Filter(match=Match(property="email_domain", using=Contains("example")))
clause = User.as_filtered_by(filter_, dynamic=dynamic)
```

Returning a clause handles the match; doing nothing (`return None`) falls back to the model's ordinary attributes.

### Custom type capabilities

A capability is a type's declaration that it supports a particular kind of Predicate.

A type is responsible for making an operation work, including any special handling it requires, so the Predicate can remain general and reusable.

Text Predicates require `Capability.TEXTUAL`, and ordering Predicates require `Capability.ORDERED`.
Equality, membership, and presence Predicates are unrestricted.

Custom SQLAlchemy types must declare the operations they support:

```python
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator
from filtrate import Capability, filter_capabilities


@filter_capabilities(Capability.TEXTUAL)
class CaseFoldedText(TypeDecorator[str]):
    impl = String
    cache_ok = True
```

## License

BSD 3-Clause Clear.
