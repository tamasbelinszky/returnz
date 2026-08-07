# pyright: basic
# ^ Starlette's TestClient + httpx aren't cleanly typed under pyright *strict*
#   (ty and mypy handle them fine). Production returnz_fastapi source stays strict.
"""BatchRoute: return a BatchResult, get HTTP 207 Multi-Status + a documented envelope.

The web analog of AWS batchItemFailures — successes and typed failures in one
response, never a whole-batch 500.
"""

from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from returnz import BatchResult, Err, Ok, Result, map_batch
from returnz_fastapi import BatchRouter
from returnz_pydantic import TaggedError


class DeleteError(TaggedError):
    tag: Literal["delete_failed"] = "delete_failed"
    status: int


async def _delete(order_id: str) -> Result[str, DeleteError]:
    return Ok(order_id) if order_id != "bad" else Err(DeleteError(status=503))


router = BatchRouter()


@router.post("/orders/delete")
async def delete_orders(ids: list[str]) -> BatchResult[str, str, DeleteError]:
    return await map_batch(ids, _delete, concurrency=4)


app = FastAPI()
app.include_router(router)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestBatchRoute:
    def test_partial_success_is_207_multi_status(self, client: TestClient) -> None:
        response = client.post("/orders/delete", json=["a", "bad", "c"])

        assert response.status_code == 207
        assert response.json() == {
            "succeeded": {"a": "a", "c": "c"},
            "failed": {"bad": {"tag": "delete_failed", "status": 503}},
        }


class TestBatchRouteDocs:
    def test_207_is_documented(self) -> None:
        responses = app.openapi()["paths"]["/orders/delete"]["post"]["responses"]

        assert "207" in responses
