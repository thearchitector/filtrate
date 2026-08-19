# SQLAlchemy Filtering

This context describes immutable filters that select rows from a SQLAlchemy model.

## Language

**Filter**:
An immutable, recursive selection criterion containing exactly one of a Match, an AND group, an OR group, or a Related Filter, plus an optional Negate flag.
_Avoid_: Expression

**Negated Filter**:
A Filter whose complete compiled criterion is logically inverted. Negation may be applied at any level of the recursive Filter tree.
_Avoid_: Negative Predicate, NOT node

**Match**:
A leaf criterion pairing a Queryable Property with the Predicate used to test it.
_Avoid_: Condition, comparison

**AND Group**:
A non-empty Filter group whose child Filters must all be satisfied.
_Avoid_: Conjunction, all-of group

**OR Group**:
A non-empty Filter group for which at least one child Filter must be satisfied.
_Avoid_: Disjunction, any-of group

**Queryable Property**:
A SQLAlchemy comparison-capable value resolved from the active model. It may represent one direct value or related values through a Proxied Attribute.
_Avoid_: Field, column

**Proxied Attribute**:
A Queryable Property backed by a SQLAlchemy association proxy. Each Match against a collection-valued Proxied Attribute independently tests whether some related value satisfies its Predicate.

**Related Filter**:
A Filter evaluated against the target model of one named relationship and applied to the current model as one existential relationship condition.

**Dynamic Match Compiler**:
A consumer-supplied function that maps an active model and complete Match to a Boolean clause before normal property resolution, or returns `None` to request normal resolution.
_Avoid_: Property factory

**Predicate**:
The comparison or test a Match applies to a Queryable Property. A Predicate may be operandless or may carry an operand through an Operator.
_Avoid_: RawOperator, comparator

**Operator**:
An operand-bearing Predicate.
_Avoid_: Operation

**Exists**:
A Predicate that tests whether a Queryable Property has at least one non-null value. Its domain meaning is presence, regardless of the SQL construct used to express it.
_Avoid_: IsNotNull
