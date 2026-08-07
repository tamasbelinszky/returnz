# pyright: basic
# ^ Starlette's TestClient + httpx aren't cleanly typed under pyright *strict*
#   (ty and mypy handle them fine). Production returnz_fastapi source stays strict.
"""ResultRouter: return a Result, get a correct + fully-documented endpoint.

Drives the router through TestClient (behaviour) and inspects app.openapi()
(typed errors documented out of the box).
"""

from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from returnz import Err, Ok, Result
from returnz_fastapi import HttpError, ResultRouter


class NotFound(HttpError):
    status_code = 404
    tag: Literal["not_found"] = "not_found"
    id: str


class RateLimited(HttpError):
    status_code = 429
    tag: Literal["rate_limited"] = "rate_limited"
    retry_after: int


router = ResultRouter()
_DB = {"42": "90210"}


@router.get("/zip/{uid}")
async def get_zip(uid: str) -> Result[str, NotFound | RateLimited]:
    if uid == "slow":
        return Err(RateLimited(retry_after=5))
    zip_code = _DB.get(uid)
    return Ok(zip_code) if zip_code is not None else Err(NotFound(id=uid))


app = FastAPI()
app.include_router(router)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestResultRouterBehaviour:
    def test_ok_unwraps_to_value(self, client: TestClient) -> None:
        response = client.get("/zip/42")

        assert response.status_code == 200
        assert response.json() == "90210"

    def test_not_found_maps_to_404(self, client: TestClient) -> None:
        response = client.get("/zip/99")

        assert response.status_code == 404
        assert response.json() == {"detail": {"tag": "not_found", "id": "99"}}

    def test_rate_limited_maps_to_429(self, client: TestClient) -> None:
        response = client.get("/zip/slow")

        assert response.status_code == 429
        assert response.json() == {"detail": {"tag": "rate_limited", "retry_after": 5}}


class TestOpenApiErrorDocs:
    def test_typed_errors_documented_out_of_the_box(self) -> None:
        responses = app.openapi()["paths"]["/zip/{uid}"]["get"]["responses"]

        assert sorted(responses.keys()) == ["200", "404", "422", "429"]
        assert responses["200"]["content"]["application/json"]["schema"]["type"] == "string"
        assert responses["404"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/NotFound"
        )
        assert responses["429"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/RateLimited"
        )
