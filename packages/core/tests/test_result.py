"""Tests for Result — free-function operations over Ok / Err."""

import pytest

from returnz import Err, Ok, Result, UnwrapError, and_then, map_err, map_ok, unwrap, unwrap_or


class TestMapOk:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(Ok(2), Ok(3), id="ok-applies-function"),
            pytest.param(Err("boom"), Err("boom"), id="err-passes-through"),
        ],
    )
    def test_map_ok(self, result: Result[int, str], expected: Result[int, str]) -> None:
        actual = map_ok(result, lambda x: x + 1)

        assert actual == expected


class TestMapErr:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(Ok(2), Ok(2), id="ok-passes-through"),
            pytest.param(Err("boom"), Err("BOOM"), id="err-applies-function"),
        ],
    )
    def test_map_err(self, result: Result[int, str], expected: Result[int, str]) -> None:
        actual = map_err(result, lambda e: e.upper())

        assert actual == expected


class TestAndThen:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(Ok(2), Ok(20), id="ok-chains"),
            pytest.param(Err("boom"), Err("boom"), id="err-short-circuits"),
        ],
    )
    def test_and_then(self, result: Result[int, str], expected: Result[int, str]) -> None:
        actual = and_then(result, lambda x: Ok(x * 10))

        assert actual == expected


class TestUnwrap:
    def test_ok_returns_value(self) -> None:
        assert unwrap(Ok(2)) == 2

    def test_err_raises(self) -> None:
        with pytest.raises(UnwrapError, match=r"called unwrap on Err: 'boom'"):
            unwrap(Err("boom"))


class TestUnwrapOr:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(Ok(2), 2, id="ok-returns-value"),
            pytest.param(Err("boom"), 99, id="err-returns-default"),
        ],
    )
    def test_unwrap_or(self, result: Result[int, str], expected: int) -> None:
        actual = unwrap_or(result, 99)

        assert actual == expected
