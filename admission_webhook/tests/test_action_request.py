"""Tests for action hashing and AgentActionRequest building."""

from datetime import datetime, timezone

from admission_webhook.app.action_request import build_action_request
from admission_webhook.app.hashing import action_hash
from admission_webhook.app.types import (
    GuardrailsDecision,
    GuardrailsRequest,
    GuardrailsScores,
)


def _request(**overrides) -> GuardrailsRequest:
    defaults = dict(
        verb="delete",
        resource="persistentvolumeclaim",
        target="production-db",
        namespace="production",
        agent_name="cursor",
        agent_max_irreversibility=4,
        agent_max_blast_radius=30,
    )
    defaults.update(overrides)
    return GuardrailsRequest(**defaults)


class TestActionHash:
    def test_is_deterministic(self) -> None:
        a = action_hash(_request())
        b = action_hash(_request())
        assert a == b

    def test_is_64_hex_chars(self) -> None:
        h = action_hash(_request())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_changes_with_verb(self) -> None:
        a = action_hash(_request(verb="delete"))
        b = action_hash(_request(verb="patch"))
        assert a != b

    def test_changes_with_target(self) -> None:
        a = action_hash(_request(target="x"))
        b = action_hash(_request(target="y"))
        assert a != b

    def test_changes_with_namespace(self) -> None:
        a = action_hash(_request(namespace="production"))
        b = action_hash(_request(namespace="staging"))
        assert a != b

    def test_verb_case_insensitive(self) -> None:
        """An agent retrying with DELETE vs delete should map to the same hash."""
        a = action_hash(_request(verb="DELETE"))
        b = action_hash(_request(verb="delete"))
        assert a == b

    def test_does_not_change_with_limits(self) -> None:
        """An admin tweaking the agent's limits shouldn't invalidate an approval."""
        a = action_hash(_request(agent_max_irreversibility=4))
        b = action_hash(_request(agent_max_irreversibility=5))
        assert a == b


class TestBuildActionRequest:
    def _decision(self) -> GuardrailsDecision:
        return GuardrailsDecision(
            verdict="require_approval",
            scores=GuardrailsScores(irreversibility=5, blast_radius=50),
            reasons=["near the limit"],
        )

    def test_records_action_hash_in_spec(self) -> None:
        req = _request()
        aar = build_action_request(req, self._decision())
        assert aar["spec"]["actionHash"] == action_hash(req)

    def test_carries_agent_label(self) -> None:
        aar = build_action_request(_request(), self._decision())
        assert aar["metadata"]["labels"]["agent-warden.io/scoped-agent"] == "cursor"

    def test_expires_at_is_after_requested_at(self) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        aar = build_action_request(_request(), self._decision(), window_minutes=15, now=now)
        assert aar["spec"]["requestedAt"] < aar["spec"]["expiresAt"]
        assert aar["spec"]["expiresAt"].startswith("2026-05-19T12:15:00")

    def test_name_includes_hash_prefix_for_uniqueness(self) -> None:
        aar = build_action_request(_request(), self._decision())
        name = aar["metadata"]["name"]
        h = action_hash(_request())
        assert h[:12] in name

    def test_action_section_carries_full_action_details(self) -> None:
        aar = build_action_request(_request(), self._decision())
        action = aar["spec"]["action"]
        assert action["verb"] == "delete"
        assert action["resource"] == "persistentvolumeclaim"
        assert action["target"] == "production-db"
        assert action["namespace"] == "production"

    def test_namespace_falls_back_to_default(self) -> None:
        req = _request(namespace=None)
        aar = build_action_request(req, self._decision())
        assert aar["metadata"]["namespace"] == "default"
        assert aar["spec"]["action"]["namespace"] == "default"
