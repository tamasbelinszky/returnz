---
name: returnz
description: >-
  Idiomatic returnz for Python — Result/Maybe error handling, @do/require
  do-notation, partial-success batches, Pydantic serialization, and FastAPI
  routers. Use when code imports returnz / returnz_pydantic / returnz_fastapi,
  or when the task involves errors-as-values (Result, Ok, Err), optional values
  (Maybe, Some, Nothing), do-notation (@do, @do_async, require), running many
  operations with partial success (map_batch, BatchResult), serializing a Result
  with Pydantic (RzResult), or returning a Result from a FastAPI endpoint
  (ResultRouter, BatchRouter, HttpError). Python 3.14+.
---

# returnz

`Result` / `Maybe` for modern Python: concrete PEP 695 generics, **no
higher-kinded types, no type-checker plugin**. Errors are *values*, not
exceptions. Verified by `pyright` + `mypy`; `ty` is a fast smoke-check.

## Core model

Construct **and** match with the variant classes — there are no smart
constructors. Each variant is a subtype of its union (like Rust's `Ok`/`Err`).

```python
from returnz import Ok, Err, Result, Some, Nothing, Maybe

def parse_int(s: str) -> Result[int, str]:
    return Ok(int(s)) if s.lstrip("-").isdigit() else Err(f"not an int: {s}")

match parse_int("42"):          # exhaustive — checkers flag a missing case
    case Ok(value): ...
    case Err(error): ...
```

Result ops are top-level free functions: `map_ok`, `map_err`, `and_then`,
`unwrap`, `unwrap_or`. **Maybe ops live in `returnz.maybe`** (`map_some`,
`and_then`, `unwrap_or`) — their names would collide at top level. `ok_or`
converts a `Maybe` to a `Result`.

## `@do` / `require` — the `?` of returnz

Straight-line code that short-circuits on the first `Err`/`Nothing`. `require`
unwraps or bails; the `@do` function returns the `Err`/`Nothing` unchanged.
Return a container explicitly — `@do` does not auto-wrap.

```python
from returnz import Ok, Result, do, do_async, require

@do
def add(a: str, b: str) -> Result[int, str]:
    x = require(parse_int(a))   # int, or short-circuit
    y = require(parse_int(b))
    return Ok(x + y)

@do_async                       # for async def (FastAPI handlers, etc.)
async def fetch_and_add(a: str, b: str) -> Result[int, str]:
    x = require(await fetch(a))
    return Ok(x)
```

## Pick the right shape

| Need | Tool |
| --- | --- |
| Sequential, dependent steps, bail on first error | `@do` / `require` |
| Validate untrusted input, collect all errors | `parse` (returnz-pydantic) |
| Run many independent ops, keep every outcome | `map_batch` (partial success) |

## Partial-success batches

```python
from returnz import BatchResult, map_batch, partition

async def delete_orders(ids: list[str]) -> BatchResult[str, str, DeleteError]:
    return await map_batch(ids, delete_one, concurrency=8)

outcome = await delete_orders(["a", "bad", "c"])
outcome.succeeded   # {"a": "a", "c": "c"}
outcome.failed      # {"bad": DeleteError(...)}
outcome.failed_keys # ["bad"] — the retry set
```

`map_batch` never short-circuits and preserves ambient `ContextVar`s (e.g. a
correlation id) into each concurrent op. `partition(results)` splits a list of
`Result` into `(oks, errs)`; `collect(results)` is all-or-nothing.

## Pydantic (returnz-pydantic)

- **`parse(Model, data) -> Result[Model, ValidationError]`** — validation as a
  boundary (parse, don't validate).
- **`RzResult[T, E]` / `RzMaybe[T]` / `RzBatchResult[K, T, E]`** — use these as
  Pydantic *field types*; they serialize as tagged envelopes
  (`{"ok": …}` / `{"err": …}`). Keep plain `Result` everywhere else.
- **`TaggedError`** — base for matchable, serializable typed errors (subclass and
  add a `Literal` `tag`).

## FastAPI (returnz-fastapi)

```python
from returnz_fastapi import ResultRouter, BatchRouter, HttpError

class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    id: str

router = ResultRouter()

@router.get("/users/{id}")
async def get_user(id: str) -> Result[User, NotFound | RateLimited]:
    ...   # Ok → 200 User; Err → its status; errors auto-documented in /docs
```

- **`ResultRouter`** — from `-> Result[T, E]`: unwraps `Ok→T`, maps `Err` to its
  HTTP status, and **documents each typed error in OpenAPI** from the return type.
- **`BatchRouter`** — from `-> BatchResult[K, T, E]`: HTTP **207 Multi-Status**
  with the `{succeeded, failed}` envelope.
- **`unwrap_or_raise(result)`** — the explicit form for a plain `@app.get`.

## Idioms & anti-patterns

- **Return `Err`, don't `raise`** for domain errors — errors are values. (In a
  batch op especially: a raise kills the whole batch; return `Err`.)
- **Construct with `Ok`/`Err`/`Some`/`Nothing`** — no `ok()`/`some()` helpers exist.
- **`require` only inside `@do`/`@do_async`** — a stray `require` raises loudly.
- **Don't mix short-circuit types in one `@do`** — convert a `Maybe` first with
  `ok_or(maybe, error)`.
- **`Some(None)` ≠ `Nothing`** — both are representable and distinct on the wire.
- **Pydantic fields need `RzResult`/`RzMaybe`/`RzBatchResult`**, not bare
  `Result`/`Maybe`/`BatchResult` (the core stays Pydantic-free).
- **Don't reach for monad transformers / HKT** — the library is deliberately
  concrete. Compose with `@do` and free functions.
- **`ty` may report a combinator's result as `Unknown`** on `Result`/`Maybe`
  values — that's a known `ty` gap with union generics, not a bug. Trust
  `pyright`/`mypy` (both infer precisely).
