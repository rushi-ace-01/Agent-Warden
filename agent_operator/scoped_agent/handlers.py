"""kopf handlers for the ScopedAgent CRD.

On create: validate spec, then apply ServiceAccount, Role, RoleBinding,
NetworkPolicy, and Job. Status is updated as we go.

On delete: nothing — Kubernetes garbage-collects everything via owner
references. The handler exists only to update status if we ever need to
hook in cleanup.

On AAR timer: every 30s, check all Pending AgentActionRequests and move
the expired ones to Expired so they can no longer be approved.

Run with:
  kopf run -A agent_operator.scoped_agent.handlers
"""

from datetime import datetime, UTC
from typing import Any

import kopf
from kubernetes import client, config

from agent_operator.scoped_agent.main import SpecError, validate_spec
from agent_operator.scoped_agent.resources import (
    build_job,
    build_network_policy,
    build_role,
    build_role_binding,
    build_service_account,
)


def _load_kube_config() -> None:
    """Load in-cluster config if available, otherwise fall back to kubeconfig.

    Lets the same code run inside a pod and in `kopf run` locally.
    """
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


@kopf.on.startup()
def startup(**_: Any) -> None:
    _load_kube_config()


@kopf.on.create("agent-warden.io", "v1alpha1", "scopedagents")
def on_create(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    uid: str,
    patch: kopf.Patch,
    logger: Any,
    **_: Any,
) -> None:
    """Materialize the resources for a new ScopedAgent."""
    try:
        validate_spec(dict(spec))
    except SpecError as e:
        patch.status["phase"] = "Failed"
        patch.status["message"] = f"invalid spec: {e}"
        raise kopf.PermanentError(f"invalid spec: {e}") from e

    patch.status["phase"] = "Pending"
    patch.status["message"] = "provisioning scoped resources"

    core = client.CoreV1Api()
    rbac = client.RbacAuthorizationV1Api()
    net = client.NetworkingV1Api()
    batch = client.BatchV1Api()

    sa = build_service_account(name, uid, namespace)
    role = build_role(name, uid, namespace)
    rb = build_role_binding(name, uid, namespace)
    np = build_network_policy(name, uid, namespace, list(spec.get("allowedEgressHosts", [])))
    job = build_job(name, uid, namespace, dict(spec))

    logger.info("creating ServiceAccount %s/%s-warden", namespace, name)
    core.create_namespaced_service_account(namespace=namespace, body=sa)

    logger.info("creating Role %s/%s-warden", namespace, name)
    rbac.create_namespaced_role(namespace=namespace, body=role)

    logger.info("creating RoleBinding %s/%s-warden", namespace, name)
    rbac.create_namespaced_role_binding(namespace=namespace, body=rb)

    logger.info("creating NetworkPolicy %s/%s-warden", namespace, name)
    net.create_namespaced_network_policy(namespace=namespace, body=np)

    logger.info("creating Job %s/%s-warden", namespace, name)
    created_job = batch.create_namespaced_job(namespace=namespace, body=job)

    patch.status["phase"] = "Running"
    patch.status["jobName"] = created_job.metadata.name
    patch.status["serviceAccountName"] = f"{name}-warden"
    patch.status["message"] = "agent job created"


@kopf.on.field(
    "batch", "v1", "jobs",
    field="status",
    labels={"agent-warden.io/scoped-agent": kopf.PRESENT},
)
def on_job_status(
    body: dict[str, Any],
    labels: dict[str, str],
    namespace: str,
    logger: Any,
    **_: Any,
) -> None:
    """Mirror the Job's status onto the owning ScopedAgent.

    kopf does field-level watches efficiently — we only react when
    status changes, not on every Job update.
    """
    agent_name = labels.get("agent-warden.io/scoped-agent")
    if not agent_name:
        return

    job_status = body.get("status", {})
    succeeded = job_status.get("succeeded", 0)
    failed = job_status.get("failed", 0)

    custom = client.CustomObjectsApi()

    phase: str | None = None
    message: str | None = None
    if succeeded:
        phase, message = "Completed", "agent job succeeded"
    elif failed:
        phase, message = "Failed", "agent job failed"
    if phase is None:
        return

    logger.info("updating ScopedAgent %s/%s phase=%s", namespace, agent_name, phase)
    custom.patch_namespaced_custom_object_status(
        group="agent-warden.io",
        version="v1alpha1",
        namespace=namespace,
        plural="scopedagents",
        name=agent_name,
        body={"status": {"phase": phase, "message": message}},
    )


@kopf.timer(
    "agent-warden.io", "v1alpha1", "agentactionrequests",
    interval=30.0,
    initial_delay=10.0,
)
def expire_action_request(
    spec: dict[str, Any],
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: Any,
    **_: Any,
) -> None:
    """Move Pending AARs past their expiresAt to Expired.

    Without this, approved-but-never-retried requests would sit in the
    backlog forever and Pending requests with stale expiry would still
    show 'Pending' on the dashboard.
    """
    current_phase = status.get("phase", "Pending")
    if current_phase != "Pending":
        return

    expires_at_raw = spec.get("expiresAt")
    if not expires_at_raw:
        return
    try:
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError:
        logger.warning("AAR %s/%s has unparseable expiresAt %r", namespace, name, expires_at_raw)
        return

    now = datetime.now(UTC)
    if expires_at >= now:
        return

    logger.info("expiring AAR %s/%s (expiresAt=%s)", namespace, name, expires_at_raw)
    custom = client.CustomObjectsApi()
    custom.patch_namespaced_custom_object_status(
        group="agent-warden.io",
        version="v1alpha1",
        namespace=namespace,
        plural="agentactionrequests",
        name=name,
        body={"status": {"phase": "Expired", "message": "approval window elapsed"}},
    )
