"""returnz-pydantic — Pydantic v2 integration for returnz.

Tagged-envelope serialization (``RzResult`` / ``RzMaybe``), validation as a
``Result`` boundary (``parse`` / ``parse_json``), and a base for typed,
serializable errors (``TaggedError``).
"""

from returnz_pydantic.errors import TaggedError
from returnz_pydantic.parsing import parse, parse_json
from returnz_pydantic.serialization import RzBatchResult, RzMaybe, RzResult

__all__ = [
    "RzBatchResult",
    "RzMaybe",
    "RzResult",
    "TaggedError",
    "parse",
    "parse_json",
]
