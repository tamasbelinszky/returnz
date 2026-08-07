"""Tests for Maybe — free-function operations over Some / Nothing."""

import pytest

from returnz import Maybe, Nothing, Some
from returnz.maybe import and_then, map_some, unwrap_or


class TestMapSome:
    @pytest.mark.parametrize(
        ("maybe", "expected"),
        [
            pytest.param(Some(2), Some(3), id="some-applies-function"),
            pytest.param(Nothing(), Nothing(), id="nothing-passes-through"),
        ],
    )
    def test_map_some(self, maybe: Maybe[int], expected: Maybe[int]) -> None:
        actual = map_some(maybe, lambda x: x + 1)

        assert actual == expected


class TestAndThen:
    @pytest.mark.parametrize(
        ("maybe", "expected"),
        [
            pytest.param(Some(2), Some(20), id="some-chains"),
            pytest.param(Nothing(), Nothing(), id="nothing-short-circuits"),
        ],
    )
    def test_and_then(self, maybe: Maybe[int], expected: Maybe[int]) -> None:
        actual = and_then(maybe, lambda x: Some(x * 10))

        assert actual == expected


class TestUnwrapOr:
    @pytest.mark.parametrize(
        ("maybe", "expected"),
        [
            pytest.param(Some(2), 2, id="some-returns-value"),
            pytest.param(Nothing(), 99, id="nothing-returns-default"),
        ],
    )
    def test_unwrap_or(self, maybe: Maybe[int], expected: int) -> None:
        actual = unwrap_or(maybe, 99)

        assert actual == expected
