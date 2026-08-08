# Pass Between bounds through unchanged

`Between` preserves the two-item operand tuple supplied by the consumer and delegates directly to SQLAlchemy's ordinary `between(lower, upper)` operation. Static typing and consumer construction are the primary correctness boundary; the Operator performs no comparison, normalization, or runtime validation of its operand.
