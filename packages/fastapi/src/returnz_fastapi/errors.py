"""HttpError — a TaggedError that knows its HTTP status.

Subclass it for errors that should become HTTP responses. ``status_code`` is a
``ClassVar`` (not serialized); the serialized body is the tagged data itself, so
an ``Err(NotFound(id="42"))`` becomes ``404 {"detail": {"tag": "not_found",
"id": "42"}}``.

    class NotFound(HttpError):
        status_code = 404
        tag: Literal["not_found"] = "not_found"
        id: str
"""

from typing import ClassVar

from fastapi import HTTPException

from returnz_pydantic import TaggedError


class HttpError(TaggedError):
    status_code: ClassVar[int] = 500

    def to_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.model_dump())
