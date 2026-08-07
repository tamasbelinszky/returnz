"""The FastAPI boundary — turn a Result into an HTTP outcome.

``unwrap_or_raise`` returns the ``Ok`` value, or raises the ``Err``'s
``HTTPException`` (``Err -> HTTPException`` by the error's own status/tag). Call
it at the end of a route so the handler's return type stays the success type
``T`` (clean for ``response_model``) while errors become real HTTP statuses —
the boundary is invisible to the caller.

    @app.get("/users/{id}/zip")
    async def get_zip(id: str) -> str:
        return unwrap_or_raise(await zip_of(id))   # zip_of -> Result[str, HttpError]
"""

from returnz import Err, Ok, Result
from returnz_fastapi.errors import HttpError


def unwrap_or_raise[T, E: HttpError](result: Result[T, E]) -> T:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise error.to_http_exception()
