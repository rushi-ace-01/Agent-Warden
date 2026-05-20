"""End-to-end API tests for the admission webhook.

Mocks the guardrails HTTP client so we exercise the full FastAPI handler
without needing a running guardrails-service.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from admission_webhook.app.main import app
from admission_webhook.app.translation import AGENT_LABEL
from admission_webhook.app.types import GuardrailsDecision, GuardrailsScores


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _review_for(
    *, agent_name: str | None, verb: str = "DELETE", resource: str = "persistentvolumeclaims"
) -> dict[str, Any]:
    labels: dict[str, str] = {}
    if agent_name:
        labels[AGENT_LABEL] = agent_name
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "test-uid-1",
            "operation": verb,
            "namespace": "production",
            "resource": {"group": "", "version": "v1", "resource": resource},
            "object": {
                "metadata": {
                    "name": "production-db-backup",
                    "namespace": "production",
                    "labels": labels,
                    "annotations": {
                        "agent-warden.io/max-irreversibility": "4",
                        "agent-warden.io/max-blast-radius": "30",
                    },
                }
            },
        },
    }


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json()["status"] == "ok"


def test_unmanaged_object_allowed_without_consulting_guardrails(client: TestClient) -> None:
    """The webhook should never call guardrails for objects without the agent label."""
    with patch("admission_webhook.app.main._ask_guardrails", new_callable=AsyncMock) as mock:
        response = client.post("/validate", json=_review_for(agent_name=None))

    mock.assert_not_called()
    assert response.status_code == 200
    body = response.json()
    assert body["response"]["allowed"] is True
    assert body["response"]["uid"] == "test-uid-1"


def test_managed_action_consults_guardrails_and_allows(client: TestClient) -> None:
    fake_decision = GuardrailsDecision(
        verdict="allow",
        scores=GuardrailsScores(irreversibility=1, blast_radius=5),
        reasons=[],
    )
    with patch(
        "admission_webhook.app.main._ask_guardrails",
        new_callable=AsyncMock,
        return_value=fake_decision,
    ) as mock:
        response = client.post("/validate", json=_review_for(agent_name="cursor"))

    mock.assert_called_once()
    assert response.json()["response"]["allowed"] is True


def test_managed_action_denial_records_blocked_action(client: TestClient) -> None:
    """A deny verdict should both block the action AND record a BlockedAction CR."""
    fake_decision = GuardrailsDecision(
        verdict="deny",
        scores=GuardrailsScores(
            irreversibility=9, blast_radius=95, colocation_risk=True
        ),
        reasons=["irreversibility 9 exceeds agent limit 4"],
    )
    with patch(
        "admission_webhook.app.main._ask_guardrails",
        new_callable=AsyncMock,
        return_value=fake_decision,
    ), patch(
        "admission_webhook.app.main._record_blocked_action", new_callable=AsyncMock
    ) as record_mock:
        response = client.post("/validate", json=_review_for(agent_name="cursor"))

    body = response.json()
    assert body["response"]["allowed"] is False
    assert body["response"]["status"]["code"] == 403
    record_mock.assert_called_once()
    blocked = record_mock.call_args.args[0]
    assert blocked["kind"] == "BlockedAction"
    assert blocked["spec"]["agentName"] == "cursor"


def test_require_approval_creates_aar_and_denies(client: TestClient) -> None:
    """First time we see require_approval, we create a new Pending AAR and deny."""
    fake_decision = GuardrailsDecision(
        verdict="require_approval",
        scores=GuardrailsScores(irreversibility=5, blast_radius=50),
        reasons=["near the limit"],
    )
    with patch(
        "admission_webhook.app.main._ask_guardrails",
        new_callable=AsyncMock,
        return_value=fake_decision,
    ), patch(
        "admission_webhook.app.main._list_action_requests",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "admission_webhook.app.main._create_action_request", new_callable=AsyncMock
    ) as create_mock:
        response = client.post("/validate", json=_review_for(agent_name="cursor"))

    body = response.json()
    assert body["response"]["allowed"] is False
    assert "AgentActionRequest" in body["response"]["status"]["message"]
    create_mock.assert_called_once()
    aar = create_mock.call_args.args[0]
    assert aar["kind"] == "AgentActionRequest"


def test_require_approval_with_existing_approved_aar_allows(client: TestClient) -> None:
    """A retry after human approval should be let through."""
    from datetime import datetime, timedelta, timezone

    from admission_webhook.app.hashing import action_hash
    from admission_webhook.app.translation import to_guardrails_request

    review = _review_for(agent_name="cursor")
    gr = to_guardrails_request(review["request"])
    assert gr is not None
    h = action_hash(gr)

    fake_decision = GuardrailsDecision(
        verdict="require_approval",
        scores=GuardrailsScores(irreversibility=5, blast_radius=50),
        reasons=["near the limit"],
    )
    approved_aar = {
        "metadata": {"name": "x-1", "namespace": "production"},
        "spec": {
            "actionHash": h,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        },
        "status": {"phase": "Approved", "decidedBy": "alice"},
    }

    with patch(
        "admission_webhook.app.main._ask_guardrails",
        new_callable=AsyncMock,
        return_value=fake_decision,
    ), patch(
        "admission_webhook.app.main._list_action_requests",
        new_callable=AsyncMock,
        return_value=[approved_aar],
    ), patch(
        "admission_webhook.app.main._mark_consumed", new_callable=AsyncMock
    ) as mark_mock:
        response = client.post("/validate", json=review)

    body = response.json()
    assert body["response"]["allowed"] is True
    mark_mock.assert_called_once_with("production", "x-1")


def test_malformed_review_returns_400(client: TestClient) -> None:
    response = client.post("/validate", json={"kind": "NotAdmissionReview"})
    assert response.status_code == 400
