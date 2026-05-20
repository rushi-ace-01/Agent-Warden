"""Types used by the admission webhook.

We keep these separate from guardrails_service.app.types because the
webhook should not depend on the service's internals - it only depends
on the over-the-wire shape of /decide. Coupling them feels tempting
but would mean any internal refactor of the service breaks the webhook.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class GuardrailsRequest(BaseModel):
    """Mirrors guardrails_service.app.types.ActionRequest at the wire boundary."""

    verb: str
    resource: str
    target: str
    namespace: str | None = None
    agent_name: str
    agent_max_irreversibility: int = Field(..., ge=0, le=10)
    agent_max_blast_radius: int = Field(..., ge=0, le=100)


class GuardrailsScores(BaseModel):
    irreversibility: int
    blast_radius: int
    colocation_risk: bool = False
    over_permissioned: bool = False


class GuardrailsDecision(BaseModel):
    verdict: Literal["allow", "require_approval", "deny"]
    scores: GuardrailsScores
    reasons: list[str]


class AdmissionResponse(BaseModel):
    """Subset of the Kubernetes AdmissionResponse v1 schema we actually populate."""

    uid: str
    allowed: bool
    status: dict[str, Any] | None = None
    warnings: list[str] | None = None
