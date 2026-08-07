"""Pydantic validation as a Result boundary — parse, don't validate.

``parse`` turns Pydantic's raise-on-failure validation into a typed value: the
canonical fallible operation in a Python app becomes a ``Result`` you compose
with (``require`` it inside ``@do``, ``match`` on it, serialize it).
"""

from pydantic import TypeAdapter, ValidationError

from returnz import Err, Ok, Result


def parse[M](model: type[M], data: object) -> Result[M, ValidationError]:
    try:
        return Ok(TypeAdapter(model).validate_python(data))
    except ValidationError as error:
        return Err(error)


def parse_json[M](model: type[M], data: str | bytes) -> Result[M, ValidationError]:
    try:
        return Ok(TypeAdapter(model).validate_json(data))
    except ValidationError as error:
        return Err(error)
