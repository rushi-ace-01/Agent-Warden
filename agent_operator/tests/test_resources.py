"""Tests for the resource builders.

These are pure functions, so we can exhaustively assert on the shape of
every resource without needing a cluster or even importing kopf.
"""

from typing import Any

import pytest

from agent_operator.scoped_agent.resources import (
    ANNOTATION_MANAGED,
    LABEL_AGENT,
    LABEL_NAME,
    build_job,
    build_network_policy,
    build_role,
    build_role_binding,
    build_service_account,
)


AGENT_NAME = "log-triage"
AGENT_UID = "abc-123-uid"
NAMESPACE = "demo"


@pytest.fixture
def spec() -> dict[str, Any]:
    return {
        "task": "summarize errors from /var/log",
        "image": "ghcr.io/example/log-triage:1.0",
        "maxIrreversibility": 4,
        "maxBlastRadius": 30,
        "allowedTools": ["slack"],
        "allowedEgressHosts": ["hooks.slack.com"],
        "timeoutSeconds": 300,
        "ttlSecondsAfterFinished": 600,
    }


class TestCommonMetadata:
    """Properties that must hold for every resource we create."""

    @pytest.fixture
    def all_resources(self, spec: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            build_service_account(AGENT_NAME, AGENT_UID, NAMESPACE),
            build_role(AGENT_NAME, AGENT_UID, NAMESPACE),
            build_role_binding(AGENT_NAME, AGENT_UID, NAMESPACE),
            build_network_policy(AGENT_NAME, AGENT_UID, NAMESPACE, []),
            build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec),
        ]

    def test_every_resource_is_named_consistently(
        self, all_resources: list[dict[str, Any]]
    ) -> None:
        for r in all_resources:
            assert r["metadata"]["name"] == f"{AGENT_NAME}-warden", r["kind"]

    def test_every_resource_lives_in_the_target_namespace(
        self, all_resources: list[dict[str, Any]]
    ) -> None:
        for r in all_resources:
            assert r["metadata"]["namespace"] == NAMESPACE, r["kind"]

    def test_every_resource_has_owner_reference_to_scoped_agent(
        self, all_resources: list[dict[str, Any]]
    ) -> None:
        for r in all_resources:
            refs = r["metadata"]["ownerReferences"]
            assert len(refs) == 1, r["kind"]
            ref = refs[0]
            assert ref["kind"] == "ScopedAgent"
            assert ref["name"] == AGENT_NAME
            assert ref["uid"] == AGENT_UID
            assert ref["controller"] is True
            assert ref["blockOwnerDeletion"] is True

    def test_every_resource_carries_identifying_labels(
        self, all_resources: list[dict[str, Any]]
    ) -> None:
        for r in all_resources:
            labels = r["metadata"]["labels"]
            assert labels[LABEL_NAME] == "agent-warden"
            assert labels[LABEL_AGENT] == AGENT_NAME

    def test_every_resource_is_marked_managed(
        self, all_resources: list[dict[str, Any]]
    ) -> None:
        for r in all_resources:
            assert r["metadata"]["annotations"][ANNOTATION_MANAGED] == "true"


class TestRole:
    def test_only_grants_self_read_on_scopedagent(self) -> None:
        role = build_role(AGENT_NAME, AGENT_UID, NAMESPACE)
        assert len(role["rules"]) == 1
        rule = role["rules"][0]
        assert rule["apiGroups"] == ["agent-warden.io"]
        assert rule["resources"] == ["scopedagents"]
        assert rule["resourceNames"] == [AGENT_NAME]
        assert set(rule["verbs"]) == {"get", "watch"}

    def test_grants_no_secrets_pods_or_pvcs(self) -> None:
        """Defense-in-depth: even if the Role drifts, dangerous verbs aren't there."""
        role = build_role(AGENT_NAME, AGENT_UID, NAMESPACE)
        for rule in role["rules"]:
            assert "secrets" not in rule.get("resources", [])
            assert "pods" not in rule.get("resources", [])
            assert "persistentvolumeclaims" not in rule.get("resources", [])


