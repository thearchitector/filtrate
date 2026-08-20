# Declare Operator Capabilities on TypeDecorator classes

Restricted Predicates need SQL-level facts such as whether a property supports text
search or ordering. A `TypeDecorator` can expose a Python type unrelated to its SQL
representation, customize its comparison behavior, or wrap an implementation whose
operators it intentionally does not preserve. Python inheritance, `python_type`, and
`impl` therefore cannot establish those semantics reliably.

Custom `TypeDecorator` classes declare supported Operator Capabilities with
`filter_capabilities`. Declarations are attached to the class, inherited additively,
and consulted at runtime. Undeclared decorators remain opaque even when their
implementation is a built-in string or numeric type. Built-in SQLAlchemy types receive
only conservative family defaults, while equality, membership, and presence remain
unrestricted.

This keeps custom SQL semantics near the type that owns them, avoids a mutable global
resolver registry, and prevents accidental support inferred from implementation
details. Consumers must opt in when a custom type truly implements a restricted
operator family, and the declaration does not add casts or promise dialect-specific
ordering behavior.
