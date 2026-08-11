"""Tests for RzResult / RzMaybe tagged-envelope serialization."""

from typing import Literal

import pytest
from pydantic import BaseModel, TypeAdapter

from returnz import BatchResult, Err, Maybe, Nothing, Ok, Result, Some
from returnz_pydantic import RzBatchResult, RzMaybe, RzResult, TaggedError
from returnz_pydantic.serialization import _batch_result_ref  # pyright: ignore[reportPrivateUsage]


class User(BaseModel):
    id: int
    name: str


class Boom(TaggedError):
    tag: Literal["boom"] = "boom"
    detail: str


_result: TypeAdapter[Result[User, str]] = TypeAdapter(RzResult[User, str])
_maybe: TypeAdapter[Maybe[int | None]] = TypeAdapter(RzMaybe[int | None])
_err_result: TypeAdapter[Result[int, Boom]] = TypeAdapter(RzResult[int, Boom])
_batch: TypeAdapter[BatchResult[str, str, Boom]] = TypeAdapter(RzBatchResult[str, str, Boom])


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


class TestBatchResultEnvelope:
    def test_dumps_succeeded_and_failed(self) -> None:
        outcome = BatchResult(succeeded={"a": "a"}, failed={"b": Boom(detail="x")})

        assert _batch.dump_python(outcome) == {
            "succeeded": {"a": "a"},
            "failed": {"b": {"tag": "boom", "detail": "x"}},
        }

    def test_round_trips(self) -> None:
        outcome = BatchResult(succeeded={"a": "a"}, failed={"b": Boom(detail="x")})

        assert _batch.validate_python(_batch.dump_python(outcome)) == outcome


class TestBatchResultRef:
    @pytest.mark.parametrize(
        ("key_type", "value_type", "error_type", "ref"),
        [
            pytest.param(
                str,
                str,
                ValueError,
                "returnz.BatchResult_str_str_ValueError:"
                "builtins.str+builtins.str+builtins.ValueError",
                id="simple",
            ),
            pytest.param(
                str,
                str,
                int | str,
                "returnz.BatchResult_str_str_int_or_str:"
                "builtins.str+builtins.str+typing.Union(builtins.int+builtins.str)",
                id="union-error",
            ),
            pytest.param(
                str,
                dict[str, int],
                ValueError,
                "returnz.BatchResult_str_dict_str_int_ValueError:"
                "builtins.str+builtins.dict(builtins.str+builtins.int)+builtins.ValueError",
                id="nested-generic",
            ),
        ],
    )
    def test_clean_label_with_qualified_identity(
        self, key_type: object, value_type: object, error_type: object, ref: str
    ) -> None:
        assert _batch_result_ref(key_type, value_type, error_type) == ref
