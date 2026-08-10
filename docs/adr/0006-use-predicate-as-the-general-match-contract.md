# Use Predicate as the general Match contract

`Match` exposes its Predicate through the keyword-only `using` field, and public
typing uses `Predicate[T]` as the operand-independent `apply()` contract.
`Operator[T, OT]` remains the operand-bearing Predicate specialization. This
replaces the implementation-oriented `RawOperator` name and lets presence and
consumer-defined operandless Predicates share the same public contract without
pretending to carry an operand.
