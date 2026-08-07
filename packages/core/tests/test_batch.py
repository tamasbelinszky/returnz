"""Tests for batch / partial-success combinators."""

import asyncio
from contextvars import ContextVar

from returnz import BatchResult, Err, Ok, Result, collect, map_batch, partition

_cid: ContextVar[str] = ContextVar("returnz_test_cid", default="none")


async def _delete(order_id: str) -> Result[str, str]:
    await asyncio.sleep(0)
    return Ok(order_id) if order_id != "bad" else Err(f"failed: {order_id}")


async def _echo_cid(item: str) -> Result[str, str]:
    await asyncio.sleep(0)
    return Ok(f"{item}:{_cid.get()}")


class TestPartition:
    def test_splits_successes_and_failures(self) -> None:
        results: list[Result[int, str]] = [Ok(1), Err("a"), Ok(2), Err("b")]

        assert partition(results) == ([1, 2], ["a", "b"])


class TestCollect:
    def test_all_ok_gives_list(self) -> None:
        results: list[Result[int, str]] = [Ok(1), Ok(2), Ok(3)]

        assert collect(results) == Ok([1, 2, 3])

    def test_first_err_short_circuits(self) -> None:
        results: list[Result[int, str]] = [Ok(1), Err("boom"), Ok(2)]

        assert collect(results) == Err("boom")


class TestMapBatch:
    def test_partial_success_keyed_by_input(self) -> None:
        outcome = asyncio.run(map_batch(["a", "bad", "c"], _delete))

        assert outcome.succeeded == {"a": "a", "c": "c"}
        assert outcome.failed == {"bad": "failed: bad"}
        assert outcome.failed_keys == ["bad"]

    def test_all_ok_when_nothing_fails(self) -> None:
        outcome = asyncio.run(map_batch(["a", "c"], _delete))

        assert outcome.all_ok is True
        assert outcome.any_failed is False


class TestBoundedConcurrency:
    def test_keeps_input_to_outcome_mapping(self) -> None:
        outcome = asyncio.run(map_batch(["a", "bad", "c", "d"], _delete, concurrency=2))

        assert outcome.succeeded == {"a": "a", "c": "c", "d": "d"}
        assert outcome.failed == {"bad": "failed: bad"}


class TestContextvarPropagation:
    def test_ambient_contextvar_visible_in_each_concurrent_op(self) -> None:
        async def scenario() -> BatchResult[str, str, str]:
            _cid.set("req-123")
            return await map_batch(["a", "b"], _echo_cid, concurrency=2)

        outcome = asyncio.run(scenario())

        assert outcome.succeeded == {"a": "a:req-123", "b": "b:req-123"}
