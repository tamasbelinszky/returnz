# /// script
# requires-python = ">=3.14"
# dependencies = ["returnz-fastapi", "fastapi[standard]"]
# ///
"""A tiny orders API showing off returnz + FastAPI.

Run it (pulls returnz + fastapi from PyPI into an isolated env):

    uv run examples/fastapi/app.py

Then open http://127.0.0.1:8000/docs — notice every typed error (400/404/409)
is documented, derived straight from each handler's `-> Result[...]` type.
"""

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from returnz import BatchResult, Err, Ok, Result, do_async, map_batch, require
from returnz_fastapi import BatchRouter, HttpError, ResultRouter


class Order(BaseModel):
    id: str
    item: str
    shipped: bool = False


# Typed errors — each carries its own HTTP status + tag, and shows up in OpenAPI.
class BadId(HttpError):
    status_code = 400
    tag: Literal["bad_id"] = "bad_id"
    order_id: str


class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    order_id: str


class AlreadyShipped(HttpError):
    status_code = 409
    tag: Literal["already_shipped"] = "already_shipped"
    order_id: str


_ORDERS: dict[str, Order] = {
    "1": Order(id="1", item="Widget"),
    "2": Order(id="2", item="Gadget", shipped=True),
}


# Services return Results — errors are values, never raised.
async def find_order(order_id: str) -> Result[Order, BadId | NotFound]:
    if not order_id.isdigit():
        return Err(BadId(order_id=order_id))
    order = _ORDERS.get(order_id)
    return Ok(order) if order is not None else Err(NotFound(order_id=order_id))


@do_async
async def ship_order(order_id: str) -> Result[Order, BadId | NotFound | AlreadyShipped]:
    order = require(await find_order(order_id))  # `?` — bail on BadId / NotFound
    if order.shipped:
        return Err(AlreadyShipped(order_id=order_id))
    shipped = order.model_copy(update={"shipped": True})
    _ORDERS[order_id] = shipped
    return Ok(shipped)


async def delete_order(order_id: str) -> Result[str, NotFound]:
    popped = _ORDERS.pop(order_id, None)
    return Ok(order_id) if popped is not None else Err(NotFound(order_id=order_id))


# ResultRouter: Ok -> value, Err -> its HTTP status, errors documented in /docs.
orders = ResultRouter(prefix="/orders", tags=["orders"])


@orders.get("/{order_id}", summary="Get an order")
async def get_order(order_id: str) -> Result[Order, BadId | NotFound]:
    return await find_order(order_id)


@orders.post("/{order_id}/ship", summary="Ship an order")
async def ship(order_id: str) -> Result[Order, BadId | NotFound | AlreadyShipped]:
    return await ship_order(order_id)


# BatchRouter: delete many, keep every outcome, respond HTTP 207 Multi-Status.
batch = BatchRouter(prefix="/orders", tags=["orders"])


@batch.post("/delete", summary="Delete orders")
async def delete_orders(ids: list[str]) -> BatchResult[str, str, NotFound]:
    return await map_batch(ids, delete_order)


app = FastAPI(title="returnz orders example")
app.include_router(orders)
app.include_router(batch)


if __name__ == "__main__":
    import uvicorn  # ty: ignore[unresolved-import]  # from fastapi[standard], the script's own dep

    uvicorn.run(app, host="127.0.0.1", port=8000)
