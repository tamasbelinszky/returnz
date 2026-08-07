# pyright: basic
# ^ Starlette's TestClient + httpx aren't cleanly typed under pyright *strict*
#   (ty and mypy handle them fine). The production returnz_fastapi source stays
#   strict; only this end-to-end test file, which drives the third-party client,
#   is relaxed.
"""End-to-end: fetch -> @do_async -> require -> unwrap_or_raise -> Err->HTTPException.

The app below is the runnable example (mirrored in the package README). The
tests drive it through FastAPI's TestClient to prove the whole stack.
"""

from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from returnz import Err, Ok, Result, do_async, require
from returnz_fastapi import HttpError, unwrap_or_raise


class User(BaseModel):
    id: str
    name: str
    zip: str


class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    id: str


_DB = {"42": User(id="42", name="Ann", zip="90210")}


async def fetch_user(user_id: str) -> Result[User, NotFound]:
    user = _DB.get(user_id)
    return Ok(user) if user is not None else Err(NotFound(id=user_id))


@do_async
async def zip_of(user_id: str) -> Result[str, NotFound]:
    user = require(await fetch_user(user_id))
    return Ok(user.zip)


app = FastAPI()


@app.get("/users/{user_id}/zip")
async def get_zip(user_id: str) -> str:
    return unwrap_or_raise(await zip_of(user_id))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestGetZip:
    def test_ok_returns_value(self, client: TestClient) -> None:
        response = client.get("/users/42/zip")

        assert response.status_code == 200
        assert response.json() == "90210"

    def test_err_becomes_http_exception_by_tag(self, client: TestClient) -> None:
        response = client.get("/users/99/zip")

        assert response.status_code == 404
        assert response.json() == {"detail": {"tag": "not_found", "id": "99"}}
