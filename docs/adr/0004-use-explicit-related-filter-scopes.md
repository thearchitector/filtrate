# Use explicit Related Filter scopes

Relationship filtering is represented by `Filter(via=Related(relationship=..., where=...))`, which compiles the complete nested Filter through SQLAlchemy's relationship `.any()` or `.has()` comparator. Explicit scopes make same-related-row binding structural and support deliberate nesting without giving dots implicit traversal meaning, adding joins, or mutating consumer statements. Proxied Attributes remain the separate mechanism for independent parent-level Matches against related values.
