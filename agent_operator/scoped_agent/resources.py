"""Pure resource builders for ScopedAgent reconciliation.

Each function takes a ScopedAgent name + spec and returns a dict ready
to be applied via the kubernetes client. No cluster I/O happens here,
which makes these functions easy to unit-test.

The naming scheme for all generated resources is `{agent_name}-warden`.
Every resource carries:
  - labels.app.kubernetes.io/name: agent-warden
  - labels.agent-warden.io/scoped-agent: <name>
  - ownerReferences pointing back to the ScopedAgent

Owner references are how Kubernetes garbage-collects everything when
the ScopedAgent is deleted - we don't need explicit cleanup logic.
"""

from typing import Any

LABEL_NAME = "app.kubernetes.io/name"
LABEL_AGENT = "agent-warden.io/scoped-agent"
ANNOTATION_MANAGED = "agent-warden.io/managed"


def _common_metadata(
    agent_name: str,
    agent_uid: str,
    namespace: str,
    suffix: str = "-warden",
) -> dict[str, Any]:
    """Metadata block shared by every resource we create for a ScopedAgent."""
    return {
        "name": f"{agent_name}{suffix}",
        "namespace": namespace,
        "labels": {
            LABEL_NAME: "agent-warden",
            LABEL_AGENT: agent_name,
        },
        "annotations": {
            ANNOTATION_MANAGED: "true",
        },
        "ownerReferences": [
            {
                "apiVersion": "agent-warden.io/v1alpha1",
                "kind": "ScopedAgent",
                "name": agent_name,
                "uid": agent_uid,
                "controller": True,
                "blockOwnerDeletion": True,
            }
        ],
    }


def build_service_account(agent_name: str, agent_uid: str, namespace: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": _common_metadata(agent_name, agent_uid, namespace),
        "automountServiceAccountToken": True,
    }


def build_role(agent_name: str, agent_uid: str, namespace: str) -> dict[str, Any]:
    """Minimal Role - the agent can only read its own ScopedAgent status.

    Real agent work goes through external APIs (allowed by NetworkPolicy);
    direct k8s API access is intentionally near-zero. This is the principle
    of least privilege as a default - any extra verb needed should require
    an explicit grant elsewhere.
    """
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "Role",
        "metadata": _common_metadata(agent_name, agent_uid, namespace),
        "rules": [
            {
                "apiGroups": ["agent-warden.io"],
                "resources": ["scopedagents"],
                "resourceNames": [agent_name],
                "verbs": ["get", "watch"],
            },
        ],
    }


def build_role_binding(agent_name: str, agent_uid: str, namespace: str) -> dict[str, Any]:
    meta = _common_metadata(agent_name, agent_uid, namespace)
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": meta,
        "subjects": [
            {
                "kind": "ServiceAccount",
                "name": f"{agent_name}-warden",
                "namespace": namespace,
            }
        ],
        "roleRef": {
            "apiGroup": "rbac.authorization.k8s.io",
            "kind": "Role",
            "name": f"{agent_name}-warden",
        },
    }


def build_network_policy(
    agent_name: str,
    agent_uid: str,
    namespace: str,
    allowed_egress_hosts: list[str],
) -> dict[str, Any]:
    """NetworkPolicy locking down egress to DNS + allowlisted hosts only.

    Note: hostname-based egress is not natively enforceable by NetworkPolicy
    (it operates on IPs and pod selectors). For Phase 2 we apply a strict
    'default deny + DNS' baseline and stash the allowlisted hosts in an
    annotation. Phase 3 will resolve them to IPs via a CNI that supports
    FQDN policies (Cilium) or via an egress gateway.
    """
    meta = _common_metadata(agent_name, agent_uid, namespace)
    meta["annotations"]["agent-warden.io/allowed-egress-hosts"] = ",".join(allowed_egress_hosts)
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": meta,
        "spec": {
            "podSelector": {
                "matchLabels": {LABEL_AGENT: agent_name},
            },
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [
                # DNS - required for any external connectivity
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
                # guardrails-service - so the agent can self-check its actions
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"kubernetes.io/metadata.name": "agent-warden-system"}
                            },
                            "podSelector": {
                                "matchLabels": {
                                    "app.kubernetes.io/component": "guardrails-service",
                                }
                            },
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": 8000}],
                },
            ],
        },
    }


def build_job(
    agent_name: str,
    agent_uid: str,
    namespace: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    """The Job that actually runs the agent.

    Inherits the strict pod security profile from guardrails-service and
    references the ServiceAccount/Role we provisioned above.
    """
    meta = _common_metadata(agent_name, agent_uid, namespace)

    container: dict[str, Any] = {
        "name": "agent",
        "image": spec["image"],
        "imagePullPolicy": "IfNotPresent",
        "env": [
            {"name": "AGENT_NAME", "value": agent_name},
            {"name": "AGENT_TASK", "value": spec["task"]},
            {"name": "AGENT_MAX_IRREVERSIBILITY", "value": str(spec["maxIrreversibility"])},
            {"name": "AGENT_MAX_BLAST_RADIUS", "value": str(spec["maxBlastRadius"])},
            {
                "name": "POD_NAMESPACE",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.namespace"}},
            },
            {
                "name": "GUARDRAILS_URL",
                "value": "http://guardrails-service.agent-warden-system.svc.cluster.local",
            },
        ],
        "resources": {
            "requests": {"cpu": "100m", "memory": "128Mi"},
            "limits": {"cpu": "500m", "memory": "512Mi"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    if spec.get("command"):
        container["command"] = spec["command"]
    if spec.get("args"):
        container["args"] = spec["args"]

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": meta,
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": spec.get("timeoutSeconds", 600),
            "ttlSecondsAfterFinished": spec.get("ttlSecondsAfterFinished", 3600),
            "template": {
                "metadata": {
                    "labels": {
                        LABEL_NAME: "agent-warden",
                        LABEL_AGENT: agent_name,
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": f"{agent_name}-warden",
                    "automountServiceAccountToken": True,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [container],
                },
            },
        },
    }
