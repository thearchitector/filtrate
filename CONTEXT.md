# SQLAlchemy Filtering

This context defines the language for selecting rows from declarative SQLAlchemy models with reusable, composable criteria.

## Language

### Filter structure

**Filter**:
A recursive selection criterion containing exactly one Match, AND Group, OR Group, or Related Filter. A Filter may itself be negated.
_Avoid_: Expression, query

**Match**:
A leaf criterion pairing one Queryable Property with the Predicate used to test it.
_Avoid_: Condition, comparison

**AND Group**:
A non-empty Filter group whose child Filters must all be satisfied by the same model row.
_Avoid_: Conjunction, all-of group

**OR Group**:
A non-empty Filter group for which at least one child Filter must be satisfied by the same model row.
_Avoid_: Disjunction, any-of group

**Negated Filter**:
A Filter whose complete criterion, including all descendants, is logically inverted. Negation may be applied at any level of a Filter.
_Avoid_: Negative Predicate, NOT node

### Properties and scope

**Active Model**:
The model whose rows a Filter currently tests. Entering a Related Filter makes the relationship's target the Active Model for the nested Filter.
_Avoid_: Current table

**Queryable Property**:
A named value of the Active Model that may be tested by a Predicate. It may be model-defined, supplied as a Dynamic Property, or expose related values through a Proxied Attribute.
_Avoid_: Field, column

**Dynamic Property**:
A Queryable Property whose meaning is supplied by the application when a Match is interpreted rather than declared on the Active Model. Dynamic resolution takes precedence over ordinary property lookup but may decline a Match and allow that lookup to continue.
_Avoid_: Dynamic Match Compiler, property factory, virtual field

**Proxied Attribute**:
A Queryable Property that exposes values from related rows without establishing a Relationship Scope. Separate Matches against a collection-valued Proxied Attribute may be satisfied by different related rows.
_Avoid_: Related Filter, relationship traversal

**Relationship Scope**:
The related-row identity established by one Related Filter. Every Match in its nested Filter tests the same related row, while sibling Related Filters establish independent scopes.
_Avoid_: Join scope

**Related Filter**:
A Filter satisfied when a row reached through one named relationship satisfies its complete nested Filter. Negating the Related Filter denies the existence of such a row; negating its nested Filter instead requires a related row that satisfies the negated criterion.
_Avoid_: Proxied Attribute, dotted property

### Property tests

**Predicate**:
The test a Match applies to a Queryable Property. A Predicate may be operandless or may carry an Operand as an Operator.
_Avoid_: RawOperator, comparator

**Operator**:
A Predicate whose test is parameterized by an Operand.
_Avoid_: Operation

**Operand**:
The value an Operator uses to test a Queryable Property. An Operand may be a single value or a structured value such as range bounds or membership candidates.
_Avoid_: Argument, parameter

**Operator Capability**:
An explicit promise that a Queryable Property supports a named family of Predicates, independently of its Python value type.
_Avoid_: Python type compatibility, cast

**Text Predicate**:
One of Contains, Starts With, or Ends With; its operand is always treated literally. The default form is case-insensitive, while its Exact form is case-sensitive.
_Avoid_: Pattern match, LIKE

**Between**:
An ordering Predicate satisfied when a Queryable Property lies inclusively between its lower and upper bounds. Bounds retain their supplied order and are not normalized.
_Avoid_: Range normalization

**One Of**:
A comparison Predicate satisfied when a Queryable Property equals any supplied candidate. Repeated candidates do not change which rows satisfy it.
_Avoid_: OR Group

**Exists**:
A presence Predicate satisfied when a Queryable Property has at least one non-null value. For a collection-valued Proxied Attribute, empty, missing, and all-null related values are all absence.
_Avoid_: Is Not Null, SQL EXISTS
