"""Translation between Kubernetes AdmissionReview and our GuardrailsRequest.

These functions are pure - they do no I/O - which means they get
exhaustive unit tests without any cluster, webhook server, or mocking
of HTTP clients.

The AdmissionReview v1 schema is documented at:
  https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/
"""

from typing import Any

from admission_webhook.app.types import (
    AdmissionResponse,
    GuardrailsDecision,
    GuardrailsRequest,
)


AGENT_LABEL = "agent-warden.io/scoped-agent"
# Defaults applied when the labeled object doesn't carry explicit limits.
# Conservative: assume the agent has no headroom unless it says so.
DEFAULT_MAX_IRREVERSIBILITY = 0
DEFAULT_MAX_BLAST_RADIUS = 0
IRREVERSIBILITY_ANNOTATION = "agent-warden.io/max-irreversibility"
BLAST_RADIUS_ANNOTATION = "agent-warden.io/max-blast-radius"


class TranslationError(ValueError):
    """Raised when an AdmissionReview can't be turned into a GuardrailsRequest."""


def extract_request(review: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Pull (uid, request) out of an AdmissionReview, validating the envelope."""
    if review.get("kind") != "AdmissionReview":
        raise TranslationError(f"expected kind=AdmissionReview, got {review.get('kind')!r}")
    req = review.get("request")
    if not isinstance(req, dict):
        raise TranslationError("missing 'request' object")
    uid = req.get("uid")
    if not isinstance(uid, str) or not uid:
        raise TranslationError("missing or empty request.uid")
    return uid, req


def _read_int_label_or_annotation(
    obj: dict[str, Any], annotation: str, default: int
) -> int:
    """Read an int from object metadata; tolerate strings; clamp to int range."""
    meta = obj.get("metadata", {}) or {}
    annos = meta.get("annotations", {}) or {}
    raw = annos.get(annotation)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as e:
        raise TranslationError(
            f"annotation {annotation}={raw!r} is not an integer"
        ) from e


def to_guardrails_request(req: dict[str, Any]) -> GuardrailsRequest | None:
    """Build a GuardrailsRequest from an AdmissionRequest.

    Returns None if the request is not for an agent-managed object —
    in that case the webhook simply allows the action through. This
    is the gate that keeps the webhook from breaking the cluster.
    """
    obj = req.get("object") or req.get("oldObject") or {}
    meta = obj.get("metadata", {}) or {}
    labels = meta.get("labels", {}) or {}

    agent_name = labels.get(AGENT_LABEL)
    if not agent_name:
        return None

    verb = req.get("operation", "").lower()
    if not verb:
        raise TranslationError("missing operation")

    resource_info = req.get("resource", {}) or {}
    resource = resource_info.get("resource", "")
    if not resource:
        raise TranslationError("missing resource.resource")

    target = meta.get("name", "")
    namespace = req.get("namespace") or meta.get("namespace") or None

    max_irr = _read_int_label_or_annotation(
        obj, IRREVERSIBILITY_ANNOTATION, DEFAULT_MAX_IRREVERSIBILITY
    )
    max_blast = _read_int_label_or_annotation(
        obj, BLAST_RADIUS_ANNOTATION, DEFAULT_MAX_BLAST_RADIUS
    )

    return GuardrailsRequest(
        verb=verb,
        resource=resource.rstrip("s") if resource.endswith("s") and len(resource) > 3 else resource,
        target=target or "(unnamed)",
        namespace=namespace,
        agent_name=agent_name,
        agent_max_irreversibility=max_irr,
        agent_max_blast_radius=max_blast,
    )


def build_admission_response(
    uid: str, decision: GuardrailsDecision | None
) -> dict[str, Any]:
    """Turn a guardrails decision (or absence of one) into an AdmissionReview response.

    decision is None when the object was not agent-managed → allow.
    decision.verdict == 'allow' → allow.
    decision.verdict == 'deny' → deny with a clear message.
    decision.verdict == 'require_approval' → for now, deny with a different message.
      (Phase 4 will turn this into an approval queue rather than a hard deny.)
    """
    response: dict[str, Any]
    if decision is None or decision.verdict == "allow":
        response = AdmissionResponse(uid=uid, allowed=True).model_dump(exclude_none=True)
    elif decision.verdict == "deny":
        response = AdmissionResponse(
            uid=uid,
            allowed=False,
            status={
                "code": 403,
                "message": (
                    "blocked by agent-warden: "
                    + "; ".join(decision.reasons)
                    + f" (irreversibility={decision.scores.irreversibility}, "
                    + f"blast_radius={decision.scores.blast_radius})"
                ),
            },
        ).model_dump(exclude_none=True)
    else:  # require_approval
        response = AdmissionResponse(
            uid=uid,
            allowed=False,
            status={
                "code": 403,
                "message": (
                    "agent-warden requires human approval for this action: "
                    + "; ".join(decision.reasons)
                ),
            },
        ).model_dump(exclude_none=True)

    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": response,
    }
