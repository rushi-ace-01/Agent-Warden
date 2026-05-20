"""API tests - exercise FastAPI endpoints via TestClient.

These tests are intentionally light on policy assertions (that's
test_rules_based's job) and heavy on HTTP-shape assertions: status
codes, response schemas, error handling.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from guardrails_service.app.main import app
from guardrails_service.tests.fixtures import POCKETOS_DB_DELETION, SAFE_LOG_READ


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_decide_pocketos_returns_deny(client: TestClient) -> None:
    response = client.post("/decide", json=POCKETOS_DB_DELETION.model_dump())
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "deny"
    assert body["scores"]["irreversibility"] == 9
    assert len(body["reasons"]) >= 1


def test_decide_safe_action_returns_allow(client: TestClient) -> None:
    response = client.post("/decide", json=SAFE_LOG_READ.model_dump())
    assert response.status_code == 200
    assert response.json()["verdict"] == "allow"


@pytest.mark.parametrize(
    "endpoint, response_key",
    [
        ("/classify", "score"),
        ("/score-blast-radius", "score"),
        ("/scan-colocation", "flag"),
        ("/audit-credential-scope", "flag"),
    ],
)
def test_atomic_endpoints_return_expected_shape(
    client: TestClient, endpoint: str, response_key: str
) -> None:
    response = client.post(endpoint, json=POCKETOS_DB_DELETION.model_dump())
    assert response.status_code == 200
    assert response_key in response.json()


def test_decide_rejects_malformed_request(client: TestClient) -> None:
    bad: dict[str, Any] = {"verb": "delete"}
    response = client.post("/decide", json=bad)
    assert response.status_code == 422


def test_decide_rejects_out_of_range_limits(client: TestClient) -> None:
    payload = POCKETOS_DB_DELETION.model_dump()
    payload["agent_max_irreversibility"] = 15
    response = client.post("/decide", json=payload)
    assert response.status_code == 422
