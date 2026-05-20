"""Tests for the AdmissionReview ↔ GuardrailsRequest translation layer."""

from typing import Any

import pytest

from admission_webhook.app.translation import (
    AGENT_LABEL,
    BLAST_RADIUS_ANNOTATION,
    IRREVERSIBILITY_ANNOTATION,
    TranslationError,
    build_admission_response,
    extract_request,
    to_guardrails_request,
)
from admission_webhook.app.types import (
    GuardrailsDecision,
    GuardrailsScores,
)


def _agent_managed_pvc_review(
    *,
    operation: str = "DELETE",
    name: str = "production-db-backup",
    namespace: str = "production",
    agent_name: str = "cursor-agent",
    max_irr: str | None = "4",
    max_blast: str | None = "30",
) -> dict[str, Any]:
    """Build a realistic AdmissionReview for tests."""
    annotations: dict[str, str] = {}
    if max_irr is not None:
        annotations[IRREVERSIBILITY_ANNOTATION] = max_irr
    if max_blast is not None:
        annotations[BLAST_RADIUS_ANNOTATION] = max_blast
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "705ab4f5-6393-11e8-b7cc-42010a800002",
            "operation": operation,
            "namespace": namespace,
            "resource": {
                "group": "",
                "version": "v1",
                "resource": "persistentvolumeclaims",
            },
            "object": {
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "labels": {AGENT_LABEL: agent_name},
                    "annotations": annotations,
                }
            },
        },
    }


class TestExtractRequest:
    def test_returns_uid_and_request(self) -> None:
        review = _agent_managed_pvc_review()
        uid, req = extract_request(review)
        assert uid == "705ab4f5-6393-11e8-b7cc-42010a800002"
        assert req["operation"] == "DELETE"

    def test_rejects_wrong_kind(self) -> None:
        review = _agent_managed_pvc_review()
        review["kind"] = "NotAdmissionReview"
        with pytest.raises(TranslationError, match="AdmissionReview"):
            extract_request(review)

    def test_rejects_missing_request(self) -> None:
        with pytest.raises(TranslationError, match="request"):
            extract_request({"kind": "AdmissionReview"})

    def test_rejects_missing_uid(self) -> None:
        review = _agent_managed_pvc_review()
        review["request"]["uid"] = ""
        with pytest.raises(TranslationError, match="uid"):
            extract_request(review)


class TestToGuardrailsRequest:
    def test_unmanaged_object_returns_none(self) -> None:
        review = _agent_managed_pvc_review()
        review["request"]["object"]["metadata"]["labels"] = {}
        result = to_guardrails_request(review["request"])
        assert result is None

    def test_managed_object_produces_request(self) -> None:
        review = _agent_managed_pvc_review()
        gr = to_guardrails_request(review["request"])
        assert gr is not None
        assert gr.verb == "delete"
        assert gr.resource == "persistentvolumeclaim"
        assert gr.target == "production-db-backup"
        assert gr.namespace == "production"
        assert gr.agent_name == "cursor-agent"
        assert gr.agent_max_irreversibility == 4
        assert gr.agent_max_blast_radius == 30

    def test_defaults_zero_when_annotations_missing(self) -> None:
        review = _agent_managed_pvc_review(max_irr=None, max_blast=None)
        gr = to_guardrails_request(review["request"])
        assert gr is not None
        assert gr.agent_max_irreversibility == 0
        assert gr.agent_max_blast_radius == 0

    def test_rejects_non_integer_annotation(self) -> None:
        review = _agent_managed_pvc_review(max_irr="not-a-number")
        with pytest.raises(TranslationError, match="not an integer"):
            to_guardrails_request(review["request"])

    def test_rejects_missing_operation(self) -> None:
        review = _agent_managed_pvc_review()
        review["request"]["operation"] = ""
        with pytest.raises(TranslationError, match="operation"):
            to_guardrails_request(review["request"])

    def test_falls_back_to_oldobject_for_delete(self) -> None:
        """DELETE requests carry the object under 'oldObject', not 'object'."""
        review = _agent_managed_pvc_review()
        review["request"]["oldObject"] = review["request"].pop("object")
        gr = to_guardrails_request(review["request"])
        assert gr is not None
        assert gr.agent_name == "cursor-agent"


class TestBuildAdmissionResponse:
    @pytest.fixture
    def allow_decision(self) -> GuardrailsDecision:
        return GuardrailsDecision(
            verdict="allow",
            scores=GuardrailsScores(irreversibility=2, blast_radius=10),
            reasons=[],
        )

    @pytest.fixture
    def deny_decision(self) -> GuardrailsDecision:
        return GuardrailsDecision(
            verdict="deny",
            scores=GuardrailsScores(
                irreversibility=9, blast_radius=95, colocation_risk=True
            ),
            reasons=["irreversibility exceeds limit", "colocates with sensitive data"],
        )

    def test_none_decision_means_allow(self) -> None:
        resp = build_admission_response("u-1", None)
        assert resp["response"]["allowed"] is True
        assert resp["response"]["uid"] == "u-1"
        assert resp["kind"] == "AdmissionReview"

    def test_allow_decision_returns_allowed(self, allow_decision: GuardrailsDecision) -> None:
        resp = build_admission_response("u-1", allow_decision)
        assert resp["response"]["allowed"] is True

    def test_deny_decision_returns_not_allowed(self, deny_decision: GuardrailsDecision) -> None:
        resp = build_admission_response("u-2", deny_decision)
        r = resp["response"]
        assert r["allowed"] is False
        assert r["status"]["code"] == 403
        msg = r["status"]["message"]
        assert "agent-warden" in msg
        assert "irreversibility" in msg
        assert "colocates" in msg

    def test_require_approval_returns_not_allowed_with_distinct_message(self) -> None:
        decision = GuardrailsDecision(
            verdict="require_approval",
            scores=GuardrailsScores(irreversibility=5, blast_radius=50),
            reasons=["near the limit"],
        )
        resp = build_admission_response("u-3", decision)
        assert resp["response"]["allowed"] is False
        assert "human approval" in resp["response"]["status"]["message"]
