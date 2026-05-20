"""Build BlockedAction custom resources from denial decisions.

Pure functions only - the k8s API call to actually create the object
lives in the FastAPI handler so we can mock the create call in tests.
"""

import re
from datetime import datetime, timezone
from typing import Any

from admission_webhook.app.types import GuardrailsDecision, GuardrailsRequest


_NAME_SAFE = re.compile(r"[^a-z0-9-]")


def _safe_name_fragment(value: str, max_len: int = 30) -> str:
    """Coerce arbitrary strings into a DNS-1123 fragment for k8s names."""
    s = _NAME_SAFE.sub("-", value.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:max_len] if s else "x"


def build_blocked_action(
    request: GuardrailsRequest,
    decision: GuardrailsDecision,
    request_uid: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Construct the BlockedAction custom resource for a denial.

    Naming scheme: `<agent>-<verb>-<short-uid>` truncated to DNS-1123 limits.
    Using the request UID suffix avoids collisions while keeping names
    debuggable.
    """
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    short_uid = request_uid.split("-")[0] if request_uid else "no-uid"

    name_parts = [
        _safe_name_fragment(request.agent_name, 30),
        _safe_name_fragment(request.verb, 10),
        _safe_name_fragment(short_uid, 12),
    ]
    name = "-".join(p for p in name_parts if p)
    name = name[:253]  # k8s metadata.name limit

    namespace = request.namespace or "default"

    return {
        "apiVersion": "agent-warden.io/v1alpha1",
        "kind": "BlockedAction",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "agent-warden",
                "agent-warden.io/scoped-agent": request.agent_name,
            },
        },
        "spec": {
            "agentName": request.agent_name,
            "verb": request.verb,
            "resource": request.resource,
            "target": request.target,
            "namespace": namespace,
            "scores": {
                "irreversibility": decision.scores.irreversibility,
                "blastRadius": decision.scores.blast_radius,
                "colocationRisk": decision.scores.colocation_risk,
                "overPermissioned": decision.scores.over_permissioned,
            },
            "reasons": decision.reasons,
            "blockedAt": timestamp,
            "requestUid": request_uid,
        },
    }
