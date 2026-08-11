from functools import reduce
from typing import TYPE_CHECKING

from beartype import BeartypeConf, BeartypeViolationVerbosity
from beartype import beartype as _beartype
from beartype.vale import IsAttr, IsEqual
from sqlalchemy import ColumnElement
from sqlalchemy.sql.elements import SQLCoreOperations

from .exceptions import InvalidFilterError

if TYPE_CHECKING:
    from beartype.vale._core._valecore import BeartypeValidator


type Property[T] = SQLCoreOperations[T]
type FilterClause = ColumnElement[bool]


def IsType(*types: object) -> BeartypeValidator:
    equalities = reduce(lambda a, b: a | b, (IsEqual[type] for type in types))
    type_validator = IsAttr["type", IsAttr["python_type", equalities]]
    return type_validator | IsAttr["remote_attr", type_validator]


beartype = _beartype(
    conf=BeartypeConf(
        violation_type=InvalidFilterError,
        violation_verbosity=BeartypeViolationVerbosity.MINIMAL,
    )
)
