# returnz

`Result`, `Maybe`, and typed error handling for modern Python — a narrowed,
FastAPI-friendly reimagining of [`dry-python/returns`](https://github.com/dry-python/returns).

**The bet:** concrete [PEP 695](https://peps.python.org/pep-0695/) generics + native
type checkers (`pyright`, plugin-free `mypy`, `ty`) + Pydantic at the boundary +
FastAPI for the web. **No higher-kinded-type emulation. No type-checker plugin.**
Python **3.14+**.

One domain runs through this whole README — orders that can be found, cancelled,
shipped, and deleted — from zero-dep core to Pydantic boundary to HTTP.

```python
from dataclasses import dataclass

from returnz import Err, Ok, Result, do, require


@dataclass(frozen=True)
class NotFound:
    order_id: str


@dataclass(frozen=True)
class AlreadyShipped:
    order_id: str


_STATUS = {"o1": "pending", "o2": "shipped"}


def find_status(order_id: str) -> Result[str, NotFound]:
    status = _STATUS.get(order_id)
    return Ok(status) if status is not None else Err(NotFound(order_id))


@do
def cancel_order(order_id: str) -> Result[str, NotFound | AlreadyShipped]:
    status = require(find_status(order_id))  # the `?` of returnz — unwrap or short-circuit
    if status == "shipped":
        return Err(AlreadyShipped(order_id))
    return Ok(f"order {order_id} cancelled")


match cancel_order("o2"):
    case Ok(message):
        print(message)
    case Err(NotFound(order_id)):
        print(f"no such order: {order_id}")
    case Err(AlreadyShipped(order_id)):
        print(f"order {order_id} already shipped")  # ← this branch
```

Errors are plain values with types — so the `match` is **exhaustive**: delete the
`AlreadyShipped` arm and `pyright`/`mypy`/`ty` flag the fall-through, no plugin
needed.

## Install

Requires Python **3.14+**.

```sh
uv add returnz              # core — Result / Maybe / @do / batch (zero deps)
uv add returnz-pydantic     # + serialization, parse, TaggedError
uv add returnz-fastapi      # + FastAPI routers (pulls in the two above)
```

Add only the layer you need — `returnz-fastapi` depends on `returnz-pydantic`,
which depends on `returnz`. (`pip install returnz` works too.)

## Three ways to compose

| Shape | Tool | Behaviour |
| --- | --- | --- |
| **Short-circuit** | `@do` / `require` | sequential, bail on the first `Err` (Rust's `?`) |
| **Validate** | `parse` (Pydantic) | accumulate *all* field errors at once |
| **Partition** | `map_batch` | run all independently, keep every outcome — partial success |

**Short-circuit** is the hero example above: `cancel_order` bails on the first
`Err` and the checker knows the full error union.

**Validate** at the boundary — `parse` returns a `Result` instead of raising,
and collects every field error, not just the first:

```python
from pydantic import BaseModel
from returnz import Err, Ok
from returnz_pydantic import parse


class PlaceOrder(BaseModel):
    item: str
    quantity: int


match parse(PlaceOrder, {"item": None, "quantity": "many"}):
    case Ok(command):
        ...
    case Err(error):
        print(error.error_count())  # 2 — both fields, not just the first
```

**Partition** when operations are independent — cancel every order you can,
report the rest, never a whole-batch failure:

```python
from returnz import map_batch


async def cancel(order_id: str) -> Result[str, AlreadyShipped]: ...  # as above, but async


outcome = await map_batch(["o1", "o2", "o3"], cancel, concurrency=8)
outcome.succeeded  # {"o1": "order o1 cancelled", "o3": "order o3 cancelled"}
outcome.failed  # {"o2": AlreadyShipped(order_id="o2")}
outcome.failed_keys  # ["o2"] — the retry set
```

## When to use `Maybe` (and when not to)

**Default to `T | None`.** Python's `Optional` is already a checked sum type —
`if x is not None` narrows exhaustively in `pyright`, `ty`, and plugin-free
`mypy`. `Maybe` adds no type safety over it. The whole ecosystem speaks `None`,
so every `Maybe` at a boundary is a conversion you have to write.

Reach for `Maybe` only when absence must **survive nesting**. `Optional[Optional[T]]`
collapses to `Optional[T]`; `Maybe[T | None]` does not — `Some(None)` and
`Nothing()` stay distinct. Three cases where that distinction is load-bearing:

| Case | Why `None` fails |
| --- | --- |
| **Cache miss vs. cached null** | `cache.get(key)` cannot tell "not cached" from "cached, value is null" — so you re-fetch every hit for legitimately-null values |
| **PATCH / partial update** | "field omitted" vs. "field explicitly `null`" — otherwise a sentinel default or `model_fields_set` introspection |
| **Generic code where `T` may be `None`** | `def first(xs: list[T]) -> T \| None` is wrong for `list[None]`: empty list and `[None]` are indistinguishable. This is the hole `dict.get` has |

```python
from returnz import Maybe, Nothing, Some


def checked_discount(cache: dict[str, int | None], order_id: str) -> Maybe[int | None]:
    return Some(cache[order_id]) if order_id in cache else Nothing()


checked_discount({"o1": None}, "o1")  # Some(value=None) — checked; no discount applies
checked_discount({}, "o1")  # Nothing()        — not checked yet
```

Everything else `Maybe` offers is ergonomics: `map_some` / `and_then` chaining
because Python has no `?.`, and `ok_or` to bridge into `Result` instead of
writing `if x is None: return Err(...)` at each step. Good ergonomics — but not
a reason to convert a codebase that is happily using `None`.

`Maybe` combinators live in `returnz.maybe`, not at the top level; their names
would collide with the `Result` ones.

```python
from returnz.maybe import ok_or, unwrap_or
```

## Packages

| Package | Import | What |
| --- | --- | --- |
| `returnz` | `returnz` | `Result` / `Maybe` / `Reader`, `@do` / `@do_async`, batch combinators. Zero deps. |
| `returnz-pydantic` | `returnz_pydantic` | Tagged-envelope serialization (`RzResult` / `RzMaybe` / `RzBatchResult`), `parse`, `TaggedError`. |
| `returnz-fastapi` | `returnz_fastapi` | `ResultRouter` (typed errors in OpenAPI), `BatchRouter` (HTTP 207), `Err → HTTPException`. |

## Return a `Result`, get a documented endpoint

The same orders domain over HTTP — the errors become `HttpError`s (a Pydantic
`TaggedError` that knows its status), and the return type drives everything:

```python
from typing import Literal

from pydantic import BaseModel
from returnz import Err, Ok, Result
from returnz_fastapi import HttpError, ResultRouter


class Order(BaseModel):
    id: str
    item: str
    shipped: bool = False


class NotFound(HttpError):  # an HttpError carries its HTTP status + tag
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    order_id: str


class AlreadyShipped(HttpError):
    status_code = 409
    tag: Literal["already_shipped"] = "already_shipped"
    order_id: str


_ORDERS = {"1": Order(id="1", item="Widget"), "2": Order(id="2", item="Gadget", shipped=True)}
router = ResultRouter()


@router.post("/orders/{order_id}/ship")
async def ship_order(order_id: str) -> Result[Order, NotFound | AlreadyShipped]:
    order = _ORDERS.get(order_id)
    if order is None:
        return Err(NotFound(order_id=order_id))
    if order.shipped:
        return Err(AlreadyShipped(order_id=order_id))
    shipped = order.model_copy(update={"shipped": True})
    _ORDERS[order_id] = shipped
    return Ok(shipped)
```

On the wire:

```
POST /orders/1/ship → 200 {"id": "1", "item": "Widget", "shipped": true}
POST /orders/2/ship → 409 {"tag": "already_shipped", "order_id": "2"}
```

`ResultRouter` unwraps `Ok` to the value, maps each `Err` to its own status, and
**auto-documents every error in the return-type union in OpenAPI** — `/docs`
shows `200` / `404` / `409` with the `NotFound` and `AlreadyShipped` schemas, no
extra code. A non-`HttpError` in the union fails at registration, not with a 500
at request time.

Batch endpoints keep every outcome — `map_batch` + `BatchRouter` respond HTTP
**207 Multi-Status** (the web analog of AWS `batchItemFailures`), never a
whole-batch 500:

```python
from returnz import BatchResult, map_batch
from returnz_fastapi import BatchRouter


async def delete_order(order_id: str) -> Result[str, NotFound]:
    popped = _ORDERS.pop(order_id, None)
    return Ok(order_id) if popped is not None else Err(NotFound(order_id=order_id))


batch = BatchRouter()


@batch.post("/orders/delete")
async def delete_orders(ids: list[str]) -> BatchResult[str, str, NotFound]:
    return await map_batch(ids, delete_order)
```

```
POST /orders/delete ["1", "99"] → 207
{"succeeded": {"1": "1"}, "failed": {"99": {"tag": "not_found", "order_id": "99"}}}
```

A complete, runnable version is in [`examples/fastapi/`](examples/fastapi/) —
`uv run examples/fastapi/app.py`, then open `/docs`. For returnz in a full
application, see
[`full-stack-fastapi-template-returnz`](https://github.com/tamasbelinszky/full-stack-fastapi-template-returnz)
— FastAPI's official full-stack template converted to `Result`-based handlers,
typed errors documented in every endpoint's responses.

## Claude Code skill

An agent skill ships at [`.claude/skills/returnz/`](.claude/skills/returnz/SKILL.md)
— it teaches Claude Code idiomatic returnz (the compose trio, the routers, and the
anti-patterns to avoid). Copy that directory into your own project's
`.claude/skills/` to use it.

## Develop

```sh
uv sync --all-packages
uv run pyright        # primary correctness gate
uv run mypy packages/core/src packages/pydantic/src packages/fastapi/src
uv run ty check       # fast smoke-check + editor LSP
uv run ruff check . && uv run ruff format --check .
uv run pytest
```

## Releasing

Publishing is automated by [`.github/workflows/publish.yml`](.github/workflows/publish.yml)
via PyPI Trusted Publishing (OIDC — no tokens stored). To cut a release:

1. Create a trusted publisher for each package at
   <https://pypi.org/manage/account/publishing/> — repo `tamasbelinszky/returnz`,
   workflow `publish.yml`, with a **distinct environment per package** (PyPI
   requires the publisher tuple to be unique):
   `returnz` → `pypi`, `returnz-pydantic` → `pypi-pydantic`,
   `returnz-fastapi` → `pypi-fastapi`.
2. Bump the version in each `packages/*/pyproject.toml`; commit.
3. Push a `v*` tag (e.g. `git tag v0.1.0 && git push origin v0.1.0`) — the
   workflow builds and uploads all three packages, each in its own environment.

See `NOTICE` for lineage. MIT licensed.
