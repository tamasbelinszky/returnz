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


match add("2", "3"):        # exhaustive — checkers flag a missing case, no plugin
    case Ok(total):
        print(total)        # 5
    case Err(msg):
        print(msg)
```

## Three ways to compose

| Shape | Tool | Behaviour |
| --- | --- | --- |
| **Short-circuit** | `@do` / `require` | sequential, bail on the first `Err` (Rust's `?`) |
| **Validate** | `parse` (Pydantic) | accumulate *all* field errors at once |
| **Partition** | `map_batch` | run all independently, keep every outcome — partial success |

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


class BadId(HttpError):        # an HttpError carries its HTTP status + tag
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

See `NOTICE` for lineage. MIT licensed.
