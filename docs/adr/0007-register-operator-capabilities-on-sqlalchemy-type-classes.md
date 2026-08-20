# Register Operator Capabilities on SQLAlchemy type classes

Restricted Predicates need SQL-level facts such as whether a property supports text
search or ordering. Those facts cannot be inferred reliably from `python_type`, an
`isinstance` classifier, or a `TypeDecorator`'s `impl`: a custom type may expose an
unrelated Python value, alter comparison behavior, or intentionally omit operators
provided by its implementation type.

Operator Capabilities are therefore stored as private metadata on SQLAlchemy type
classes. The library registers conservative declarations directly on built-in family
bases, and standard variants inherit them through ordinary Python inheritance.
Consumer-defined `TypeEngine` subclasses use the same `filter_capabilities`
decorator and the same runtime lookup. Declarations extend inherited capabilities by
default; `replace=True` stores exactly the supplied set so a subtype can narrow or
clear them.

`String` receives `TEXTUAL`. Integer, numeric, and temporal families receive
`ORDERED`. SQLAlchemy `Enum` replaces the `String` declaration with an empty set
because native enum text operations are not portable across dialects. A custom
native-enum subclass may opt back in only after implementing the promised portable
semantics. A `TypeDecorator` remains opaque unless its own class declares
capabilities; nothing is inferred from `impl` or `python_type`.

This makes capability lookup identical for built-in and custom types and avoids both
a growing type-family conditional and a mutable resolver registry. The tradeoff is
process-local private metadata on SQLAlchemy's type classes. Declarations describe
supported SQL semantics only: they do not add casts or guarantee database-specific
behavior.
