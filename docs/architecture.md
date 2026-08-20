# sqlafilters architecture and design

## Status and authority

This document is the normative architecture and design for `sqlafilters` version 0.1. It refines the conceptual sketch in `PROMPT.md`; when the two disagree, this document takes precedence.

The domain language is defined in [`CONTEXT.md`](CONTEXT.md). Decisions whose rationale would otherwise be surprising are recorded in [`adr/`](adr/).

## Purpose

`sqlafilters` lets a SQLAlchemy mapped class compile an immutable Filter tree into one SQLAlchemy Boolean where-clause expression. Consumers construct Filter objects in Python and attach the resulting expression to a statement:

```python
filter_ = Filter(
    and_=(
        Filter(match=Match(property="score", using=Between((0, 5)))),
        Filter(match=Match(property="name", using=Contains("smith"))),
    )
)

statement = select(MyModel).where(MyModel.as_filtered_by(filter_))
```

The library builds SQLAlchemy expressions. It does not execute statements, own sessions, or inspect database query plans.

## Goals

- Provide a small, typed Python vocabulary for property and relationship-scoped filtering.
- Compile recursive Match, AND, OR, and Related trees, with negation at any node,
  into one SQLAlchemy where clause.
- Support mapped scalar attributes, column properties, hybrid properties, direct column-targeted association proxies, and other SQLAlchemy `SQLCoreOperations` expressions.
- Detect invalid properties and Related relationships during compilation.
- Let consumers explicitly support dynamic properties with a trusted, model-aware Match compiler that runs before ORM attribute access.
- Make Filter, Match, and built-in Predicate values immutable, hashable, and deterministic, and require the same behavior from custom Predicates.
- Remain dialect-neutral to the extent enabled by SQLAlchemy's expression APIs.
- Bias expression design toward common database performance practices without making execution-time guarantees.
- Allow consumers to add custom immutable Predicates.

## Non-goals

- Parsing, serialization, or validation of external payloads.
- Pydantic models or a stable JSON schema.
- Implicit or dotted relationship paths, implicit joins, or statement mutation.
- Automatically treating a Match as relationship traversal; relationship scope must be explicit through `via` or owned by a Proxied Attribute.
- Rewriting or optimizing the Filter tree.
- Query execution, session management, pagination, sorting, or projection.
- Specialized universal relationship quantifiers.
- A built-in where-clause cache.
- Built-in limits on tree depth, group width, or Match count.
- Database-specific query-plan or timing guarantees.

Consumers that accept untrusted input are responsible for authorization, complexity limits, and construction of the public value objects.

## Architectural boundary

```text
Consumer Python code
    │ constructs frozen values
    ▼
Filter / Match / Related / Predicate tree
    │ MyModel.as_filtered_by(filter_)
    ▼
Recursive compiler inside FilterableMixin
    ├── compiles Matches against the active model
    ├── gives a model-aware dynamic compiler first priority for Matches
    ├── compiles Related Filters through relationship.any() / .has()
    ├── combines child clauses with and_() / or_()
    └── negates each completed node whose negate flag is true
    ▼
SQLAlchemy Boolean where-clause expression
    │ consumer attaches it to select/update/delete
    ▼
SQLAlchemy rendering and database optimization
```

`FilterableMixin.as_filtered_by()` is the only public compilation entry point. Private functions may separate traversal, property resolution, and error translation so each behavior can be tested independently.

The compiler accepts a concrete mapped subclass of `DeclarativeBase` at that entry point and as every relationship target. Consumers own the declarative base, registry, and metadata; the compiler uses each model's `__mapper__` directly and creates no registry of its own. Imperative mapping and decorator-only declarative mapping are outside the supported contract, while `MappedAsDataclass` is optional and supported when combined with `DeclarativeBase`. Abstract and unmapped classes are programmer misuse with unspecified failure behavior, so this boundary is documented rather than runtime-validated. See [ADR 0005](adr/0005-require-concrete-declarative-base-models.md).

## Package structure

