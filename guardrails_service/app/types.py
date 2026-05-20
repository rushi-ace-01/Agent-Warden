"""Domain types for the guardrails policy engine.

These types are the contract between the admission webhook and the
guardrails service. They are intentionally framework-agnostic — no
FastAPI imports here — so they can be reused by the operator and tests.
"""

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """What the policy engine decided about an action."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ActionRequest(BaseModel):
    """A proposed action by an agent, awaiting a policy decision.

    The admission webhook constructs this from a Kubernetes AdmissionReview
    and sends it to /decide. Field names mirror the upstream taxonomy.
    """

    verb: str = Field(..., description="The operation: create, delete, patch, exec, ...")
    resource: str = Field(..., description="The target resource kind, e.g. 'pvc', 'secret'")
    target: str = Field(..., description="A human-readable identifier of the target")
    namespace: str | None = Field(default=None)
    agent_name: str = Field(..., description="Name of the ScopedAgent making the request")
    agent_max_irreversibility: int = Field(..., ge=0, le=10)
    agent_max_blast_radius: int = Field(..., ge=0, le=100)


class Scores(BaseModel):
    """Numeric outputs from the policy checks for a single action."""

    irreversibility: int = Field(..., ge=0, le=10)
    blast_radius: int = Field(..., ge=0, le=100)
    colocation_risk: bool = Field(default=False)
    over_permissioned: bool = Field(default=False)


class Decision(BaseModel):
    """The policy engine's verdict on an action."""

    verdict: Verdict
    scores: Scores
    reasons: list[str] = Field(default_factory=list)
