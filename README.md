# returnz

`Result`, `Maybe`, and typed error handling for modern Python — a narrowed,
FastAPI-friendly reimagining of [`dry-python/returns`](https://github.com/dry-python/returns).

**The bet:** concrete [PEP 695](https://peps.python.org/pep-0695/) generics + native
type checkers (`pyright`, plugin-free `mypy`, `ty`) + Pydantic at the boundary +
FastAPI for the web. **No higher-kinded-type emulation. No type-checker plugin.**
Python **3.14+**.

```python
from returnz import Ok, Err, Result, do, require


def parse_int(s: str) -> Result[int, str]:
    return Ok(int(s)) if s.lstrip("-").isdigit() else Err(f"not an int: {s}")


@do
def add(a: str, b: str) -> Result[int, str]:
    x = require(parse_int(a))  # the `?` of returnz — unwrap or short-circuit
    y = require(parse_int(b))
    return Ok(x + y)


match add("2", "3"):  # exhaustive — checkers flag a missing case, no plugin
    case Ok(total):
        print(total)  # 5
    case Err(msg):
        print(msg)
```

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


def cached(cache: dict[str, int | None], key: str) -> Maybe[int | None]:
    return Some(cache[key]) if key in cache else Nothing()


cached({"a": None}, "a")  # Some(value=None) — cached, and the value is null
cached({}, "a")  # Nothing()        — not cached
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

```python
from typing import Literal

from pydantic import BaseModel
from returnz import Ok, Err, Result
from returnz_fastapi import ResultRouter, HttpError


class User(BaseModel):
    id: str
    name: str


class BadId(HttpError):  # an HttpError carries its HTTP status + tag
    status_code = 400
    tag: Literal["bad_id"] = "bad_id"
    id: str


class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    id: str


_USERS = {"42": User(id="42", name="Ann")}
router = ResultRouter()


@router.get("/users/{id}")
async def get_user(id: str) -> Result[User, BadId | NotFound]:
    if not id.isdigit():
        return Err(BadId(id=id))
    user = _USERS.get(id)
    return Ok(user) if user is not None else Err(NotFound(id=id))
```

`ResultRouter` unwraps `Ok` to the value (a `200` with `User` here), maps each
`Err` to its own HTTP status (`400` / `404`), **and auto-documents every error in
the return-type union in OpenAPI** — the `BadId` and `NotFound` schemas show up
in `/docs` with no extra code. `BatchRouter` turns a `BatchResult` into HTTP
**207 Multi-Status** (the web analog of AWS `batchItemFailures`): successes and
typed per-item failures in one response, never a whole-batch 500.

A complete, runnable version is in [`examples/fastapi/`](examples/fastapi/) —
`uv run examples/fastapi/app.py`, then open `/docs`.

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
