# sqlafilters architecture and design

## Status and authority

This document is the normative architecture and design for `sqlafilters` version 0.1. It refines the conceptual sketch in `PROMPT.md`; when the two disagree, this document takes precedence.

The domain language is defined in [`CONTEXT.md`](CONTEXT.md). Decisions whose rationale would otherwise be surprising are recorded in [`adr/`](adr/).

## Purpose

`sqlafilters` lets a SQLAlchemy mapped class compile an immutable Filter tree into one SQLAlchemy Boolean where-clause expression. Consumers construct Filter objects in Python and attach the resulting expression to a statement:

```python
filter_ = Filter(
    and_=(
        Filter(match=Match(property="score", operator=Between((0, 5)))),
        Filter(match=Match(property="name", operator=Contains("smith"))),
    )
)

statement = select(MyModel).where(MyModel.as_filtered_by(filter_))
```

The library builds SQLAlchemy expressions. It does not execute statements, own sessions, or inspect database query plans.

## Goals

- Provide a small, typed Python vocabulary for property and relationship-scoped filtering.
- Compile recursive Match, AND, OR, and Related trees into one SQLAlchemy where clause.
- Support mapped scalar attributes, column properties, hybrid properties, direct column-targeted association proxies, and other SQLAlchemy `SQLCoreOperations` expressions.
- Detect structurally invalid Filters during construction.
- Detect invalid properties and Related relationships during compilation.
- Let consumers lazily recover from any property compilation failure by supplying a trusted fallback property resolver.
- Make Filter, Match, and built-in Operator values immutable, hashable, and deterministic, and require the same behavior from custom Operators.
- Remain dialect-neutral to the extent enabled by SQLAlchemy's expression APIs.
- Bias expression design toward common database performance practices without making execution-time guarantees.
- Allow consumers to add custom immutable Operators.

## Non-goals

- Parsing, serialization, or validation of external payloads.
- Pydantic models or a stable JSON schema.
- Implicit or dotted relationship paths, implicit joins, or statement mutation.
- Automatically treating a Match as relationship traversal; relationship scope must be explicit through `via` or owned by a Proxied Attribute.
- Rewriting or optimizing the Filter tree.
- Query execution, session management, pagination, sorting, or projection.
- A general NOT node.
- A built-in where-clause cache.
- Built-in limits on tree depth, group width, or Match count.
- Database-specific query-plan or timing guarantees.

Consumers that accept untrusted input are responsible for authorization, complexity limits, and construction of the public value objects.

## Architectural boundary

```text
Consumer Python code
    │ constructs frozen values
    ▼
Filter / Match / Related / Operator tree
    │ MyModel.as_filtered_by(filter_)
    ▼
Recursive compiler inside FilterableMixin
    ├── compiles Matches against the active model
    ├── lazily tries a model-aware fallback after a property failure
    ├── compiles Related Filters through relationship.any() / .has()
    └── combines child clauses with and_() / or_()
    ▼
SQLAlchemy Boolean where-clause expression
    │ consumer attaches it to select/update/delete
    ▼
SQLAlchemy rendering and database optimization
```

`FilterableMixin.as_filtered_by()` is the only public compilation entry point. Private functions may separate traversal, property resolution, and error translation so each behavior can be tested independently.

## Package structure

```text
src/sqlafilters/
├── __init__.py       # supported public re-exports
├── exceptions.py     # InvalidFilterError, FilterCompilationError, BadRelationshipError
├── filters.py        # Filter, Match, and Related
├── mixins.py         # FilterableMixin and private compilation helpers
├── operators.py      # Operator and built-in implementations
├── types.py          # shared SQLAlchemy typing aliases
└── py.typed
```

The package root re-exports the supported API, including the `Property` typing alias, so normal consumer imports remain concise and fallback functions can use public annotations:

```python
from sqlafilters import (
    BadRelationshipError,
    Between,
    Contains,
    Filter,
    FilterableMixin,
    Match,
    Property,
    Related,
)
```

Pydantic is not part of the target dependency set. The runtime depends on SQLAlchemy 2.0 (`>=2,<2.1`), matching the project's declared dependency range.

## Domain model

### Filter

