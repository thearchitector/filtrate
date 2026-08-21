from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from beartype.vale import Is, IsAttr
from sqlalchemy import Date, DateTime, Integer, Numeric, String, Time
from sqlalchemy import Enum as SAEnum
from sqlalchemy.types import TypeEngine

if TYPE_CHECKING:
    from beartype.vale._core._valecore import BeartypeValidator


@dataclass(frozen=True, slots=True)
class Capability:
    key: str

    # builtins

    TEXTUAL: ClassVar[Capability]
    ORDERED: ClassVar[Capability]


Capability.TEXTUAL = Capability("builtin:textual")
Capability.ORDERED = Capability("builtin:ordered")

_CAPABILITIES_ATTRIBUTE = "__sqlafilters_capabilities__"
_DEFAULT_CAPABILITIES: frozenset[Capability] = frozenset()


def filter_capabilities[T: type[TypeEngine[Any]]](
    *capabilities: Capability, replace: bool = False
) -> Callable[[T], T]:
    """
    Register the given type with the provided filtering capabilities. Use this to communicate
    a given type as compatible with families of operators.

    By default, capabilities are inherited from superclassses. Pass `replace=True` to overwrite
    any capabilities present on the parent type.
    """

    def decorator(type: T) -> T:
        caps = capabilities

        if not replace:
            inherited: frozenset[Capability] = getattr(
                type, _CAPABILITIES_ATTRIBUTE, _DEFAULT_CAPABILITIES
            )
            caps = (*caps, *inherited)

        setattr(type, _CAPABILITIES_ATTRIBUTE, frozenset(caps))
        return type

    return decorator


filter_capabilities(Capability.TEXTUAL)(String)

# some dialects like postgres have native enum types, which are not directly compatible
# with text operators such as LIKE without an explicit CAST. sqlalchemy's Enum subclasses
# String, so for consistency, remove TEXTUAL operator support.
filter_capabilities(replace=True)(SAEnum)

_register_ordered = filter_capabilities(Capability.ORDERED)
_register_ordered(Integer)
_register_ordered(Numeric)
_register_ordered(Date)
_register_ordered(DateTime)
_register_ordered(Time)


def IsCapable(*capabilities: Capability) -> BeartypeValidator:
    caps = frozenset(capabilities)
    type_validator = IsAttr[
        "type",
        Is[
            lambda ptype: caps.issubset(
                getattr(type(ptype), _CAPABILITIES_ATTRIBUTE, _DEFAULT_CAPABILITIES)
            )
        ],
    ]
    return type_validator | IsAttr["remote_attr", type_validator]
