"""Result[T, E] — a computation that either succeeds (Ok) or fails (Err).

Design: the variants are *pure data* frozen dataclasses (no methods) and each
is a subtype of the ``Result`` union directly, so bare ``Ok`` / ``Err`` work as
both constructors and ``match`` patterns (just like Rust) — no smart
constructors, no ``E``-variance games. Operations are free functions with a
single signature each — the callback's parameter type is pinned by ``result``,
so no type-checker plugin and no lambda-inference ambiguity.
"""

from collections.abc import Callable
from dataclasses import dataclass


class UnwrapError(Exception):
    """Raised by ``unwrap`` when called on an ``Err``."""


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


type Result[T, E] = Ok[T] | Err[E]


def map_ok[T, U, E](result: Result[T, E], f: Callable[[T], U]) -> Result[U, E]:
    match result:
        case Ok(value):
            return Ok(f(value))
        case Err(_):
            return result


def map_err[T, E, F](result: Result[T, E], f: Callable[[E], F]) -> Result[T, F]:
    match result:
        case Ok(_):
            return result
        case Err(error):
            return Err(f(error))


def and_then[T, U, E](result: Result[T, E], f: Callable[[T], Result[U, E]]) -> Result[U, E]:
    match result:
        case Ok(value):
            return f(value)
        case Err(_):
            return result


def unwrap[T, E](result: Result[T, E]) -> T:
    match result:
        case Ok(value):
            return value
        case Err(error):
            raise UnwrapError(f"called unwrap on Err: {error!r}")


def unwrap_or[T, E, D](result: Result[T, E], default: D) -> T | D:
    match result:
        case Ok(value):
            return value
        case Err(_):
            return default
