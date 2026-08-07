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


match add("2", "3"):
    case Ok(total):
        ...  # exhaustive; verified by pyright/mypy with no plugin
    case Err(msg):
        ...
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
from returnz_fastapi import ResultRouter, HttpError

router = ResultRouter()


@router.get("/users/{id}")
async def get_user(
    id: str,
) -> Result[
    User, NotFound | RateLimited
]: ...  # Ok → 200 User;  Err → its HTTP status;  errors documented in /docs
```

`ResultRouter` unwraps `Ok` to `T`, maps `Err` to the right HTTP status, **and
auto-documents each typed error in OpenAPI** — schemas derived from the return
type. `BatchRouter` turns a `BatchResult` into HTTP **207 Multi-Status** (the web
analog of AWS `batchItemFailures`): successes and typed per-item failures in one
response, never a whole-batch 500.

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
