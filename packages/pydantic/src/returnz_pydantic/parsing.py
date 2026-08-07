"""Pydantic validation as a Result boundary — parse, don't validate.

``parse`` turns Pydantic's raise-on-failure validation into a typed value: the
canonical fallible operation in a Python app becomes a ``Result`` you compose
with (``require`` it inside ``@do``, ``match`` on it, serialize it).
"""

from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from returnz import Err, Ok, Result

# TypeAdapter construction is expensive; Pydantic recommends reusing one per type
# rather than rebuilding it on every call. (functools.cache erases the M binding.)
_ADAPTERS: dict[type, TypeAdapter[Any]] = {}


def _adapter[M](model: type[M]) -> TypeAdapter[M]:
    cached = _ADAPTERS.get(model)
    if cached is not None:
        return cast("TypeAdapter[M]", cached)
    adapter: TypeAdapter[M] = TypeAdapter(model)
    _ADAPTERS[model] = adapter
    return adapter


def parse[M](model: type[M], data: object) -> Result[M, ValidationError]:
    try:
        return Ok(_adapter(model).validate_python(data))
    except ValidationError as error:
        return Err(error)


def parse_json[M](model: type[M], data: str | bytes) -> Result[M, ValidationError]:
    try:
        return Ok(_adapter(model).validate_json(data))
    except ValidationError as error:
        return Err(error)
