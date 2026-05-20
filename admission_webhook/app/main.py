"""ValidatingAdmissionWebhook for agent-warden.

Receives AdmissionReview objects from kube-apiserver. For each one:
  1. If the target object is not agent-managed → allow.
  2. Otherwise, ask guardrails-service /decide.
  3. On deny: record a BlockedAction CR and return AdmissionResponse(allowed=False).
  4. On require_approval: consult AgentActionRequests for this action hash:
     - approved + unexpired + unconsumed → mark consumed, return allowed.
     - pending or human-denied or none   → create one (if needed) and deny.
  5. On allow: return AdmissionResponse(allowed=True).

The webhook is fail-closed for genuine errors talking to guardrails-service
(returns 500), but the ValidatingWebhookConfiguration uses failurePolicy=Ignore
so cluster operations are never blocked by webhook outages. This is a
deliberate trade-off: if guardrails is down, we'd rather agents proceed
than freeze the cluster. Production deployments may invert this.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from admission_webhook.app.action_request import build_action_request
from admission_webhook.app.approval_lookup import (
    ApprovalOutcome,
    evaluate_existing_aars,
)
from admission_webhook.app.blocked_action import build_blocked_action
from admission_webhook.app.hashing import action_hash
from admission_webhook.app.translation import (
    AGENT_LABEL,
    TranslationError,
    build_admission_response,
    extract_request,
    to_guardrails_request,
)
from admission_webhook.app.types import GuardrailsDecision, GuardrailsRequest

logger = logging.getLogger(__name__)

GUARDRAILS_URL = os.environ.get(
    "GUARDRAILS_URL", "http://guardrails-service.agent-warden-system.svc.cluster.local"
)
GUARDRAILS_TIMEOUT_SECONDS = 3.0

app = FastAPI(title="agent-warden admission-webhook", version="0.1.0")


class Health(BaseModel):
    status: str
    version: str


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok", version="0.1.0")


async def _ask_guardrails(payload: dict[str, Any]) -> GuardrailsDecision:
    """Call guardrails-service /decide and return the parsed decision."""
    async with httpx.AsyncClient(timeout=GUARDRAILS_TIMEOUT_SECONDS) as http:
        response = await http.post(f"{GUARDRAILS_URL}/decide", json=payload)
        response.raise_for_status()
        return GuardrailsDecision.model_validate(response.json())


def _k8s_clients() -> Any:
    """Lazy-load the kubernetes client. Returns a CustomObjectsApi handle."""
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


async def _record_blocked_action(blocked: dict[str, Any]) -> None:
    try:
        custom = _k8s_clients()
        custom.create_namespaced_custom_object(
            group="agent-warden.io",
            version="v1alpha1",
            namespace=blocked["metadata"]["namespace"],
            plural="blockedactions",
            body=blocked,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("failed to record BlockedAction: %s", e)


async def _list_action_requests(namespace: str, agent_name: str) -> list[dict[str, Any]]:
    """Return all AARs in the namespace for the given agent."""
    try:
        custom = _k8s_clients()
        result = custom.list_namespaced_custom_object(
            group="agent-warden.io",
            version="v1alpha1",
            namespace=namespace,
            plural="agentactionrequests",
            label_selector=f"{AGENT_LABEL}={agent_name}",
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        return list(items)
    except Exception as e:  # noqa: BLE001
        logger.error("failed to list AARs: %s", e)
        return []


async def _create_action_request(aar: dict[str, Any]) -> None:
    try:
        custom = _k8s_clients()
        custom.create_namespaced_custom_object(
            group="agent-warden.io",
            version="v1alpha1",
            namespace=aar["metadata"]["namespace"],
            plural="agentactionrequests",
            body=aar,
        )
    except Exception as e:  # noqa: BLE001
        # If creation fails because the name already exists, that's fine —
        # it means a concurrent request already queued this. Log and move on.
        logger.error("failed to create AgentActionRequest (may already exist): %s", e)


async def _mark_consumed(namespace: str, name: str) -> None:
    try:
        custom = _k8s_clients()
        now = datetime.now(timezone.utc).isoformat()
        custom.patch_namespaced_custom_object_status(
            group="agent-warden.io",
            version="v1alpha1",
            namespace=namespace,
            plural="agentactionrequests",
            name=name,
            body={"status": {"phase": "Consumed", "consumedAt": now}},
        )
    except Exception as e:  # noqa: BLE001
        logger.error("failed to mark AAR consumed: %s", e)


async def _handle_require_approval(
    gr: GuardrailsRequest, decision: GuardrailsDecision
) -> tuple[bool, str]:
    """Resolve a require_approval verdict against existing AARs.

    Returns (allowed, message). When allowed=True, we've already marked
    the matching AAR as Consumed.
    """
    namespace = gr.namespace or "default"
    h = action_hash(gr)
    aars = await _list_action_requests(namespace, gr.agent_name)
    now = datetime.now(timezone.utc)
    result = evaluate_existing_aars(aars, action_hash=h, now=now)

    if result.outcome == ApprovalOutcome.ALLOW_AND_CONSUME:
        assert result.matching_aar_name is not None
        await _mark_consumed(namespace, result.matching_aar_name)
        return True, f"approval honored: {result.reason}"

    if result.outcome == ApprovalOutcome.DENY_PENDING_EXISTS:
        return False, (
            f"agent-warden: approval pending (AgentActionRequest "
            f"{result.matching_aar_name}). Approve via the dashboard, then retry."
        )

    if result.outcome == ApprovalOutcome.DENY_HUMAN_REJECTED:
        return False, (
            f"agent-warden: a human denied this action (AgentActionRequest "
            f"{result.matching_aar_name}). Refusing."
        )

    # CREATE_AND_DENY
    aar = build_action_request(gr, decision)
    await _create_action_request(aar)
    return False, (
        f"agent-warden requires human approval. Created AgentActionRequest "
        f"{aar['metadata']['name']} — approve via the dashboard, then retry."
    )


@app.post("/validate")
async def validate(req: Request) -> dict[str, Any]:
    """Handle a kube-apiserver AdmissionReview."""
    try:
        review = await req.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {e}") from e

    try:
        uid, request = extract_request(review)
        gr = to_guardrails_request(request)
    except TranslationError as e:
        logger.warning("translation failed: %s", e)
        raise HTTPException(status_code=400, detail=str(e)) from e

    if gr is None:
        return build_admission_response(uid, None)

    logger.info(
        "consulting guardrails for agent=%s verb=%s resource=%s target=%s",
        gr.agent_name, gr.verb, gr.resource, gr.target,
    )
    try:
        decision = await _ask_guardrails(gr.model_dump())
    except httpx.HTTPError as e:
        logger.error("guardrails request failed, denying: %s", e)
        raise HTTPException(status_code=503, detail=f"guardrails unavailable: {e}") from e

    if decision.verdict == "deny":
        blocked = build_blocked_action(gr, decision, uid)
        await _record_blocked_action(blocked)
        return build_admission_response(uid, decision)

    if decision.verdict == "require_approval":
        allowed, message = await _handle_require_approval(gr, decision)
        if allowed:
            return build_admission_response(uid, None)  # treat as plain allow
        # Synthesize a deny response that carries our specific message.
        return {
            "apiVersion": "admission.k8s.io/v1",
            "kind": "AdmissionReview",
            "response": {
                "uid": uid,
                "allowed": False,
                "status": {"code": 403, "message": message},
            },
        }

    return build_admission_response(uid, decision)
