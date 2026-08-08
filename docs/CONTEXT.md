# SQLAlchemy Filtering

This context describes immutable filters that select rows from a SQLAlchemy model.

## Language

**Filter**:
An immutable, recursive selection criterion containing exactly one of a Match, an AND group, an OR group, or a Related Filter.
_Avoid_: Predicate, expression

**Match**:
A leaf criterion that applies an Operator to a Queryable Property.
_Avoid_: Condition, comparison

**AND Group**:
A non-empty Filter group whose child Filters must all be satisfied.
_Avoid_: Conjunction, all-of group

**OR Group**:
A non-empty Filter group for which at least one child Filter must be satisfied.
_Avoid_: Disjunction, any-of group

**Queryable Property**:
A SQLAlchemy comparison-capable value resolved from the active model or supplied by a Fallback Property Resolver. It may represent one direct value or related values through a Proxied Attribute.
_Avoid_: Field, column

**Proxied Attribute**:
A Queryable Property backed by a SQLAlchemy association proxy. Each Match against a collection-valued Proxied Attribute independently tests whether some related value satisfies its Operator.

**Related Filter**:
A Filter evaluated against the target model of one named relationship and applied to the current model as one existential relationship condition.

**Fallback Property Resolver**:
A consumer-supplied recovery function that maps an active model and literal property name to an alternative Queryable Property after normal property compilation fails, or returns no alternative.
_Avoid_: Property factory, override

**Operator**:
The comparison or test a Match applies to a Queryable Property using an operand.
_Avoid_: Comparator, operation

**Exists**:
An Operator that tests whether a Queryable Property has at least one non-null value. Its domain meaning is presence, regardless of the SQL construct used to express it.
_Avoid_: IsNotNull

**NotExists**:
The logical complement of Exists; an Operator that tests whether a Queryable Property has no non-null value.
_Avoid_: IsNull