A Filter is a frozen, slotted, keyword-only dataclass with four optional fields:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Filter:
    match: Match | None = None
    and_: tuple[Filter, ...] | None = None
    or_: tuple[Filter, ...] | None = None
    via: Related | None = None
```

Exactly one field must be non-`None`.

- `match` is a leaf.
- `and_` is a non-empty tuple whose children must all match.
- `or_` is a non-empty tuple for which at least one child must match.
- `via` is a Related Filter evaluated against one direct mapped relationship.

AND and OR tuples preserve insertion order and duplicates. Equality and hashing are structural rather than logical: reordering children produces a different Filter value even when the database predicate would be logically equivalent. The compiler does not flatten, sort, deduplicate, or otherwise normalize groups.

A singleton AND or OR group is valid and compiles to the same effective where clause as its only child. Empty groups are invalid.

### Related

Related is a frozen, slotted, keyword-only dataclass:

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class Related:
    relationship: str
    where: Filter
```

`relationship` must be a non-empty literal name of one direct SQLAlchemy relationship on the active model. Dots have no traversal semantics; callers express multiple hops by nesting Related Filters. `where` is compiled against the relationship's target model, then applied to the current model as one positive existential condition.

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
    operator: Operator[Any]
```

`property` must be a non-empty string. It names one direct class attribute on the mapped model. Dots have no traversal semantics; a dotted string is looked up as one attribute name and will normally fail compilation.

Operators are statically typed and expected to honor the immutable value contract. The library does not duplicate that contract with nominal runtime checks.

### Construction invariants

Semantic failures that static types cannot express raise `InvalidFilterError` as soon as the relevant value is constructed. These include:

- a Filter with zero or multiple populated variants;
- an empty AND or OR tuple;
- a blank property name;
- a blank Related relationship name.

Static typing is the primary validation boundary for nominal types, tuple members, Operator operands, and custom extensions. The dataclasses do not coerce or revalidate correctly typed inputs.

## Operator model

### Extension contract

`Operator` is a public abstract generic base with one required operation:

```python
type Property[T] = SQLCoreOperations[T]


@dataclass(frozen=True, slots=True)
class Operator[T](ABC):
    @abstractmethod
    def apply(self, property: Property[T]) -> ColumnExpressionArgument[bool]:
        """Return a SQLAlchemy Boolean expression."""
