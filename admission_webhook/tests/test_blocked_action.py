"""Tests for BlockedAction CR construction."""

from datetime import datetime, timezone

import pytest

from admission_webhook.app.blocked_action import build_blocked_action
from admission_webhook.app.types import (
    GuardrailsDecision,
    GuardrailsRequest,
    GuardrailsScores,
)


@pytest.fixture
def request_obj() -> GuardrailsRequest:
    return GuardrailsRequest(
        verb="delete",
        resource="persistentvolumeclaim",
        target="production-db-backup",
        namespace="production",
        agent_name="cursor-agent",
        agent_max_irreversibility=4,
        agent_max_blast_radius=30,
    )


@pytest.fixture
def decision() -> GuardrailsDecision:
    return GuardrailsDecision(
        verdict="deny",
        scores=GuardrailsScores(
            irreversibility=9,
            blast_radius=95,
            colocation_risk=True,
            over_permissioned=True,
        ),
        reasons=[
            "irreversibility 9 exceeds agent limit 4",
            "target colocates with sensitive data",
        ],
    )


def test_metadata_carries_agent_label(
    request_obj: GuardrailsRequest, decision: GuardrailsDecision
) -> None:
    ba = build_blocked_action(request_obj, decision, request_uid="705ab4f5-6393-11e8")
    labels = ba["metadata"]["labels"]
    assert labels["agent-warden.io/scoped-agent"] == "cursor-agent"
    assert labels["app.kubernetes.io/name"] == "agent-warden"


def test_namespace_falls_back_to_default(decision: GuardrailsDecision) -> None:
    req = GuardrailsRequest(
        verb="delete",
        resource="pvc",
        target="x",
        namespace=None,
        agent_name="a",
        agent_max_irreversibility=0,
        agent_max_blast_radius=0,
    )
    ba = build_blocked_action(req, decision, request_uid="u")
    assert ba["metadata"]["namespace"] == "default"
    assert ba["spec"]["namespace"] == "default"


def test_name_is_dns_safe(decision: GuardrailsDecision) -> None:
    """k8s requires names to match DNS-1123: lowercase, alphanumeric, hyphens only."""
    req = GuardrailsRequest(
        verb="DELETE",
        resource="pvc",
        target="x",
        agent_name="Some/Agent With_Spaces!",
        agent_max_irreversibility=0,
        agent_max_blast_radius=0,
    )
    ba = build_blocked_action(req, decision, request_uid="abc-def")
    name = ba["metadata"]["name"]
    assert name == name.lower()
    assert all(c.isalnum() or c == "-" for c in name)
    assert not name.startswith("-")
    assert not name.endswith("-")
    assert len(name) <= 253


def test_scores_serialized_in_camelcase(
    request_obj: GuardrailsRequest, decision: GuardrailsDecision
) -> None:
    """k8s convention is camelCase in spec fields, even though Python uses snake_case."""
    ba = build_blocked_action(request_obj, decision, request_uid="u")
    scores = ba["spec"]["scores"]
    assert scores["irreversibility"] == 9
    assert scores["blastRadius"] == 95
    assert scores["colocationRisk"] is True
    assert scores["overPermissioned"] is True


def test_blocked_at_uses_provided_time(
    request_obj: GuardrailsRequest, decision: GuardrailsDecision
) -> None:
    """Tests pass in `now` to make assertions deterministic."""
    fixed = datetime(2026, 4, 15, 12, 0, 0, tzinfo=timezone.utc)
    ba = build_blocked_action(request_obj, decision, request_uid="u", now=fixed)
    assert ba["spec"]["blockedAt"].startswith("2026-04-15T12:00:00")


def test_reasons_are_preserved(
    request_obj: GuardrailsRequest, decision: GuardrailsDecision
) -> None:
    ba = build_blocked_action(request_obj, decision, request_uid="u")
    assert ba["spec"]["reasons"] == decision.reasons


def test_request_uid_recorded(
    request_obj: GuardrailsRequest, decision: GuardrailsDecision
) -> None:
    ba = build_blocked_action(request_obj, decision, request_uid="705ab4f5-6393-11e8")
    assert ba["spec"]["requestUid"] == "705ab4f5-6393-11e8"
