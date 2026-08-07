"""Batch / partial-success combinators — run many independent operations and
keep every outcome (never short-circuit).

This is the applicative counterpart to ``@do`` (which bails on the first error):
``partition`` / ``map_batch`` run all operations and report successes *and*
failures, keyed by input so the failures are a ready-made retry set (the shape
of AWS SQS ``batchItemFailures``). ``collect`` is the all-or-nothing variant.

``map_batch`` runs its operations with ``asyncio.gather``, so each op runs in a
copied context: any ambient ``ContextVar`` (a correlation/request id, etc.)
propagates into every concurrent op — and its logs and outbound calls — without
being passed as a parameter. Observability stays ambient, not threaded through
signatures.
"""

import asyncio
from collections.abc import Awaitable, Callable, Hashable, Iterable
from dataclasses import dataclass

from returnz.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class BatchResult[K: Hashable, T, E]:
    succeeded: dict[K, T]
    failed: dict[K, E]

    @property
    def all_ok(self) -> bool:
        return not self.failed

    @property
    def any_failed(self) -> bool:
        return bool(self.failed)

    @property
    def failed_keys(self) -> list[K]:
        """The keys that failed — the retry set (AWS ``batchItemFailures``)."""
        return list(self.failed)


def partition[T, E](results: Iterable[Result[T, E]]) -> tuple[list[T], list[E]]:
    succeeded: list[T] = []
    failed: list[E] = []
    for result in results:
        match result:
            case Ok(value):
                succeeded.append(value)
            case Err(error):
                failed.append(error)
    return succeeded, failed


def collect[T, E](results: Iterable[Result[T, E]]) -> Result[list[T], E]:
    values: list[T] = []
    for result in results:
        match result:
            case Ok(value):
                values.append(value)
            case Err(_):
                return result
    return Ok(values)


async def gather_results[T, E](
    awaitables: Iterable[Awaitable[Result[T, E]]],
    *,
    concurrency: int | None = None,
) -> list[Result[T, E]]:
    if concurrency is None:
        return list(await asyncio.gather(*awaitables))

    semaphore = asyncio.Semaphore(concurrency)

    async def _run(awaitable: Awaitable[Result[T, E]]) -> Result[T, E]:
        async with semaphore:
            return await awaitable

    return list(await asyncio.gather(*(_run(awaitable) for awaitable in awaitables)))


async def map_batch[K: Hashable, T, E](
    items: Iterable[K],
    op: Callable[[K], Awaitable[Result[T, E]]],
    *,
    concurrency: int | None = None,
) -> BatchResult[K, T, E]:
    keys = list(items)
    results = await gather_results([op(key) for key in keys], concurrency=concurrency)

    succeeded: dict[K, T] = {}
    failed: dict[K, E] = {}
    for key, result in zip(keys, results, strict=True):
        match result:
            case Ok(value):
                succeeded[key] = value
            case Err(error):
                failed[key] = error
    return BatchResult(succeeded=succeeded, failed=failed)
