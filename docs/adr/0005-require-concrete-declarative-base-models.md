# Require concrete DeclarativeBase models

Filtering is supported for a concrete mapped subclass of `DeclarativeBase`, using the consumer-owned declarative registry and metadata; `MappedAsDataclass` remains an optional compatible mixin. This deliberately excludes imperative and decorator-only declarative mapping so the compiler can use the model's `__mapper__` directly instead of maintaining compatibility branches or runtime validation for mapping styles outside its core contract.
