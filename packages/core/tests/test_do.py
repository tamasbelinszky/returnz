"""Tests for @do / @do_async notation — require-based short-circuit."""

import asyncio

import pytest

from returnz import Err, Maybe, Nothing, Ok, Result, Some, do, do_async, ok_or, require
from returnz.do import ShortCircuit


def parse_int(s: str) -> Result[int, str]:
    return Ok(int(s)) if s.lstrip("-").isdigit() else Err(f"not an int: {s}")


def char_at(s: str, i: int) -> Maybe[str]:
    return Some(s[i]) if i < len(s) else Nothing()


def lookup(table: dict[str, int], key: str) -> Maybe[int]:
    return Some(table[key]) if key in table else Nothing()


async def async_parse_int(s: str) -> Result[int, str]:
    return parse_int(s)


@do
def add_parsed(a: str, b: str) -> Result[int, str]:
    x = require(parse_int(a))
    y = require(parse_int(b))
    return Ok(x + y)


@do
def first_two_chars(s: str) -> Maybe[str]:
    a = require(char_at(s, 0))
    b = require(char_at(s, 1))
    return Some(a + b)


@do
def lookup_and_double(table: dict[str, int], key: str) -> Result[int, str]:
    value = require(ok_or(lookup(table, key), f"missing: {key}"))
    return Ok(value * 2)


@do
def sum_of_two_sums(a: str, b: str, c: str, d: str) -> Result[int, str]:
    left = require(add_parsed(a, b))
    right = require(add_parsed(c, d))
    return Ok(left + right)


@do
def swallow_attempt(a: str) -> Result[int, str]:
    try:
        x = require(parse_int(a))
    except Exception:  # must NOT catch the short-circuit
        x = -1
    return Ok(x)


@do_async
async def async_add(a: str, b: str) -> Result[int, str]:
    x = require(await async_parse_int(a))
    y = require(await async_parse_int(b))
    return Ok(x + y)


class TestAddParsed:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            pytest.param("2", "3", Ok(5), id="both-ok"),
            pytest.param("2", "x", Err("not an int: x"), id="second-short-circuits"),
            pytest.param("x", "3", Err("not an int: x"), id="first-short-circuits"),
        ],
    )
    def test_add_parsed(self, a: str, b: str, expected: Result[int, str]) -> None:
        actual = add_parsed(a, b)

        assert actual == expected


class TestFirstTwoChars:
    @pytest.mark.parametrize(
        ("s", "expected"),
        [
            pytest.param("hello", Some("he"), id="long-enough"),
            pytest.param("x", Nothing(), id="too-short-short-circuits"),
        ],
    )
    def test_first_two_chars(self, s: str, expected: Maybe[str]) -> None:
        actual = first_two_chars(s)

        assert actual == expected


class TestLookupAndDouble:
    @pytest.mark.parametrize(
        ("table", "key", "expected"),
        [
            pytest.param({"a": 5}, "a", Ok(10), id="present"),
            pytest.param({}, "a", Err("missing: a"), id="absent-converts-to-err"),
        ],
    )
    def test_lookup_and_double(
        self, table: dict[str, int], key: str, expected: Result[int, str]
    ) -> None:
        actual = lookup_and_double(table, key)

        assert actual == expected


class TestSumOfTwoSums:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            pytest.param(("1", "2", "3", "4"), Ok(10), id="all-ok"),
            pytest.param(("1", "x", "3", "4"), Err("not an int: x"), id="nested-short-circuits"),
        ],
    )
    def test_sum_of_two_sums(
        self, values: tuple[str, str, str, str], expected: Result[int, str]
    ) -> None:
        actual = sum_of_two_sums(*values)

        assert actual == expected


class TestDoAsync:
    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            pytest.param("2", "3", Ok(5), id="both-ok"),
            pytest.param("2", "x", Err("not an int: x"), id="short-circuits"),
        ],
    )
    def test_async_add(self, a: str, b: str, expected: Result[int, str]) -> None:
        actual = asyncio.run(async_add(a, b))

        assert actual == expected


class TestShortCircuitIsUnswallowable:
    def test_except_exception_does_not_catch_short_circuit(self) -> None:
        assert swallow_attempt("x") == Err("not an int: x")

    def test_ok_path_is_unaffected(self) -> None:
        assert swallow_attempt("7") == Ok(7)


class TestStrayRequire:
    def test_require_outside_do_raises_with_guidance(self) -> None:
        with pytest.raises(ShortCircuit, match=r"outside a @do/@do_async function"):
            require(Err("boom"))
