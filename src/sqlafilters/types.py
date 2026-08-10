from sqlalchemy import ColumnExpressionArgument
from sqlalchemy.sql.elements import SQLCoreOperations

type Property[T] = SQLCoreOperations[T]
type FilterClause = ColumnExpressionArgument[bool]
