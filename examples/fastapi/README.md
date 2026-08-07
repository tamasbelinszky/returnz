# returnz — FastAPI orders example

A tiny orders API that exercises the whole stack: typed errors documented in
OpenAPI, `@do_async` / `require`, and a partial-success batch as HTTP 207.

## Run

`app.py` is a self-contained [PEP 723](https://peps.python.org/pep-0723/) script —
`uv` pulls `returnz` + `fastapi` from PyPI into an isolated env:

```sh
uv run examples/fastapi/app.py
```

Then open **http://127.0.0.1:8000/docs** — every typed error (`400` / `404` /
`409`) is documented, derived straight from each handler's `-> Result[...]` type.

## Try it

```sh
# 200 — an order
curl -s http://127.0.0.1:8000/orders/1

# 404 — typed not_found (Err serialized as data)
curl -s http://127.0.0.1:8000/orders/999

# 400 — typed bad_id (non-numeric id)
curl -s http://127.0.0.1:8000/orders/abc

# 200 — ship it; ship an already-shipped order -> 409 already_shipped
curl -sX POST http://127.0.0.1:8000/orders/1/ship
curl -sX POST http://127.0.0.1:8000/orders/2/ship

# 207 Multi-Status — delete many, keep every outcome
curl -sX POST http://127.0.0.1:8000/orders/delete \
  -H 'content-type: application/json' -d '["1", "999"]'
# -> {"succeeded": {"1": "1"}, "failed": {"999": {"tag": "not_found", "id": "999"}}}
```

## What each piece shows

- **`ResultRouter`** — `get_order` / `post_ship` return a `Result`; `Ok` becomes
  the `200` body, each `Err` becomes its own HTTP status, and the `BadId` /
  `NotFound` / `AlreadyShipped` schemas are auto-documented in `/docs`.
- **`@do_async` + `require`** — `ship_order` reads like straight-line code and
  bails on the first error.
- **`BatchRouter` + `map_batch`** — `delete_orders` runs every delete and reports
  successes *and* typed failures in one `207` response (never a whole-batch 500).
- **`HttpError`** — errors are plain, matchable, serializable data with a status.