```text
src/sqlafilters/
├── __init__.py       # supported public re-exports
├── capabilities.py   # Operator Capabilities and SQLAlchemy type classification
├── exceptions.py     # InvalidFilterError, FilterCompilationError, BadRelationshipError
├── filters.py        # Filter, Match, and Related
├── mixins.py         # Dynamic, FilterableMixin, and private compilation helpers
├── operators.py      # Predicate, Operator, and built-in implementations
├── types.py          # shared SQLAlchemy typing aliases
└── py.typed
```

The package root re-exports the supported API, including the `Dynamic` and `Property` typing aliases, so normal consumer imports remain concise:

```python
from sqlafilters import (
    BadRelationshipError,
    Between,
    Capability,
    Contains,
    Dynamic,
    Filter,
    FilterClause,
    FilterableMixin,
    Match,
    Property,
    Related,
    filter_capabilities,
)
```

Pydantic is not part of the target dependency set. The runtime depends on SQLAlchemy 2.0 (`>=2,<2.1`), matching the project's declared dependency range.

## Domain model

### Filter

A Filter is a frozen, slotted, keyword-only dataclass with four optional variant
fields and one Boolean flag:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Filter:
    match: Match | None = None
    and_: tuple[Filter, ...] | None = None
    or_: tuple[Filter, ...] | None = None
    via: Related | None = None
    negate: bool = False
```

Exactly one variant field must be non-`None`.

- `match` is a leaf.
- `and_` is a non-empty tuple whose children must all match.
- `or_` is a non-empty tuple for which at least one child must match.
- `via` is a Related Filter evaluated against one direct mapped relationship.
- `negate` logically inverts the complete expression compiled for this Filter node.

AND and OR tuples preserve insertion order and duplicates. Equality and hashing are structural rather than logical: reordering children or changing `negate` produces a different Filter value even when the database predicate would be logically equivalent. The compiler does not flatten, sort, deduplicate, or otherwise normalize groups.

A singleton AND or OR group is valid and compiles to the same effective where clause as its only child. Empty groups are invalid.

### Related

Related is a frozen, slotted, keyword-only dataclass:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Related:
    relationship: str
    where: Filter
```

`relationship` must be a non-empty literal name of one direct SQLAlchemy relationship on the active model. Dots have no traversal semantics; callers express multiple hops by nesting Related Filters. `where` is compiled against the relationship's target model, then applied to the current model as one existential condition. The containing Filter may negate that completed relationship expression, while a negated `where` remains inside the existential scope.

For a collection relationship, Related uses `relationship.any(compiled_where)`. For a scalar relationship, it uses `relationship.has(compiled_where)`. SQLAlchemy owns secondary tables, custom join conditions, and correlation details. Empty collections and missing scalar relationships do not satisfy a positive Related Filter.

One Related Filter binds its entire `where` tree to the same related row:

```python
Filter(
    via=Related(
        relationship="children", where=Filter(and_=(score_filter, color_filter))
    )
)
```

By contrast, sibling Related Filters are independent existential scopes and may be satisfied by different rows. This explicit scoping decision is recorded in [ADR 0004](adr/0004-use-explicit-related-filter-scopes.md).

### Match

A Match is a frozen, slotted, keyword-only dataclass:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Match:
    property: str
    using: Predicate[Any]
```

`property` is expected to be a non-empty string. It names one direct class attribute on the mapped model. Blank and unknown names fail during compilation. Dots have no traversal semantics; a dotted string is looked up as one attribute name and will normally fail compilation.

Predicates are statically typed and expected to honor the immutable value contract. The library does not duplicate that contract with nominal runtime checks.

### Construction contract

Static typing and consumer construction are the validation boundary. Filter values do not validate, coerce, or normalize their fields at runtime. Consumers provide exactly one of the four Filter variants, a Boolean `negate` value, non-empty AND and OR tuples, and non-blank property and relationship names. Blank names fail naturally during compilation; other malformed structures are outside the supported contract.

## Predicate model

### Extension contract

`Predicate` is the public abstract generic contract accepted by Match:

```python
type Property[T] = SQLCoreOperations[T]


class Predicate[T](ABC):
    @abstractmethod
    def apply(self, property: Property[T]) -> FilterClause:
        """Return a SQLAlchemy Boolean expression."""


