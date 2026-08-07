"""Tests for RzResult / RzMaybe tagged-envelope serialization."""

from typing import Literal

import pytest
from pydantic import BaseModel, TypeAdapter

from returnz import Err, Maybe, Nothing, Ok, Result, Some
from returnz_pydantic import RzMaybe, RzResult, TaggedError


class User(BaseModel):
    id: int
    name: str


class Boom(TaggedError):
    tag: Literal["boom"] = "boom"
    detail: str


_result: TypeAdapter[Result[User, str]] = TypeAdapter(RzResult[User, str])
_maybe: TypeAdapter[Maybe[int | None]] = TypeAdapter(RzMaybe[int | None])
_err_result: TypeAdapter[Result[int, Boom]] = TypeAdapter(RzResult[int, Boom])


class Envelope(BaseModel):
    result: RzResult[User, str]


class TestResultEnvelope:
    @pytest.mark.parametrize(
        ("value", "envelope"),
        [
            pytest.param(Ok(User(id=1, name="Ann")), {"ok": {"id": 1, "name": "Ann"}}, id="ok"),
            pytest.param(Err("not found"), {"err": "not found"}, id="err"),
        ],
    )
    def test_dumps_tagged_envelope(self, value: Result[User, str], envelope: object) -> None:
        assert _result.dump_python(value) == envelope

    @pytest.mark.parametrize(
        ("envelope", "value"),
        [
            pytest.param({"ok": {"id": 1, "name": "Ann"}}, Ok(User(id=1, name="Ann")), id="ok"),
            pytest.param({"err": "not found"}, Err("not found"), id="err"),
        ],
    )
    def test_reconstructs_by_tag(self, envelope: object, value: Result[User, str]) -> None:
        assert _result.validate_python(envelope) == value


class TestMaybeSomeNoneDistinctFromNothing:
    def test_serialize_differently(self) -> None:
        assert _maybe.dump_python(Some(None)) == {"some": None}
        assert _maybe.dump_python(Nothing()) == {"nothing": True}

    def test_round_trip_preserves_the_distinction(self) -> None:
        assert _maybe.validate_python({"some": None}) == Some(None)
        assert _maybe.validate_python({"nothing": True}) == Nothing()


class TestInstanceAcceptedInModel:
    def test_accepts_variant_instance_and_dumps_envelope(self) -> None:
        model = Envelope(result=Ok(User(id=9, name="Zoe")))

        assert model.model_dump() == {"result": {"ok": {"id": 9, "name": "Zoe"}}}


class TestTaggedErrorAsError:
    def test_serializes_error_with_its_tag(self) -> None:
        dumped = _err_result.dump_python(Err(Boom(detail="kaboom")))

        assert dumped == {"err": {"tag": "boom", "detail": "kaboom"}}
