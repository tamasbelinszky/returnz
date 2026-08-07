"""Tests for @do notation — q-based short-circuit over Result and Maybe."""

import pytest

from returnz import Err, Maybe, Nothing, Ok, Result, Some, do, ok_or, q


def parse_int(s: str) -> Result[int, str]:
    return Ok(int(s)) if s.lstrip("-").isdigit() else Err(f"not an int: {s}")


def char_at(s: str, i: int) -> Maybe[str]:
    return Some(s[i]) if i < len(s) else Nothing()


def lookup(table: dict[str, int], key: str) -> Maybe[int]:
    return Some(table[key]) if key in table else Nothing()


@do
def add_parsed(a: str, b: str) -> Result[int, str]:
    x = q(parse_int(a))
    y = q(parse_int(b))
    return Ok(x + y)


@do
def first_two_chars(s: str) -> Maybe[str]:
    a = q(char_at(s, 0))
    b = q(char_at(s, 1))
    return Some(a + b)


@do
def lookup_and_double(table: dict[str, int], key: str) -> Result[int, str]:
    value = q(ok_or(lookup(table, key), f"missing: {key}"))
    return Ok(value * 2)


@do
def sum_of_two_sums(a: str, b: str, c: str, d: str) -> Result[int, str]:
    left = q(add_parsed(a, b))
    right = q(add_parsed(c, d))
    return Ok(left + right)


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
