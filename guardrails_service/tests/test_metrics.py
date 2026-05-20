"""Tests for Prometheus metrics emission."""

from fastapi.testclient import TestClient

from guardrails_service.app.main import app
from guardrails_service.tests.fixtures import POCKETOS_DB_DELETION, SAFE_LOG_READ


def test_metrics_endpoint_returns_prometheus_format() -> None:
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "agent_warden_decisions_total" in body
    assert "agent_warden_decision_latency_seconds" in body


def test_decide_increments_verdict_counter() -> None:
    client = TestClient(app)
    before = client.get("/metrics").text

    client.post("/decide", json=POCKETOS_DB_DELETION.model_dump())
    client.post("/decide", json=SAFE_LOG_READ.model_dump())

    after = client.get("/metrics").text
    assert 'agent_warden_decisions_total{verdict="deny"}' in after
    assert 'agent_warden_decisions_total{verdict="allow"}' in after
    # The counter must have moved
    assert before != after


def test_decide_records_score_histograms() -> None:
    client = TestClient(app)
    client.post("/decide", json=POCKETOS_DB_DELETION.model_dump())
    body = client.get("/metrics").text
    assert "agent_warden_irreversibility_score_bucket" in body
    assert "agent_warden_blast_radius_score_bucket" in body
