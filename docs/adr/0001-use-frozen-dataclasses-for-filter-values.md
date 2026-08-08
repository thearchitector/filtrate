# Use frozen dataclasses for filter values

Filter, Match, and concrete Operators are frozen Python dataclasses rather than Pydantic models. Library consumers are responsible for constructing and serializing these values; this keeps the public model independent of a serialization framework and allows consumers to implement custom Operator subclasses, while giving up Pydantic validation and serialization helpers.
