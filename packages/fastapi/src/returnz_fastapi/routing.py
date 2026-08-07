"""Routers that turn a returnz return type into a correct, documented endpoint.

Both work the same way — introspect the handler's return annotation, set the
response schema, and transform the return value — differing only in the transform.

``ResultRouter`` — from ``-> Result[T, E]``:

1. **unwraps** ``Ok`` to its value (response body is ``T``) or raises the ``Err``'s
   ``HTTPException`` (``Err -> HTTPException`` by the error's status);
2. sets ``response_model = T`` so the ``200`` schema is correct;
3. **auto-derives the OpenAPI error responses** from ``E`` — each ``HttpError`` in
   the (possibly union) error type becomes a documented ``responses`` entry.
   Plain FastAPI documents only ``200`` + ``422``; here your typed errors show up
   in ``/docs`` out of the box.

``BatchRouter`` — from ``-> BatchResult[K, T, E]``: responds **HTTP 207
Multi-Status** with the ``{succeeded, failed}`` envelope (via ``RzBatchResult``),
so a partial-success batch returns every outcome with typed per-item failures
instead of a whole-batch 500.

Usage::

    router = ResultRouter()

    @router.get("/users/{id}")
    async def get_user(id: str) -> Result[User, NotFound | RateLimited]:
        ...
"""

import functools
import inspect
import types
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, Union, get_args, get_origin, get_type_hints

from fastapi import APIRouter
from fastapi.datastructures import DefaultPlaceholder
from fastapi.routing import APIRoute

from returnz import BatchResult, Result
from returnz.result import Err, Ok
from returnz_fastapi.errors import HttpError
from returnz_pydantic import RzBatchResult


def _is_result(annotation: object) -> bool:
    return get_origin(annotation) is Result


def _is_batch_result(annotation: object) -> bool:
    return get_origin(annotation) is BatchResult


def _error_types(annotation: object) -> list[type[HttpError]]:
    """Flatten a (possibly union) error annotation to its HttpError members."""
    members = (
        get_args(annotation)
        if get_origin(annotation) in (Union, types.UnionType)
        else (annotation,)
    )
    return [m for m in members if isinstance(m, type) and issubclass(m, HttpError)]


def _responses_for(errors: list[type[HttpError]]) -> dict[int | str, dict[str, Any]]:
    """Group error types by status into OpenAPI ``responses`` (Union per status)."""
    by_status: dict[int, list[type[HttpError]]] = {}
    for error in errors:
        by_status.setdefault(error.status_code, []).append(error)
    responses: dict[int | str, dict[str, Any]] = {}
    for status, group in by_status.items():
        model: Any = group[0]
        for extra in group[1:]:
            model = model | extra
        responses[status] = {"model": model}
    return responses


def _unwrap(result: Result[Any, Any]) -> Any:
    match result:
        case Ok(value):
            return value
        case Err(error):
            if not isinstance(error, HttpError):
                raise TypeError(
                    f"ResultRoute requires the Err type to be an HttpError; "
                    f"got {type(error).__name__}"
                )
            raise error.to_http_exception()


class ResultRoute(APIRoute):
    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        annotation = get_type_hints(endpoint).get("return")
        if annotation is not None and _is_result(annotation):
            success_type, error_type = get_args(annotation)

            response_model = kwargs.get("response_model")
            if response_model is None or isinstance(response_model, DefaultPlaceholder):
                kwargs["response_model"] = success_type

            responses: dict[Any, Any] = dict(kwargs.get("responses") or {})
            for status, spec in _responses_for(_error_types(error_type)).items():
                responses.setdefault(status, spec)
            kwargs["responses"] = responses

            endpoint = _wrap_unwrap(endpoint, success_type)
        super().__init__(path, endpoint, **kwargs)


class ResultRouter(APIRouter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", ResultRoute)
        super().__init__(*args, **kwargs)


class BatchRoute(APIRoute):
    """From a handler ``-> BatchResult[K, T, E]``: respond **HTTP 207 Multi-Status**
    with the ``{succeeded, failed}`` envelope (serialized via ``RzBatchResult``, so
    each per-item failure keeps its typed schema), documented in OpenAPI.

    The web analog of AWS ``batchItemFailures``: successes and typed failures in
    one response, never a whole-batch 500. Reuses the same introspect-return-type
    approach as ``ResultRoute``; here the transform is "serialize the envelope"
    rather than "unwrap or raise".
    """

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        annotation = get_type_hints(endpoint).get("return")
        if annotation is not None and _is_batch_result(annotation):
            key_type, value_type, error_type = get_args(annotation)

            if kwargs.get("status_code") is None:
                kwargs["status_code"] = HTTPStatus.MULTI_STATUS

            response_model = kwargs.get("response_model")
            if response_model is None or isinstance(response_model, DefaultPlaceholder):
                # types from get_args, built at runtime — mypy can't verify vars-as-types.
                kwargs["response_model"] = RzBatchResult[key_type, value_type, error_type]  # type: ignore[valid-type]
        super().__init__(path, endpoint, **kwargs)


class BatchRouter(APIRouter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("route_class", BatchRoute)
        super().__init__(*args, **kwargs)


def _wrap_unwrap(endpoint: Callable[..., Any], success_type: Any) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _unwrap(await endpoint(*args, **kwargs))

        wrapper: Callable[..., Any] = async_wrapper
    else:

        @functools.wraps(endpoint)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            return _unwrap(endpoint(*args, **kwargs))

        wrapper = sync_wrapper

    # Replace the copied `-> Result[T, E]` annotation so FastAPI never infers it.
    wrapper.__annotations__ = {**endpoint.__annotations__, "return": success_type}
    return wrapper
