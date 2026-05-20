"""Build AgentActionRequest custom resources for gray-zone decisions.

When the policy says require_approval, the webhook calls this function
to construct the AAR, then creates it via the k8s API. Same testability
pattern as build_blocked_action: no I/O here.
"""

import re
from datetime import datetime, timedelta, UTC
from typing import Any

from admission_webhook.app.hashing import action_hash
from admission_webhook.app.types import GuardrailsDecision, GuardrailsRequest

DEFAULT_APPROVAL_WINDOW_MINUTES = 15

_NAME_SAFE = re.compile(r"[^a-z0-9-]")


def _safe_name_fragment(value: str, max_len: int = 30) -> str:
    s = _NAME_SAFE.sub("-", value.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] if s else "x"


def build_action_request(
    request: GuardrailsRequest,
    decision: GuardrailsDecision,
    *,
    window_minutes: int = DEFAULT_APPROVAL_WINDOW_MINUTES,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construct the AgentActionRequest CR for a require_approval decision.

    The AAR name uses the first 12 hex chars of the action hash, which
    means re-requesting the same action while a previous Pending AAR
    still exists results in a duplicate-name conflict the webhook can
    interpret as 'already pending, just deny'.
    """
    timestamp = now or datetime.now(UTC)
    expires_at = timestamp + timedelta(minutes=window_minutes)
    h = action_hash(request)

    name = "-".join(
        p for p in [
            _safe_name_fragment(request.agent_name, 30),
            _safe_name_fragment(request.verb, 10),
            h[:12],
        ] if p
    )[:253]

    namespace = request.namespace or "default"

    return {
        "apiVersion": "agent-warden.io/v1alpha1",
        "kind": "AgentActionRequest",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "agent-warden",
                "agent-warden.io/scoped-agent": request.agent_name,
                "agent-warden.io/action-hash": h[:32],
            },
        },
        "spec": {
            "agentName": request.agent_name,
            "actionHash": h,
            "action": {
                "verb": request.verb,
                "resource": request.resource,
                "target": request.target,
                "namespace": namespace,
            },
            "scores": {
                "irreversibility": decision.scores.irreversibility,
                "blastRadius": decision.scores.blast_radius,
                "colocationRisk": decision.scores.colocation_risk,
                "overPermissioned": decision.scores.over_permissioned,
            },
            "reasons": decision.reasons,
            "requestedAt": timestamp.isoformat(),
            "expiresAt": expires_at.isoformat(),
        },
    }