```

The generic parameter represents the value exposed by the `Property[T]` accepted by `apply()`. Each concrete Operator declares its own operand shape and delegates directly to the corresponding `SQLCoreOperations` method. Most operands have the same type as the property value, while `Between[T]` accepts `tuple[T, T]` and `OneOf[T]` accepts `tuple[T, ...]`. Operators valid for every SQLAlchemy value, such as equality and presence, specialize with `Any`; ordered comparisons retain a bounded type parameter, and containment specializes to `str`. An exhaustive universal union would incorrectly exclude consumer-defined SQLAlchemy types. Presence Operators are naturally nullary because the base class does not prescribe an operand field.

Built-in Operators are frozen, slotted dataclasses whose value fields may be passed positionally. This keeps Match construction concise:

```python
Equals(5)
Between((0, 5))
Contains("foo")
OneOf((1, 2, 3))
Exists()
```

Keyword arguments remain available when they improve clarity, but are never required for built-ins. A custom Operator should be immutable, hashable, and deterministic; these are consumer responsibilities rather than runtime-validated requirements.

### Built-in surface

| Operator | Fields | Meaning |
|---|---|---|
| `Equals` | `operand` | property equals operand |
| `NotEquals` | `operand` | property does not equal operand |
| `LessThan` | `operand` | property is less than operand |
| `LessThanOrEqual` | `operand` | property is at most operand |
| `GreaterThan` | `operand` | property is greater than operand |
| `GreaterThanOrEqual` | `operand` | property is at least operand |
| `Between` | `operand` tuple | property is inclusively between the supplied bounds |
| `Exists` | none | property has at least one non-null value |
| `NotExists` | none | property has no non-null value |
| `Contains` | `operand` | case-insensitive literal substring containment |
| `ContainsExact` | `operand` | case-sensitive literal substring containment |
| `OneOf` | `operand` tuple | property equals one member |

### Null policy

Operand shapes are expressed through static annotations and are not revalidated during construction. Consumers use the dedicated presence Operators for null semantics:

Presence is expressed only through complementary nullary Operators:

```python
Exists()  # property.is_not(None)
NotExists()  # ~property.is_not(None)
```

For an ordinary scalar property, `NotExists` is equivalent to `property.is_(None)`. For a Proxied Attribute, `Exists` means at least one related target value is non-null, while `NotExists` means no related target value is non-null. The latter therefore matches an empty or missing relationship and an all-null collection, but not a collection containing any non-null value. These Operators express domain-level presence rather than a request for a particular SQL construct, although a Proxied Attribute may cause SQLAlchemy to render `EXISTS` or `NOT EXISTS`. The rationale is recorded in [ADR 0002](adr/0002-use-exists-for-null-presence.md).

### Proxied attributes

A Proxied Attribute is a direct, column-targeted SQLAlchemy `association_proxy`. It may be resolved under its model attribute name or returned under another literal name by fallback. `ColumnAssociationProxyInstance` and ordinary mapped expressions both satisfy `SQLCoreOperations`, so `Property` requires no runtime descriptor inspection.

Built-ins invoke comparison methods on the proxy itself. This lets SQLAlchemy correlate the related table and produce the appropriate existential expression. Chained and object-targeted association proxies remain SQLAlchemy- or custom-Operator-defined behavior.

Each Match against a collection-valued Proxied Attribute is an independent existential test. For example, a parent with related values `2` and `3` satisfies both `Equals(2)` and `NotEquals(2)`. `NotExists` is the deliberate exception to ordinary proxy operation forwarding: it remains the logical complement of `Exists`, so a mixture of null and non-null values satisfies only `Exists`.

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

Compilation first attempts a Match against the active mapped model. The active model is initially the class on which `as_filtered_by()` was called and changes to the target model while compiling `Related.where`:

1. Inspect the class as a SQLAlchemy mapped class.
2. Reject the name if SQLAlchemy identifies it as a relationship property.
3. Resolve the direct class attribute once with `getattr(cls, match.property)`.
4. Pass the resolved value to `match.operator.apply()`.

Failure to inspect the model, resolve the attribute, or use the attribute with the selected Operator raises `FilterCompilationError`. If `as_filtered_by()` has no fallback, that error propagates immediately.

Consumers may instead pass a keyword-only `fallback` with type `Callable[[type[DeclarativeBase], str], Property[Any] | None] | None`. The fallback is a recovery path for every `FilterCompilationError` from the normal property attempt, not only for an unknown name. It therefore may recover from a missing attribute, a Match that names a relationship, a descriptor failure, or an Operator expression failure. The model property always receives the first attempt; a fallback cannot eagerly override one that compiles successfully.

The fallback receives the active model and the exact, unmodified `Match.property` string. The core compiler continues to assign no traversal semantics to dots, but trusted fallback logic may interpret the string, return aliases, calculated expressions, or direct column-targeted association proxies, and construct other custom SQLAlchemy properties. The consumer owns all such semantics.

A successful non-`None` fallback result is memoized by `(active_model, literal_property_name)` for the duration of one top-level `as_filtered_by()` call. Every Match still tries normal property compilation first. Only after that attempt fails does compilation consult the per-call fallback cache or invoke the fallback. The cache is discarded when the call returns or raises; it is never shared across Filter values or calls. Returning `None` re-raises the original `FilterCompilationError`, so a `None` result ends compilation immediately and need not be cached.

Fallback results are trusted. The compiler performs no nominal runtime class check before passing a non-`None` result to the same Operator. `Operator.apply()` remains the authority on whether the result is usable. If it raises `FilterCompilationError`, the new error propagates with the original normal-attempt error as its cause. If the fallback itself raises, its exception propagates with the original `FilterCompilationError` as its cause. Fallback logic is expected by convention to resolve a given property name deterministically, though the library cannot enforce that contract.

There is intentionally no allowlist of individual mapped fields or nominal descriptor classes. `Property` publicly names SQLAlchemy's common `SQLCoreOperations` behavior for static typing, but the resolver does not enforce a separate runtime class check. This admits mapped scalar attributes, `column_property` values, class-level hybrid expressions, direct column-targeted association proxies, compatible extension descriptors, and trusted fallback-generated properties.

This boundary allows a Proxied Attribute, hybrid property, compatible extension descriptor, fallback, or custom Operator to produce an `EXISTS` subquery or another Boolean expression. SQLAlchemy or consumer code owns those property-level semantics; the compiler neither parses an implicit relationship path nor adds a join.

## Related filter resolution

Compilation resolves `Filter.via` separately from Match property resolution:

1. Inspect the active model as a SQLAlchemy mapped class.
2. Resolve `Related.relationship` as one direct mapped relationship; fallback is never consulted for it.
3. Obtain the relationship's target mapped model and compile `Related.where` against that model, using the same model-aware fallback and per-call cache.
4. Apply the compiled child expression through `.any()` when the relationship has `uselist=True`, or `.has()` when it has `uselist=False`.

An invalid relationship name, a non-relationship attribute, failure to inspect the model for Related resolution, or failure to construct the required `.any()` or `.has()` expression raises `BadRelationshipError`. An error from within `Related.where` propagates unchanged and identifies its active target model; it is not wrapped with a relationship path.

Related is positive and existential only. It does not express universal matching, relationship absence, or negation. Nested Related Filters provide explicit multiple-hop scopes, while SQLAlchemy's relationship comparator remains responsible for custom joins, many-to-many secondary tables, and correlation SQL. See [ADR 0004](adr/0004-use-explicit-related-filter-scopes.md).

## Recursive compilation

Conceptually, compilation performs the following sequence. Before recursion starts, `_memoized_fallback()` wraps a supplied fallback with a per-call cache of successful non-`None` results keyed by `(model, property_name)`; it does not invoke the fallback eagerly.

```python
def _compile_match(
    model: type[DeclarativeBase],
    match: Match,
    fallback: Callable[[type[DeclarativeBase], str], Property[Any] | None] | None,
) -> ColumnExpressionArgument[bool]:
    try:
        property_ = resolve_property(model, match.property)
        return match.operator.apply(property_)
    except FilterCompilationError as original:
        if fallback is None:
            raise

        try:
            property_ = fallback(model, match.property)
        except Exception as invalid:
            raise invalid from original

        if property_ is None:
            raise original

        try:
            return match.operator.apply(property_)
        except FilterCompilationError as invalid:
            raise invalid from original


