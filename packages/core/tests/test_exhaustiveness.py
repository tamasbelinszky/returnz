"""The strategic gate: exhaustive ``match`` narrows Result/Maybe under ty,
pyright, and mypy with NO plugin — the thing dry-python/returns cannot do
(returns #1361).

If a ``case`` below is deleted, ``assert_never`` fails static checking under all
three checkers. That negative is proven by hand; here we pin the positive: the
checkers pass (enforced in CI) and the runtime dispatch is correct.
"""

from typing import assert_never

import pytest

from returnz import Err, Maybe, Nothing, Ok, Result, Some


def describe_result(result: Result[int, str]) -> str:
    match result:
        case Ok(value):
            return f"ok:{value}"
        case Err(error):
            return f"err:{error}"
        case _:
            assert_never(result)


def describe_maybe(maybe: Maybe[int]) -> str:
    match maybe:
        case Some(value):
            return f"some:{value}"
        case Nothing():
            return "nothing"
        case _:
            assert_never(maybe)


class TestDescribeResult:
    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            pytest.param(Ok(7), "ok:7", id="ok"),
            pytest.param(Err("boom"), "err:boom", id="err"),
        ],
    )
    def test_dispatches_each_variant(self, result: Result[int, str], expected: str) -> None:
        actual = describe_result(result)

        assert actual == expected


class TestDescribeMaybe:
    @pytest.mark.parametrize(
        ("maybe", "expected"),
        [
            pytest.param(Some(7), "some:7", id="some"),
            pytest.param(Nothing(), "nothing", id="nothing"),
        ],
    )
    def test_dispatches_each_variant(self, maybe: Maybe[int], expected: str) -> None:
        actual = describe_maybe(maybe)

        assert actual == expected
