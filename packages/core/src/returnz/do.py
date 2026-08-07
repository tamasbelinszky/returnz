"""do-notation — straight-line Result/Maybe code with ``?``-style short-circuit.

``require(container)`` unwraps an ``Ok`` / ``Some`` to its value (precisely
typed), or aborts the enclosing ``@do`` / ``@do_async`` function, which then
returns the ``Err`` / ``Nothing`` unchanged. This is returnz's answer to Rust's
``?`` and Effect's ``yield*``.

The short-circuit is an exception the ``@do`` wrapper catches, so intermediate
values keep their precise types — unlike generator-based do-notation, whose
``yield`` expressions collapse to a single send type (the core reason
dry-python/returns never shipped typed do-notation; see returns #392).

Contract and caveats:

* ``@do`` does not auto-wrap: return a container explicitly (``return Ok(...)`` /
  ``return Some(...)``). The type checker enforces this against the declared
  return type.
* ``require`` preserves the ``Err`` / ``Nothing`` as-is. The declared error type
  of a block is NOT statically checked against the errors you ``require`` (the
  short-circuit travels as an exception, which Python cannot type). So only
  ``require`` results whose error is that type — or convert first with
  ``map_err``.
* ``require`` must run inside a ``@do`` / ``@do_async`` function (directly or
  transitively). A stray ``require`` on an ``Err`` / ``Nothing`` raises
  ``ShortCircuit`` with a message telling you to add the decorator.
* To pull a ``Maybe`` into a ``Result`` block, convert it first with ``ok_or``
  (``returnz.maybe.ok_or``); the two short-circuit types cannot mix in one block.
* Use ``@do`` for ``def`` and ``@do_async`` for ``async def``; ``require`` is the
  same in both (it unwraps an already-awaited container).
"""

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, cast, overload

from returnz.maybe import Maybe, Nothing, Some
from returnz.result import Err, Ok, Result


class ShortCircuit(BaseException):
    """Control-flow signal raised by ``require`` and caught by the nearest ``@do``.

    Subclasses ``BaseException`` (not ``Exception``) deliberately: a user's
    ``except Exception`` inside a block must not swallow the short-circuit. Only
    the ``@do`` / ``@do_async`` wrapper catches it. Not part of the public API
    (kept out of ``__all__``); exposed unprefixed only so it reads clearly in a
    traceback and can be referenced in tests. Do not catch it yourself.
    """

    __slots__ = ("short",)

    def __init__(self, short: object) -> None:
        self.short = short
        super().__init__(
            "require() short-circuited outside a @do/@do_async function — "
            "decorate the enclosing function"
        )


# Overloaded so the public contract carries no `Any`: pyright and mypy then infer
# the unwrapped value precisely (e.g. `int`). NOTE: ty 0.0.69 still degrades this
# to `Unknown` because it cannot bind a generic typevar across a union-typed
# argument (Ok[T] | Err[E]); that is a known ty gap, not unsoundness — it never
# reports a false error. pyright is therefore our primary correctness gate.
@overload
def require[T, E](container: Result[T, E]) -> T: ...
@overload
def require[T](container: Maybe[T]) -> T: ...
def require(container: Result[Any, Any] | Maybe[Any]) -> Any:
    match container:
        case Ok(value) | Some(value):
            return value
        case Err(_) | Nothing():
            raise ShortCircuit(container)


def do[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except ShortCircuit as short_circuit:
            return cast(R, short_circuit.short)

    return wrapper


def do_async[**P, R](
    fn: Callable[P, Coroutine[Any, Any, R]],
) -> Callable[P, Coroutine[Any, Any, R]]:
    @wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ShortCircuit as short_circuit:
            return cast(R, short_circuit.short)

    return wrapper