def _compile_related(
    model: type[DeclarativeBase],
    related: Related,
    fallback: Callable[[type[DeclarativeBase], str], Property[Any] | None] | None,
) -> ColumnExpressionArgument[bool]:
    relationship = resolve_relationship(model, related.relationship)
    target_model = relationship.mapper.class_
    child_clause = _compile_filter(target_model, related.where, fallback)

    try:
        if relationship.uselist:
            return getattr(model, related.relationship).any(child_clause)
        return getattr(model, related.relationship).has(child_clause)
    except Exception as original:
        raise BadRelationshipError(...) from original


def _compile_filter(
    model: type[DeclarativeBase],
    filter_: Filter,
    fallback: Callable[[type[DeclarativeBase], str], Property[Any] | None] | None,
) -> ColumnExpressionArgument[bool]:
    if filter_.match is not None:
        return _compile_match(model, filter_.match, fallback)

    if filter_.and_ is not None:
        return and_(
            *(_compile_filter(model, child, fallback) for child in filter_.and_)
        )

    if filter_.or_ is not None:
        return or_(*(_compile_filter(model, child, fallback) for child in filter_.or_))

    return _compile_related(model, filter_.via, fallback)
```

The actual compiler is private. Construction invariants make an undefined branch impossible, so compilation does not invent identities for empty groups.

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
        fallback: (
            Callable[[type[DeclarativeBase], str], Property[Any] | None] | None
        ) = None,
    ) -> ColumnExpressionArgument[bool]: ...
```

It does not inherit `MappedAsDataclass` and defines no mapped fields. Consumers can combine it with `DeclarativeBase`, `MappedAsDataclass`, or their own declarative hierarchy:

```python
class Base(DeclarativeBase, MappedAsDataclass):
    pass


class MyModel(FilterableMixin, Base):
    __tablename__ = "my_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    score: Mapped[int]
    name: Mapped[str]
```

