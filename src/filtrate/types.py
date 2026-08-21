from beartype import BeartypeConf, BeartypeViolationVerbosity
from beartype import beartype as _beartype
from sqlalchemy import ColumnElement
from sqlalchemy.sql.elements import SQLCoreOperations

from .exceptions import InvalidFilterError

type Property[T] = SQLCoreOperations[T]
type FilterClause = ColumnElement[bool]

beartype = _beartype(
    conf=BeartypeConf(
        violation_type=InvalidFilterError,
        violation_verbosity=BeartypeViolationVerbosity.MINIMAL,
    )
)
