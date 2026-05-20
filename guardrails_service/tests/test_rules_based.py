"""Unit tests for RulesBasedEngine - each rule exercised in isolation."""

import pytest

from guardrails_service.app.policy.rules_based import RulesBasedEngine
from guardrails_service.app.types import ActionRequest, Verdict
from guardrails_service.tests.fixtures import (
    BORDERLINE_DEPLOY_PATCH,
    POCKETOS_DB_DELETION,
    SAFE_LOG_READ,
)


@pytest.fixture
def engine() -> RulesBasedEngine:
    return RulesBasedEngine()


class TestClassify:
    @pytest.mark.parametrize(
        "verb, expected",
        [
            ("get", 0),
            ("list", 0),
            ("create", 3),
            ("patch", 5),
            ("delete", 9),
            ("deletecollection", 10),
        ],
    )
    def test_known_verbs_have_expected_scores(
        self, engine: RulesBasedEngine, verb: str, expected: int
    ) -> None:
        request = ActionRequest(
            verb=verb,
            resource="pod",
            target="x",
            agent_name="a",
            agent_max_irreversibility=10,
            agent_max_blast_radius=100,
        )
        assert engine.classify(request) == expected

    def test_unknown_verb_returns_middle_score(self, engine: RulesBasedEngine) -> None:
        request = ActionRequest(
            verb="frobnicate",
            resource="pod",
            target="x",
            agent_name="a",
            agent_max_irreversibility=10,
            agent_max_blast_radius=100,
        )
        assert engine.classify(request) == 5


class TestBlastRadius:
    def test_pvc_in_production_scores_higher_than_in_dev(
        self, engine: RulesBasedEngine
    ) -> None:
        prod = ActionRequest(
            verb="delete",
            resource="pvc",
            target="x",
            namespace="production",
            agent_name="a",
            agent_max_irreversibility=10,
            agent_max_blast_radius=100,
        )
        dev = prod.model_copy(update={"namespace": "dev"})
        assert engine.score_blast_radius(prod) > engine.score_blast_radius(dev)

    def test_unknown_resource_gets_default(self, engine: RulesBasedEngine) -> None:
        request = ActionRequest(
            verb="delete",
            resource="widget",
            target="x",
            agent_name="a",
            agent_max_irreversibility=10,
            agent_max_blast_radius=100,
        )
        assert engine.score_blast_radius(request) == 20


class TestColocation:
    def test_backup_in_prod_namespace_is_colocated(self, engine: RulesBasedEngine) -> None:
        assert engine.scan_colocation(POCKETOS_DB_DELETION) is True

    def test_pod_in_staging_is_not_colocated(self, engine: RulesBasedEngine) -> None:
        assert engine.scan_colocation(SAFE_LOG_READ) is False


class TestDecide:
    def test_pocketos_incident_is_denied(self, engine: RulesBasedEngine) -> None:
        decision = engine.decide(POCKETOS_DB_DELETION)
        assert decision.verdict == Verdict.DENY
        assert decision.scores.irreversibility == 9
        assert decision.scores.colocation_risk is True
        assert any("colocates" in r for r in decision.reasons)

    def test_safe_log_read_is_allowed(self, engine: RulesBasedEngine) -> None:
        decision = engine.decide(SAFE_LOG_READ)
        assert decision.verdict == Verdict.ALLOW
        assert decision.reasons == []

    def test_borderline_action_requires_approval(self, engine: RulesBasedEngine) -> None:
        decision = engine.decide(BORDERLINE_DEPLOY_PATCH)
        assert decision.verdict == Verdict.REQUIRE_APPROVAL