If SQLAlchemy later proves to require additional declarative integration for a supported hierarchy, that requirement can be added without changing the Filter or Operator model. It is not part of the initial design.

## Error model

```python
class InvalidFilterError(Exception):
    """Base error for invalid Filter construction or compilation."""


class FilterCompilationError(InvalidFilterError):
    """A valid Filter cannot compile for the selected mapped class."""


class BadRelationshipError(FilterCompilationError):
    """A Related Filter cannot compile for its selected relationship."""
```

No other public exception subclasses are defined.

Compilation errors should identify the failing property and Operator. Normal property resolution and Operator application translate their own failures into `FilterCompilationError`.

Without a fallback, a recursive call lets the first `FilterCompilationError` propagate unchanged. With a fallback, returning `None` re-raises that original error. An exception raised by the fallback propagates from the original error. If applying the Operator to a non-`None` fallback property raises a new `FilterCompilationError`, that new error propagates from the original error. Recovery is attempted once; the compiler never invokes the fallback recursively for a failing fallback property.

`BadRelationshipError` identifies the active model and literal relationship name. It covers invalid Related relationship resolution and failure to create the appropriate relationship expression. Property and Operator failures inside `Related.where` retain their original subtype and identify the active target model; the compiler does not add relationship-path wrappers.

The compiler reports the failing leaf or relationship boundary; it does not snapshot or report the state of the entire Filter tree.

## Performance design

Performance is a design bias, not a deterministic guarantee.

- Operators construct SQLAlchemy expressions directly and keep operands parameterized.
- The compiler does not add casts, functions, or joins. It produces correlated relationship subqueries only for explicit Related Filters or when the selected Proxied Attribute or Operator delegates that behavior to SQLAlchemy.
- Library-provided Operators are deterministic, so structurally equal built-in Filter trees produce the same SQLAlchemy expression structure. Custom Operators must provide the same property by contract.
- The compiler does not cache where-clause objects. SQLAlchemy owns its own statement compilation caching, and retaining expressions in a library cache could retain model metadata and operand values.
- Within one `as_filtered_by()` call, the compiler memoizes successful fallback results by `(active_model, literal_property_name)`. This transient resolution cache avoids repeating consumer logic but never bypasses the normal property attempt and never outlives the call.
- The compiler does not reorder, flatten, deduplicate, or algebraically rewrite Filter groups or Operator operands.
- The database remains responsible for choosing indexes, join strategies, and execution plans.

Some requested semantics inherently affect index use. For example, case-insensitive containment may render a case-folding expression on dialects without native `ILIKE`, and substring searches commonly need specialized indexes for large datasets. The library preserves the requested semantics and leaves database-specific physical design to consumers.

Related Filters and Proxied Attributes commonly render correlated `EXISTS` expressions. Nested Related Filters render nested scopes. SQLAlchemy owns their join and correlation SQL, while the database remains responsible for choosing an execution plan; the library makes no guarantee that correlated predicates outperform an explicit join for a given workload.

## Security and operational boundaries

- During normal resolution, property and relationship names are used only for direct Python attribute lookup and are never interpolated into SQL text by the library.
- Built-ins use SQLAlchemy expression methods so operands remain bound values.
- A fallback is trusted library-consumer code. It receives the active model and literal property name and may interpret the name or construct arbitrary SQLAlchemy expressions; it can weaken the guarantees provided by normal property resolution.
- A custom Operator is trusted library-consumer code and can weaken these guarantees if it emits raw SQL.
- The library does not authorize which mapped properties or relationships a caller may filter. Consumers exposing Filters to less-trusted callers must enforce their own property and relationship policy.
- The library imposes no recursion, relationship-depth, width, Match-count, or subquery-count limits. Consumers translating untrusted data must enforce limits before constructing a Filter.
- Filter hashability does not imply that Filter contents are safe cache keys across processes or deployments; no serialized or stable cross-version hash contract exists.

## Testing strategy

Tests are behavior-focused and execute against an in-memory SQLite database. They do not assert rendered SQL strings, private SQLAlchemy expression classes, cache keys, query plans, or timing thresholds.

### Value-object behavior