@dataclass(frozen=True, slots=True)
class Operator[T, OT = T](Predicate[T], ABC):
    operand: OT
```

The Predicate generic parameter represents the value exposed by the `Property[T]` accepted by `apply()`. `Operator[T, OT]` is the operand-bearing Predicate specialization; its second parameter describes the stored operand and defaults to the property value type. Most Operators use that default, while `Between[T]` uses `tuple[T, T]` and `OneOf[T]` uses `tuple[T, ...]`. Predicates valid for every SQLAlchemy value, such as equality and presence, specialize with `Any`; ordered comparisons retain a bounded type parameter, and containment specializes to `str`. An exhaustive universal union would incorrectly exclude consumer-defined SQLAlchemy types. Presence Predicates directly subclass Predicate because they are operandless.

Built-in Predicates are frozen, slotted dataclasses whose value fields may be passed positionally. This keeps Match construction concise:

```python
Equals(5)
Between((0, 5))
Contains("foo")
OneOf((1, 2, 3))
Exists()
```

Keyword arguments remain available when they improve clarity, but are never required for built-ins. A custom Predicate should be immutable, hashable, and deterministic; these are consumer responsibilities rather than runtime-validated requirements. Custom operand-bearing Predicates subclass Operator; operandless Predicates subclass Predicate directly.

### Built-in surface

| Predicate | Fields | Meaning |
|---|---|---|
| `Equals` | `operand` | property equals operand |
| `LessThan` | `operand` | property is less than operand |
| `LessThanOrEqual` | `operand` | property is at most operand |
| `GreaterThan` | `operand` | property is greater than operand |
| `GreaterThanOrEqual` | `operand` | property is at least operand |
| `Between` | `operand` tuple | property is inclusively between the supplied bounds |
| `Exists` | none | property has at least one non-null value |
| `Contains` | `operand` | case-insensitive literal substring containment |
| `ContainsExact` | `operand` | case-sensitive literal substring containment |
| `OneOf` | `operand` tuple | property equals one member |

### Operator Capabilities

`TEXT_SEARCH` and `ORDERING` are runtime Operator Capabilities used by the built-in
restricted Predicates. String types and their standard variants receive
`TEXT_SEARCH`. Integer types, including `SmallInteger` and `BigInteger`, plus numeric,
floating, date, time, and datetime types receive `ORDERING`. Boolean, binary, JSON,
UUID, plain SQLAlchemy `Enum`, and unknown types receive neither capability. Equality,
membership, and presence remain unrestricted.

These defaults are registered as the same private class metadata used by custom
types. Standard variants inherit the declaration from their SQLAlchemy type-family
base. `Enum` and `TypeDecorator` carry explicit empty declarations so they do not
inherit capabilities from a broader family, and runtime lookup is one metadata read
regardless of whether the type is built in or consumer defined.

Every `TypeDecorator` is opaque, including one whose `impl` or `python_type` resembles
a supported built-in. Its class must opt in explicitly:

```python
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator
from sqlafilters import Capability, filter_capabilities


@filter_capabilities(Capability.TEXT_SEARCH)
class SearchableCode(TypeDecorator[str]):
    impl = String
    cache_ok = True
