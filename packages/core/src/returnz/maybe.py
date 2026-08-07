"""Maybe[T] — an optional value: Some(value) or Nothing.

Same shape as Result: pure-data variants + free-function operations. Bare
``Some`` / ``Nothing`` work as both constructors and ``match`` patterns.
``Nothing`` carries no type parameter; construct it as ``Nothing()`` and match
it as ``case Nothing():``.
"""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Some[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Nothing:
    pass


type Maybe[T] = Some[T] | Nothing


def map_some[T, U](maybe: Maybe[T], f: Callable[[T], U]) -> Maybe[U]:
    match maybe:
        case Some(value):
            return Some(f(value))
        case Nothing():
            return maybe


def and_then[T, U](maybe: Maybe[T], f: Callable[[T], Maybe[U]]) -> Maybe[U]:
    match maybe:
        case Some(value):
            return f(value)
        case Nothing():
            return maybe


def unwrap_or[T, D](maybe: Maybe[T], default: D) -> T | D:
    match maybe:
        case Some(value):
            return value
        case Nothing():
            return default
