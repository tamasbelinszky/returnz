"""do-notation — straight-line Result/Maybe code with ``?``-style short-circuit.

``q(container)`` unwraps an ``Ok`` / ``Some`` to its value (fully typed), or
aborts the enclosing ``@do`` function, which then returns the ``Err`` / ``Nothing``
unchanged. This is returnz's answer to Rust's ``?`` and Effect's ``yield*``.

The short-circuit is a private exception the ``@do`` wrapper catches, so
intermediate values keep their precise types — unlike generator-based
do-notation, whose ``yield`` expressions collapse to a single send type (the
core reason dry-python/returns never shipped typed do-notation; see returns
#392).

A ``@do`` function returns a container explicitly (``return Ok(...)`` /
``return Some(...)``); ``@do`` only intercepts the short-circuit, it does not
auto-wrap. To pull a ``Maybe`` into a ``Result`` do-block, convert it first with
``ok_or`` (``returnz.maybe.ok_or``); the two short-circuit types cannot mix in
one block, by construction.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any, cast, overload

from returnz.maybe import Maybe, Nothing, Some
from returnz.result import Err, Ok, Result


class _ShortCircuit(Exception):
    __slots__ = ("short",)

    def __init__(self, short: object) -> None:
        self.short = short


# Overloaded so the public contract carries no `Any`: pyright and mypy then infer
# the unwrapped value precisely (e.g. `int`). NOTE: ty 0.0.69 still degrades this
# to `Unknown` because it cannot bind a generic typevar across a union-typed
# argument (Ok[T] | Err[E]); that is a known ty gap, not unsoundness — it never
# reports a false error. pyright is therefore our primary correctness gate.
@overload
def q[T, E](container: Result[T, E]) -> T: ...
@overload
def q[T](container: Maybe[T]) -> T: ...
def q(container: Result[Any, Any] | Maybe[Any]) -> Any:
    match container:
        case Ok(value) | Some(value):
            return value
        case Err(_) | Nothing():
            raise _ShortCircuit(container)


def do[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return fn(*args, **kwargs)
        except _ShortCircuit as short_circuit:
            return cast(R, short_circuit.short)

    return wrapper