```

`filter_capabilities` accepts one or more enum values and returns the same class.
Stacked declarations and declarations inherited from a decorated base class are
additive. The private class metadata is intentionally not a consumer API; there is no
global resolver registry or public lookup helper.

At runtime, capability lookup reads the expression's SQLAlchemy `type`, falling back
through `remote_attr` for a Proxied Attribute. Beartype functional validators enforce
`TEXT_SEARCH` on containment Predicates and `ORDERING` on ordered comparisons and
`Between`; applying a restricted Predicate to an unsupported property raises
`InvalidFilterError` before SQL construction. A declaration records supported SQL
semantics but neither introduces a cast nor guarantees database-specific behavior.
See [ADR 0007](adr/0007-declare-operator-capabilities-on-type-decorators.md).

### Null policy

Operand shapes are expressed through static annotations and are not revalidated during construction. Presence and its complement use one operandless Predicate plus Filter negation:

```python
Exists()  # property.is_not(None)
Filter(match=Match(property="value", using=Exists()), negate=True)
```

For an ordinary scalar property, negated `Exists` is equivalent to `property.is_(None)`. For a Proxied Attribute, `Exists` means at least one related target value is non-null, while the negated Filter means no related target value is non-null. The latter therefore matches an empty or missing relationship and an all-null collection, but not a collection containing any non-null value. These Filters express domain-level presence rather than a request for a particular SQL construct, although a Proxied Attribute may cause SQLAlchemy to render `EXISTS` or `NOT EXISTS`. The rationale is recorded in [ADR 0002](adr/0002-use-exists-for-null-presence.md).

### Proxied attributes

A Proxied Attribute is a direct, column-targeted SQLAlchemy `association_proxy`. It is resolved under its model attribute name; a dynamic compiler may apply a Match to the same proxy while compiling another literal name. `ColumnAssociationProxyInstance` and ordinary mapped expressions both satisfy `SQLCoreOperations`, so `Property` requires no runtime descriptor inspection.

Built-ins invoke comparison methods on the proxy itself. This lets SQLAlchemy correlate the related table and produce the appropriate existential expression. Chained and object-targeted association proxies remain SQLAlchemy- or custom-Predicate-defined behavior.

Each positive Match against a collection-valued Proxied Attribute is an independent existential test. Negating the containing Filter complements the complete proxy expression: negated `Equals(2)` means no related value equals `2`, rather than that some related value differs from `2`. The latter remains expressible with an explicit Related Filter containing a negated inner Match. Likewise, negated `Exists` is the logical complement of `Exists`, so a mixture of null and non-null values satisfies only the positive Filter.

### Between

`Between` has inclusive range semantics while retaining portable SQL:

`Between` preserves its two-item operand tuple and delegates directly to `property.between(lower, upper)`. Consumers provide bounds in the desired order. See [ADR 0003](adr/0003-normalize-between-bounds.md).

### Containment

Containment treats the operand as literal text, not as a caller-provided SQL pattern:

```python
Contains("a%b")  # case-insensitive literal substring
ContainsExact("a%b")  # case-sensitive literal substring
```

Compilation delegates wildcard escaping and dialect behavior to SQLAlchemy:

```python
property.icontains(operand, autoescape=True)  # Contains
property.contains(operand, autoescape=True)  # ContainsExact
```

SQLAlchemy may implement case-insensitive containment with native `ILIKE` or a dialect-appropriate equivalent.

### OneOf

`OneOf.operand` is a tuple whose order and duplicates are preserved in the value object. Compilation delegates directly to `property.in_(operand)` without normalization.

## Queryable property resolution

Compilation resolves every Match against an active mapped model. The active model is initially the class on which `as_filtered_by()` was called and changes to the target model while compiling `Related.where`.

Consumers may pass the keyword-only `dynamic` argument, whose public type is `Dynamic = Callable[[type[DeclarativeBase], Match], FilterClause | None]`. For every Match, the compiler invokes `dynamic` first with the active model and complete, unmodified Match. A returned clause takes immediate precedence, including over a readable mapped property. Returning `None` requests ordinary ORM attribute resolution:

1. Inspect the class as a SQLAlchemy mapped class.
2. Reject the name if SQLAlchemy identifies it as a relationship property.
3. Resolve the direct class attribute once with `getattr(cls, match.property)`.
4. Pass the resolved value to `match.using.apply()`.

Failure to resolve the attribute raises `FilterCompilationError`. SQLAlchemy mapper introspection is assumed to satisfy its documented contract. The resolved property is passed directly to `Predicate.apply()`, whose exceptions propagate unchanged.

Dynamic results are trusted Boolean clauses and are returned without further Predicate application or nominal runtime checks. Results are not cached or shared between Matches. If the dynamic function raises, compilation stops immediately with a `FilterCompilationError`; the original exception is retained as its cause, and ordinary ORM resolution is not attempted. Dynamic logic is expected by convention to compile a given Match deterministically, though the library cannot enforce that contract.

There is intentionally no allowlist of individual mapped fields or nominal descriptor classes. `Property` publicly names SQLAlchemy's common `SQLCoreOperations` behavior for static typing, but the resolver does not enforce a separate runtime class check. This admits mapped scalar attributes, `column_property` values, class-level hybrid expressions, direct column-targeted association proxies, and compatible extension descriptors. Dynamic functions may compile those same properties or broader Boolean expressions.

This boundary allows a Proxied Attribute, hybrid property, compatible extension descriptor, dynamic function, or custom Predicate to produce an `EXISTS` subquery or another Boolean expression. SQLAlchemy or consumer code owns those property-level semantics; the compiler neither parses an implicit relationship path nor adds a join.

## Related filter resolution

Compilation resolves `Filter.via` separately from Match property resolution:

1. Inspect the active model as a SQLAlchemy mapped class.
2. Resolve `Related.relationship` as one direct mapped relationship; `dynamic` is never consulted for the relationship boundary.
3. Obtain the relationship's target mapped model and compile `Related.where` against that model, using the same model-aware dynamic function.
4. Apply the compiled child expression through `.any()` when the relationship has `uselist=True`, or `.has()` when it has `uselist=False`.

An invalid relationship name or non-relationship attribute raises `BadRelationshipError`. Mapper target resolution and construction of the appropriate `.any()` or `.has()` expression rely directly on SQLAlchemy's documented relationship behavior. An error from within `Related.where` propagates unchanged and identifies its active target model; it is not wrapped with a relationship path.

Related first produces an existential relationship expression. A containing Filter with `negate=True` complements that complete expression, including matching empty collections or missing scalar relationships when the positive expression is false. Negating `Related.where` instead asks for an existing related row that fails the inner criterion. Neither form is presented as a specialized universal quantifier. Nested Related Filters provide explicit multiple-hop scopes, while SQLAlchemy's relationship comparator remains responsible for custom joins, many-to-many secondary tables, and correlation SQL. See [ADR 0004](adr/0004-use-explicit-related-filter-scopes.md).

## Recursive compilation

Conceptually, compilation performs the following sequence:

```python
def _compile_match(
    model: type[DeclarativeBase],
    match: Match,
    dynamic: Dynamic | None,
) -> FilterClause:
    if dynamic is not None:
        try:
            clause = dynamic(model, match)
        except Exception as error:
            raise FilterCompilationError(...) from error

        if clause is not None:
            return clause

    property_ = resolve_property(model, match.property)
    return match.using.apply(property_)


