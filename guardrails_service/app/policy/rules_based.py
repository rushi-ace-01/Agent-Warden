"""Rules-based policy engine.

Transparent, in-repo implementation modeled on the upstream agent-guardrails
taxonomy. Patterns are deliberately conservative: when in doubt, score higher.

When the upstream toolset stabilizes, UpstreamEngine will replace this for
production use, but we keep RulesBasedEngine around as a baseline and a
fast unit-test fixture.
"""

from guardrails_service.app.policy.engine import _compose_decision
from guardrails_service.app.types import ActionRequest, Decision, Scores


_IRREVERSIBILITY_BY_VERB: dict[str, int] = {
    "get": 0,
    "list": 0,
    "watch": 0,
    "create": 3,
    "patch": 5,
    "update": 5,
    "exec": 7,
    "delete": 9,
    "deletecollection": 10,
}

_BLAST_RADIUS_BY_RESOURCE: dict[str, int] = {
    "configmap": 15,
    "pod": 25,
    "deployment": 35,
    "job": 30,
    "service": 30,
    "secret": 70,
    "pvc": 80,
    "persistentvolumeclaim": 80,
    "persistentvolume": 90,
    "node": 95,
    "namespace": 95,
    "clusterrole": 90,
    "clusterrolebinding": 90,
}

_SENSITIVE_NAMESPACE_KEYWORDS: tuple[str, ...] = (
    "prod",
    "production",
    "backup",
    "kube-system",
    "vault",
)

_SENSITIVE_TARGET_KEYWORDS: tuple[str, ...] = (
    "backup",
    "snapshot",
    "credentials",
    "master",
)


class RulesBasedEngine:
    """Table-driven policy engine. Implements the PolicyEngine Protocol."""

    def classify(self, request: ActionRequest) -> int:
        return _IRREVERSIBILITY_BY_VERB.get(request.verb.lower(), 5)

    def score_blast_radius(self, request: ActionRequest) -> int:
        base = _BLAST_RADIUS_BY_RESOURCE.get(request.resource.lower(), 20)
        if request.namespace and any(
            kw in request.namespace.lower() for kw in _SENSITIVE_NAMESPACE_KEYWORDS
        ):
            base = min(100, base + 15)
        return base

    def scan_colocation(self, request: ActionRequest) -> bool:
        target_lower = request.target.lower()
        ns_lower = (request.namespace or "").lower()
        target_hits_sensitive = any(kw in target_lower for kw in _SENSITIVE_TARGET_KEYWORDS)
        ns_hits_sensitive = any(kw in ns_lower for kw in _SENSITIVE_NAMESPACE_KEYWORDS)
        return target_hits_sensitive and ns_hits_sensitive

    def audit_credential_scope(self, request: ActionRequest) -> bool:
        """A read-only verb attempting a destructive resource implies over-scoped creds."""
        read_only = request.verb.lower() in {"get", "list", "watch"}
        destructive_resource = request.resource.lower() in {
            "secret",
            "pvc",
            "persistentvolumeclaim",
            "persistentvolume",
        }
        return not read_only and destructive_resource and request.agent_max_blast_radius < 50

    def decide(self, request: ActionRequest) -> Decision:
        scores = Scores(
            irreversibility=self.classify(request),
            blast_radius=self.score_blast_radius(request),
            colocation_risk=self.scan_colocation(request),
            over_permissioned=self.audit_credential_scope(request),
        )
        return _compose_decision(request, scores, reasons=[])
