"""Prometheus metrics for the guardrails service.

Instruments three things:
  - decisions_total{verdict}    counter, one per /decide call
  - decision_latency_seconds    histogram, measured from request to verdict
  - scores_irreversibility/blast_radius   histograms, score distributions

We use prometheus_client directly rather than a FastAPI middleware so we
control exactly what labels emit. Cardinality matters: we label on
verdict only (3 values), never on agent_name or target (unbounded).
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

decisions_total = Counter(
    "agent_warden_decisions_total",
    "Number of policy decisions made, labeled by verdict.",
    ["verdict"],
)

decision_latency = Histogram(
    "agent_warden_decision_latency_seconds",
    "Latency of a /decide call from request receipt to verdict emission.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

irreversibility_score = Histogram(
    "agent_warden_irreversibility_score",
    "Distribution of irreversibility scores returned by /decide.",
    buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
)

blast_radius_score = Histogram(
    "agent_warden_blast_radius_score",
    "Distribution of blast radius scores returned by /decide.",
    buckets=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)


def render_metrics() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