class TestRoleBinding:
    def test_binds_role_to_service_account(self) -> None:
        rb = build_role_binding(AGENT_NAME, AGENT_UID, NAMESPACE)
        assert rb["roleRef"]["kind"] == "Role"
        assert rb["roleRef"]["name"] == f"{AGENT_NAME}-warden"
        assert len(rb["subjects"]) == 1
        sub = rb["subjects"][0]
        assert sub["kind"] == "ServiceAccount"
        assert sub["name"] == f"{AGENT_NAME}-warden"
        assert sub["namespace"] == NAMESPACE


class TestNetworkPolicy:
    def test_default_denies_ingress(self) -> None:
        np = build_network_policy(AGENT_NAME, AGENT_UID, NAMESPACE, [])
        assert np["spec"]["ingress"] == []
        assert "Ingress" in np["spec"]["policyTypes"]

    def test_allows_dns_egress(self) -> None:
        np = build_network_policy(AGENT_NAME, AGENT_UID, NAMESPACE, [])
        dns_rule = next(
            (r for r in np["spec"]["egress"] if {"port": 53, "protocol": "UDP"} in r["ports"]),
            None,
        )
        assert dns_rule is not None

    def test_allows_guardrails_service_egress(self) -> None:
        np = build_network_policy(AGENT_NAME, AGENT_UID, NAMESPACE, [])
        guardrails_rule = next(
            (r for r in np["spec"]["egress"] if {"port": 8000, "protocol": "TCP"} in r["ports"]),
            None,
        )
        assert guardrails_rule is not None

    def test_allowed_hosts_recorded_in_annotation(self) -> None:
        np = build_network_policy(
            AGENT_NAME, AGENT_UID, NAMESPACE, ["api.github.com", "hooks.slack.com"]
        )
        anno = np["metadata"]["annotations"]["agent-warden.io/allowed-egress-hosts"]
        assert "api.github.com" in anno
        assert "hooks.slack.com" in anno


class TestJob:
    def test_runs_under_scoped_service_account(self, spec: dict[str, Any]) -> None:
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec)
        pod_spec = job["spec"]["template"]["spec"]
        assert pod_spec["serviceAccountName"] == f"{AGENT_NAME}-warden"

    def test_never_retries(self, spec: dict[str, Any]) -> None:
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec)
        assert job["spec"]["backoffLimit"] == 0
        assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"

    def test_pod_runs_as_non_root_with_dropped_caps(self, spec: dict[str, Any]) -> None:
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec)
        pod_spec = job["spec"]["template"]["spec"]
        assert pod_spec["securityContext"]["runAsNonRoot"] is True
        assert pod_spec["securityContext"]["runAsUser"] == 10001
        container = pod_spec["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
        assert container["securityContext"]["allowPrivilegeEscalation"] is False

    def test_task_and_limits_passed_as_env(self, spec: dict[str, Any]) -> None:
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec)
        env = {e["name"]: e["value"] for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        assert env["AGENT_NAME"] == AGENT_NAME
        assert env["AGENT_TASK"] == spec["task"]
        assert env["AGENT_MAX_IRREVERSIBILITY"] == "4"
        assert env["AGENT_MAX_BLAST_RADIUS"] == "30"
        assert "guardrails-service" in env["GUARDRAILS_URL"]

    def test_respects_timeout_and_ttl(self, spec: dict[str, Any]) -> None:
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec)
        assert job["spec"]["activeDeadlineSeconds"] == 300
        assert job["spec"]["ttlSecondsAfterFinished"] == 600

    def test_defaults_apply_when_optional_fields_missing(self) -> None:
        minimal_spec = {
            "task": "x",
            "image": "x:1",
            "maxIrreversibility": 0,
            "maxBlastRadius": 0,
        }
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, minimal_spec)
        assert job["spec"]["activeDeadlineSeconds"] == 600
        assert job["spec"]["ttlSecondsAfterFinished"] == 3600

    def test_command_and_args_passed_through_when_present(self) -> None:
        spec_with_cmd = {
            "task": "x",
            "image": "x:1",
            "maxIrreversibility": 0,
            "maxBlastRadius": 0,
            "command": ["/bin/sh"],
            "args": ["-c", "echo hello"],
        }
        job = build_job(AGENT_NAME, AGENT_UID, NAMESPACE, spec_with_cmd)
        container = job["spec"]["template"]["spec"]["containers"][0]
        assert container["command"] == ["/bin/sh"]
        assert container["args"] == ["-c", "echo hello"]
