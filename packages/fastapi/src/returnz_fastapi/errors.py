"""HttpError — a TaggedError that knows its HTTP status.

Subclass it for errors that should become HTTP responses. ``status_code`` is a
``ClassVar`` (not serialized); the serialized body is the tagged data itself, so
an ``Err(NotFound(id="42"))`` becomes ``404 {"tag": "not_found", "id": "42"}`` —
exactly the schema OpenAPI documents.

    class NotFound(HttpError):
        status_code = 404
        tag: Literal["not_found"] = "not_found"
        id: str

``to_response`` is that bare body (what ``ResultRouter`` sends);
``to_http_exception`` is the same data behind FastAPI's ``{"detail": ...}``
wrapper, for plain routes via ``unwrap_or_raise``.
"""

from typing import ClassVar

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from returnz_pydantic import TaggedError


class HttpError(TaggedError):
    status_code: ClassVar[int] = 500

    def to_response(self) -> JSONResponse:
        return JSONResponse(status_code=self.status_code, content=self.model_dump(mode="json"))

    def to_http_exception(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.model_dump())