- construction accepts each valid Filter variant;
- undefined and multiply defined Filters raise `InvalidFilterError`;
- Related values require a non-blank relationship name;
- groups reject empty tuples;
- singleton groups preserve the child's query behavior;
- equivalent trees built from library-provided Operators compare and hash equally;
- reordered groups and duplicate-preserving groups retain structural value semantics.

### Operator behavior

- every built-in returns the expected rows at boundary and representative values;
- `Exists` and `NotExists` implement complementary presence and absence behavior;
- `Between` passes its supplied bounds to SQLAlchemy in order;
- containment is case-sensitive or insensitive as specified and treats `%` and `_` literally;
- `OneOf` behaves correctly with duplicates.

### Compilation behavior

- deeply nested AND/OR trees return the expected rows;
- mapped scalar attributes, column properties, and hybrid properties work;
- without a fallback, unknown attributes, relationships, and every other normal property failure propagate as `FilterCompilationError` immediately;
- a fallback is invoked lazily after missing, relational, descriptor, and Operator expression failures;
- a fallback receives the active model and literal property string and may return a usable custom property;
- a `None` fallback result re-raises the original `FilterCompilationError`;
- fallback exceptions and invalid fallback properties propagate from the original normal-attempt error;
- successful fallback results are memoized by `(active_model, property_name)` within one call but do not eagerly override normal properties;
- fallback caches are isolated across `as_filtered_by()` calls;
- collection Related Filters use positive existential semantics and scalar Related Filters use positive scalar-reference semantics;
- empty collections and missing scalar relationships do not satisfy a positive Related Filter;
- one Related Filter binds an AND subtree to the same related row, while sibling Related Filters may match different rows;
- nested Related Filters support multiple explicit relationship hops;
- unknown and non-relationship `Related.relationship` names raise `BadRelationshipError`;
- errors inside `Related.where` retain their original subtype and identify the active target model;
- fallback works inside `Related.where` and receives that target model;
- direct column-targeted Proxied Attributes work with built-in operations supported by SQLAlchemy;
- separate collection-valued Proxied Attribute Matches remain independent existential tests;
- on Proxied Attributes, `Exists` is true for at least one non-null value and `NotExists` is its complement, including for empty, all-null, and mixed collections;
- a custom Operator can compile and execute successfully;
- an exception from a descriptor or custom Operator is wrapped and chained;
- traversal stops at the first failing leaf.

SQLite is the executable behavioral reference for version 0.1. Dialect neutrality comes from using SQLAlchemy's public, dialect-agnostic expression APIs rather than from assertions about raw compiled SQL.

## Implementation sequence

1. Add the three public exceptions.
2. Implement frozen `Match`, `Related`, and `Filter` values with semantic construction invariants.
3. Add the `Property` typing alias and one-method `Operator` base.
4. Implement and behavior-test direct comparison and complementary presence Operators.
5. Implement direct `Between`, containment, and `OneOf` delegation.
6. Implement private property and direct relationship resolution, including `BadRelationshipError` translation.
7. Implement recursive Match, AND, OR, and Related compilation through `_compile_filter()`.
8. Add the behavior-only `FilterableMixin` public entry point with its model-aware, per-call-memoized fallback recovery path.
9. Re-export the supported API, including `Property`, `Related`, and `BadRelationshipError`, from `sqlafilters.__init__`.
10. Remove the placeholder function and Pydantic dependency.
11. Complete SQLite-backed behavioral coverage for nested trees, Related Filters, Proxied Attributes, custom Operators, and failures.
12. Update user-facing examples and API documentation to match the implemented contract.

## Decisions and future evolution

The initial design deliberately keeps several extensions possible without promising them:

- A standalone public compiler can be added if the mixin entry point proves constraining.
- A general NOT node can be added as another mutually exclusive Filter variant.
- Negative or universal Related quantifiers can be proposed with an explicit semantic model; positive `via` is not overloaded to provide them.
- Additional built-ins can be added when their escaping, type, and portability contracts are settled.
- A bounded compilation cache can be considered only after profiling demonstrates meaningful construction cost.
- Serialization can be supplied by consumers or reconsidered as a separate adapter layer without changing the core value vocabulary by accident.

Any such change must preserve the distinction between structural Filter values, SQLAlchemy expression construction, and database execution planning.
