"""Abstract policy engine interface.

Phase 1 ships with RulesBasedEngine — a transparent, in-repo implementation
that gives us something to test the full pipeline against.

Phase 1.5 will add UpstreamEngine that delegates to the vendored
agent-guardrails toolset. Both implement this Protocol, so the FastAPI
layer never imports either concrete class directly.
"""

from typing import Protocol

from guardrails_service.app.types import ActionRequest, Decision, Scores


class PolicyEngine(Protocol):
    """The contract every policy engine must implement."""

    def classify(self, request: ActionRequest) -> int:
        """Return an irreversibility score in [0, 10] for the action."""
        ...

    def score_blast_radius(self, request: ActionRequest) -> int:
        """Return a blast-radius score in [0, 100] for the action."""
        ...

    def scan_colocation(self, request: ActionRequest) -> bool:
        """Return True if the action's target colocates with sensitive data."""
        ...

    def audit_credential_scope(self, request: ActionRequest) -> bool:
        """Return True if the agent's credentials exceed what this action needs."""
        ...

    def decide(self, request: ActionRequest) -> Decision:
        """Run all checks and return a composite verdict."""
        ...


def _compose_decision(
    request: ActionRequest, scores: Scores, reasons: list[str]
) -> Decision:
    """Shared verdict logic - takes raw scores and produces a Decision.

    Kept at module level so multiple engine implementations can call it
    without duplicating the policy. The verdict thresholds are:
      - DENY: any score exceeds the agent's declared maximums, OR colocation
        risk is detected, OR the credential is over-permissioned.
      - REQUIRE_APPROVAL: irreversibility is close to the limit (within 2)
        and blast radius is non-trivial (>= 20).
      - ALLOW: otherwise.
    """
    from guardrails_service.app.types import Verdict

    if scores.irreversibility > request.agent_max_irreversibility:
        reasons.append(
            f"irreversibility {scores.irreversibility} exceeds agent limit "
            f"{request.agent_max_irreversibility}"
        )
    if scores.blast_radius > request.agent_max_blast_radius:
        reasons.append(
            f"blast radius {scores.blast_radius} exceeds agent limit "
            f"{request.agent_max_blast_radius}"
        )
    if scores.colocation_risk:
        reasons.append("target colocates with sensitive data")
    if scores.over_permissioned:
        reasons.append("agent credentials exceed required scope")

    if reasons:
        return Decision(verdict=Verdict.DENY, scores=scores, reasons=reasons)

    if (
        scores.irreversibility >= max(0, request.agent_max_irreversibility - 2)
        and scores.blast_radius >= 20
    ):
        return Decision(
            verdict=Verdict.REQUIRE_APPROVAL,
            scores=scores,
            reasons=["action is near the agent's irreversibility limit with non-trivial blast radius"],
        )

    return Decision(verdict=Verdict.ALLOW, scores=scores, reasons=[])
