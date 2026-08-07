"""Tests for parse / parse_json — Pydantic validation as a Result boundary."""

from pydantic import BaseModel

from returnz import Err, Ok
from returnz_pydantic import parse, parse_json


class Point(BaseModel):
    x: int
    y: int


class TestParse:
    def test_ok_on_valid(self) -> None:
        actual = parse(Point, {"x": 1, "y": 2})

        assert actual == Ok(Point(x=1, y=2))

    def test_err_on_invalid(self) -> None:
        actual = parse(Point, {"x": "nope", "y": 2})

        assert isinstance(actual, Err)
        assert actual.error.error_count() == 1


class TestParseJson:
    def test_ok_on_valid(self) -> None:
        actual = parse_json(Point, b'{"x": 1, "y": 2}')

        assert actual == Ok(Point(x=1, y=2))

    def test_err_on_invalid(self) -> None:
        actual = parse_json(Point, b'{"x": "nope", "y": 2}')

        assert isinstance(actual, Err)
        assert actual.error.error_count() == 1
