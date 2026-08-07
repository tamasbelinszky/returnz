# returnz

`Result`, `Maybe`, and `Reader` for modern Python — a narrowed, FastAPI-friendly
take on [`dry-python/returns`](https://github.com/dry-python/returns).

**The bet:** concrete [PEP 695](https://peps.python.org/pep-0695/) generics + native
type checkers (`ty`, `pyright`, plugin-free `mypy`) + Pydantic at the boundary +
FastAPI `Depends` for DI. No higher-kinded-type emulation. **No type-checker plugin.**

## Packages

| Package | Import | What |
| --- | --- | --- |
| `returnz` | `returnz` | Core `Result` / `Maybe` / `Reader` + `@do` notation. Zero runtime deps. |
| `returnz-fastapi` | `returnz_fastapi` | `Err -> HTTPException`, Results on the wire, Pydantic settings as deps. |

## Status

Early scaffold (P0). Core types land in P1. Python **3.14+**.

## Develop

```sh
uv sync --all-packages
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pyright
uv run mypy packages/core/src packages/fastapi/src
uv run pytest
```

See `NOTICE` for lineage.