def _compile_related(
    model: type[DeclarativeBase],
    related: Related,
    dynamic: Dynamic | None,
) -> FilterClause:
    relationship = resolve_relationship(model, related.relationship)
    target_model = relationship.mapper.class_
    child_clause = _compile_filter(target_model, related.where, dynamic)

    if relationship.uselist:
        return getattr(model, related.relationship).any(child_clause)
    return getattr(model, related.relationship).has(child_clause)


def _compile_filter(
    model: type[DeclarativeBase],
    filter_: Filter,
    dynamic: Dynamic | None,
) -> FilterClause:
    if filter_.match is not None:
        clause = _compile_match(model, filter_.match, dynamic)
    elif filter_.and_ is not None:
        clause = and_(
            *(_compile_filter(model, child, dynamic) for child in filter_.and_)
        )
    elif filter_.or_ is not None:
        clause = or_(*(_compile_filter(model, child, dynamic) for child in filter_.or_))
    else:
        clause = _compile_related(model, filter_.via, dynamic)

    return not_(clause) if filter_.negate else clause
```

The actual compiler is private. It assumes the construction contract and does not normalize malformed trees or invent identities for empty groups.

Traversal is depth-first and stops at the first failing leaf. The compiler does not collect errors from the remaining tree.

## Mixin design

`FilterableMixin` contributes behavior only:

```python
class FilterableMixin:
    @classmethod
    def as_filtered_by(
        cls,
        filter_: Filter,
        *,
        dynamic: Dynamic | None = None,
    ) -> FilterClause: ...
```

It does not inherit `MappedAsDataclass` and defines no mapped fields. Consumers combine it with a concrete mapped subclass of their own `DeclarativeBase`; that base may also inherit `MappedAsDataclass`:

```python
class Base(DeclarativeBase, MappedAsDataclass):
    pass


