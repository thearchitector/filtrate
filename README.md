# sqlafilters

`sqlafilters` builds immutable filter values and compiles them into SQLAlchemy 2.0
Boolean expressions. Consumers keep ownership of queries, sessions, serialization,
and the policy that decides which fields callers may use.

It requires Python 3.14 and SQLAlchemy `>=2,<2.1`.

## Model integration

Add `FilterableMixin` to a declarative model, construct a `Filter`, and attach the
result of `as_filtered_by()` to any SQLAlchemy statement:

The supported model contract is a concrete mapped subclass of `DeclarativeBase`.
Applications own the `DeclarativeBase` subclass, registry, and metadata;
`FilterableMixin` only adds filter compilation. Imperative mapping and
decorator-only declarative mapping are not supported. `MappedAsDataclass` is
optional and is supported when used with `DeclarativeBase`.

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

Filter values are frozen, slotted, structurally comparable, and hashable. Every
Filter has a `negate` flag, defaulting to `False`, that logically negates that
node's complete compiled expression. `and_` and `or_` take non-empty tuples; they
preserve child order and duplicates.

```python
from sqlafilters import Contains, GreaterThan, OneOf

filter_ = Filter(
    and_=(
        Filter(match=Match(property="age", using=GreaterThan(17))),
        Filter(
            or_=(
                Filter(match=Match(property="email", using=Contains("@example"))),
                Filter(match=Match(property="id", using=OneOf((1, 2, 2)))),
            )
        ),
    )
)
```

Negation works at any depth. For example, this selects users whose age is not 42:

```python
filter_ = Filter(
    match=Match(property="age", using=Equals(42)),
    negate=True,
)
```

## Relationship scopes

`Related` names one direct mapped relationship. Collection relationships compile
through `any()` and scalar relationships through `has()`:

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

Both matches above apply to the same order. Separate sibling `Related` nodes are
independent existential scopes and may be satisfied by different rows. Express
multiple relationship hops with nested `Related` values; dotted names never imply
traversal.

## Fallback properties

A trusted fallback can recover from any normal property compilation failure. It
receives the active model—including a relationship target model—and the exact
literal property name:

```python
from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase
from sqlafilters import Contains, Property


def fallback(model: type[DeclarativeBase], name: str) -> Property[str] | None:
    if model is User and name == "email_domain":
        return func.substr(User.email, func.instr(User.email, "@") + 1)
    return None


filter_ = Filter(match=Match(property="email_domain", using=Contains("example")))
clause = User.as_filtered_by(filter_, fallback=fallback)
```

Normal mapped resolution always runs first. The fallback is invoked independently
for every Match whose normal property resolution fails; results are not cached.
Fallbacks are consumer-controlled SQL construction and therefore part of the
trusted boundary.

Direct column-targeted `association_proxy` attributes are supported by built-ins:

```python
filter_ = Filter(match=Match(property="tag_names", using=Equals("python")))
```

Each positive proxy Match is its own existential test. Negating the Filter negates
the complete proxy expression, so a negated `Equals("python")` means that no
related value equals `"python"`. To express “some related value does not equal
`"python"`,” use an explicit `Related` Filter and negate the inner value Match.

## Predicates

The built-in surface is:

| Family | Predicates |
| --- | --- |
| Comparison | `Equals`, `OneOf` |
| Ordering | `LessThan`, `LessThanOrEqual`, `GreaterThan`, `GreaterThanOrEqual`, `Between` |
| Containment | `Contains`, `ContainsExact` |
| Presence | `Exists` |

Predicates delegate directly to SQLAlchemy's property operations. `Predicate[T]`
is the public one-method contract accepted by `Match`; `Operator[T, OT]` is its
operand-bearing specialization. `Predicate[T]` and `Property[T]` communicate
property-value compatibility statically instead of duplicating it as runtime
validation. Each concrete Operator declares its own operand shape: `Between[T]`
accepts `tuple[T, T]`, while `OneOf[T]` accepts `tuple[T, ...]`, and both operate on
`Property[T]`. Universally applicable predicates such as equality and presence use
`Any`; ordered comparisons remain generic, and containment is fixed to `str`.
`Between` is inclusive and expects its bounds in the desired order. `OneOf`
preserves tuple order and duplicates.
`Contains` is case-insensitive and `ContainsExact` uses SQLAlchemy's case-sensitive
containment operation; both enable `autoescape`, so caller-supplied `%` and `_` are
literal characters rather than wildcard syntax.

`Exists` means “at least one non-null value.” A Filter containing `Exists()` with
`negate=True` is its logical complement. For an ordinary scalar these behave like
`IS NOT NULL` and `IS NULL`. For an association-proxy collection, the negated
Filter matches empty and all-null collections, while `Exists` matches mixed and
all-non-null collections.

The former `NotEquals` and `NotExists` Predicates have been removed. Replace them
with Filters containing `Equals` or `Exists`, respectively, and set `negate=True`.

Custom Predicates implement one method and should themselves be immutable,
hashable, and deterministic. Subclass `Operator` when the Predicate stores an
operand:

```python
from dataclasses import dataclass
from sqlafilters import FilterClause, Operator, Predicate, Property


@dataclass(frozen=True, slots=True)
class StartsWith(Operator[str]):
    operand: str

    def apply(self, property: Property[str]) -> FilterClause:
        return property.startswith(self.operand, autoescape=True)


@dataclass(frozen=True, slots=True)
class IsPositive(Predicate[int]):
    def apply(self, property: Property[int]) -> FilterClause:
        return property > 0
```

## Errors and trust boundary

Filter values do not perform runtime construction validation. Consumers are
responsible for constructing exactly one variant with non-empty groups. Blank or
unknown property names and descriptor access fail with `FilterCompilationError`
during compilation. Predicates are applied directly, so their exceptions propagate
unchanged. Unknown and non-relationship direct relationship names raise
`BadRelationshipError`, a subtype of `FilterCompilationError`. Compilation is
depth-first and stops at the first failing leaf. A fallback exception or
fallback-property compilation error is chained from the original normal-resolution
error.

Normal names are used only for direct Python attribute lookup, and built-in
operands remain SQLAlchemy bound values. This is not an authorization layer:
applications accepting untrusted filter input must allowlist permitted properties
and relationships and must bound tree depth, width, match count, and relationship
depth before constructing values. Custom Predicates and fallbacks are trusted code
that can weaken the normal SQL-safety boundary.

Serialization, specialized universal relationship scopes, a standalone public
compiler, and cross-call compilation caches are intentionally outside the v0.1 API.
