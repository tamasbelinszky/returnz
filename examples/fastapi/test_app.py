# pyright: basic
# ^ Starlette's TestClient + httpx aren't cleanly typed under pyright *strict*
#   (ty and mypy handle them fine).
"""The runnable example app, pinned end to end: wire bodies and OpenAPI docs.

These are the same bodies the README quotes — if a snippet there drifts from
reality, this file fails.
"""

import pytest
from app import _ORDERS, app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def restore_orders():
    snapshot = dict(_ORDERS)
    yield
    _ORDERS.clear()
    _ORDERS.update(snapshot)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestGetOrder:
    def test_ok_returns_the_order(self, client: TestClient) -> None:
        response = client.get("/orders/1")

        assert response.status_code == 200
        assert response.json() == {"id": "1", "item": "Widget", "shipped": False}

    def test_non_numeric_id_maps_to_400(self, client: TestClient) -> None:
        response = client.get("/orders/abc")

        assert response.status_code == 400
        assert response.json() == {"tag": "bad_id", "order_id": "abc"}

    def test_missing_order_maps_to_404(self, client: TestClient) -> None:
        response = client.get("/orders/99")

        assert response.status_code == 404
        assert response.json() == {"tag": "not_found", "order_id": "99"}


class TestShipOrder:
    def test_ships_a_pending_order(self, client: TestClient) -> None:
        response = client.post("/orders/1/ship")

        assert response.status_code == 200
        assert response.json() == {"id": "1", "item": "Widget", "shipped": True}

    def test_already_shipped_maps_to_409(self, client: TestClient) -> None:
        response = client.post("/orders/2/ship")

        assert response.status_code == 409
        assert response.json() == {"tag": "already_shipped", "order_id": "2"}


class TestDeleteOrders:
    def test_partial_success_is_207_multi_status(self, client: TestClient) -> None:
        response = client.post("/orders/delete", json=["1", "99"])

        assert response.status_code == 207
        assert response.json() == {
            "succeeded": {"1": "1"},
            "failed": {"99": {"tag": "not_found", "order_id": "99"}},
        }


class TestOpenApiDocs:
    def test_ship_documents_every_typed_error(self) -> None:
        responses = app.openapi()["paths"]["/orders/{order_id}/ship"]["post"]["responses"]

        assert sorted(responses) == ["200", "400", "404", "409", "422"]

    def test_delete_documents_cleanly_named_batch_envelope(self) -> None:
        responses = app.openapi()["paths"]["/orders/delete"]["post"]["responses"]

        assert responses["207"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/BatchResult_str_str_NotFound"
        }