class MyModel(FilterableMixin, Base):
    __tablename__ = "my_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    score: Mapped[int]
    name: Mapped[str]
```

Imperative mappings and decorator-only declarative mappings are not supported integration paths.

## Error model

```python
class InvalidFilterError(Exception):
    """Base error for a Filter that cannot be compiled."""


class FilterCompilationError(InvalidFilterError):
    """A valid Filter cannot compile for the selected mapped class."""


class BadRelationshipError(FilterCompilationError):
    """A Related Filter cannot compile for its selected relationship."""
```

No other public exception subclasses are defined.

Property-resolution errors identify the active model and literal property name. Predicate applications are direct calls, and their exceptions propagate unchanged.

Without a dynamic function, a recursive call lets the first property-resolution `FilterCompilationError` propagate unchanged. With one, every Match invokes it before property resolution. Returning `None` continues with normal resolution; a returned clause is used directly. An exception from the dynamic function stops immediately and is wrapped in `FilterCompilationError` with the original exception as its cause.

`BadRelationshipError` identifies the active model and literal relationship name for invalid Related relationship resolution. Property and Predicate failures inside `Related.where` retain their original subtype and identify the active target model; the compiler does not add relationship-path wrappers.

The compiler reports the failing leaf or relationship boundary; it does not snapshot or report the state of the entire Filter tree.

## Performance design

Performance is a design bias, not a deterministic guarantee.

- Predicates construct SQLAlchemy expressions directly and keep operands parameterized.
- The compiler does not add casts, functions, or joins. It produces correlated relationship subqueries only for explicit Related Filters or when the selected Proxied Attribute or Predicate delegates that behavior to SQLAlchemy.
- Library-provided Predicates are deterministic, so structurally equal built-in Filter trees produce the same SQLAlchemy expression structure. Custom Predicates must provide the same property by contract.
- The compiler does not cache where-clause objects. SQLAlchemy owns its own statement compilation caching, and retaining expressions in a library cache could retain model metadata and operand values.
- The compiler maintains no property, subtree, clause, or cross-call cache. SQLAlchemy remains responsible for its own statement compilation caching.
- The compiler does not reorder, flatten, deduplicate, or algebraically rewrite Filter groups or Predicate values.
- The database remains responsible for choosing indexes, join strategies, and execution plans.

Some requested semantics inherently affect index use. For example, case-insensitive containment may render a case-folding expression on dialects without native `ILIKE`, and substring searches commonly need specialized indexes for large datasets. The library preserves the requested semantics and leaves database-specific physical design to consumers.

Related Filters and Proxied Attributes commonly render correlated `EXISTS` expressions. Nested Related Filters render nested scopes. SQLAlchemy owns their join and correlation SQL, while the database remains responsible for choosing an execution plan; the library makes no guarantee that correlated predicates outperform an explicit join for a given workload.

## Security and operational boundaries

- During normal resolution, property and relationship names are used only for direct Python attribute lookup and are never interpolated into SQL text by the library.
- Built-ins use SQLAlchemy expression methods so operands remain bound values.
- A dynamic function is trusted library-consumer code. It receives the active model and complete Match and may construct arbitrary SQLAlchemy Boolean expressions; it can weaken the guarantees provided by normal property resolution.
- A custom Predicate is trusted library-consumer code and can weaken these guarantees if it emits raw SQL.
- The library does not authorize which mapped properties or relationships a caller may filter. Consumers exposing Filters to less-trusted callers must enforce their own property and relationship policy.
- The library imposes no recursion, relationship-depth, width, Match-count, or subquery-count limits. Consumers translating untrusted data must enforce limits before constructing a Filter.
- Filter hashability does not imply that Filter contents are safe cache keys across processes or deployments; no serialized or stable cross-version hash contract exists.

## Testing strategy

Tests are behavior-focused and execute against an in-memory SQLite database. They do not assert rendered SQL strings, private SQLAlchemy expression classes, cache keys, query plans, or timing thresholds.

### Value-object behavior

- constructors preserve supplied values without validation or normalization;
- singleton groups preserve the child's query behavior;
- equivalent trees built from library-provided Predicates compare and hash equally;
- reordered groups and duplicate-preserving groups retain structural value semantics.

### Predicate behavior

- every built-in returns the expected rows at boundary and representative values;
- `Exists` and a negated Filter implement complementary presence and absence behavior;
- `Between` passes its supplied bounds to SQLAlchemy in order;
- containment is case-sensitive or insensitive as specified and treats `%` and `_` literally;
- `OneOf` behaves correctly with duplicates.

### Compilation behavior

- deeply nested AND/OR trees return the expected rows;
- mapped scalar attributes, column properties, and hybrid properties work;
- a dynamic function is called before normal ORM property access and may override an existing property;
- a dynamic function receives the active model and complete Match and may return any usable Boolean clause, including one built from a custom property or relationship scope;
- a `None` dynamic result continues with normal property resolution;
- dynamic exceptions stop immediately as `FilterCompilationError`, retaining the original exception as their cause, while Predicate exceptions propagate unchanged;
- repeated Matches invoke the dynamic function independently;
- collection Related Filters use existential semantics and scalar Related Filters use scalar-reference semantics;
- negating a completed Related Filter differs from negating its inner `where`, including for empty collections and missing scalar relationships;
- one Related Filter binds an AND subtree to the same related row, while sibling Related Filters may match different rows;
- nested Related Filters support multiple explicit relationship hops;
- unknown and non-relationship `Related.relationship` names raise `BadRelationshipError`;
- errors inside `Related.where` retain their original subtype and identify the active target model;
- dynamic works inside `Related.where` and receives that target model;
- direct column-targeted Proxied Attributes work with built-in operations supported by SQLAlchemy;
- separate collection-valued Proxied Attribute Matches remain independent existential tests;
- on Proxied Attributes, `Exists` is true for at least one non-null value and negating its Filter is the complement, including for empty, all-null, and mixed collections;
- custom operand-bearing and operandless Predicates can compile and execute successfully;
- an exception from a descriptor or custom Predicate is wrapped and chained;
- traversal stops at the first failing leaf.

SQLite is the executable behavioral reference for version 0.1. Dialect neutrality comes from using SQLAlchemy's public, dialect-agnostic expression APIs rather than from assertions about raw compiled SQL.

## Implementation sequence

1. Add the three public exceptions.
2. Implement frozen `Match`, `Related`, and `Filter` values without runtime construction validation.
3. Add the public `Property` typing alias, one-method `Predicate` contract, and operand-bearing `Operator` specialization.
4. Implement and behavior-test direct comparison Operators and the presence Predicate.
5. Implement direct `Between`, containment, and `OneOf` delegation.
6. Implement private property and direct relationship resolution, including `BadRelationshipError` translation.
7. Implement recursive Match, AND, OR, and Related compilation, including node-level negation, through `_compile_filter()`.
8. Add the behavior-only `FilterableMixin` public entry point with its model-aware dynamic Match compiler.
9. Re-export the supported API, including `Dynamic`, `Predicate`, `Operator`, `Property`, `FilterClause`, `Related`, and `BadRelationshipError`, from `sqlafilters.__init__`.
10. Remove the placeholder function and Pydantic dependency.
11. Complete SQLite-backed behavioral coverage for nested trees, Related Filters, Proxied Attributes, custom Predicates, and failures.
12. Update user-facing examples and API documentation to match the implemented contract.

## Decisions and future evolution

The initial design deliberately keeps several extensions possible without promising them:

- A standalone public compiler can be added if the mixin entry point proves constraining.
- Negative or universal Related quantifiers can be proposed with an explicit semantic model; positive `via` is not overloaded to provide them.
- Additional built-ins can be added when their escaping, type, and portability contracts are settled.
- A bounded compilation cache can be considered only after profiling demonstrates meaningful construction cost.
- Serialization can be supplied by consumers or reconsidered as a separate adapter layer without changing the core value vocabulary by accident.

Any such change must preserve the distinction between structural Filter values, SQLAlchemy expression construction, and database execution planning.
