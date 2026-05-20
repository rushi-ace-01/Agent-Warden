"""FastAPI entrypoint for the guardrails policy service.

Exposes the four atomic checks plus a composite /decide endpoint. The
admission webhook only needs /decide; the atomic endpoints exist for
debugging, replay testing, and the future approval-workflow UI.

Also exposes /metrics for Prometheus scraping.
"""

import time

from fastapi import FastAPI, Response
from pydantic import BaseModel

from guardrails_service.app.metrics import (
    blast_radius_score,
    decision_latency,
    decisions_total,
    irreversibility_score,
    render_metrics,
)
from guardrails_service.app.policy.engine import PolicyEngine
from guardrails_service.app.policy.rules_based import RulesBasedEngine
from guardrails_service.app.types import ActionRequest, Decision


app = FastAPI(title="agent-warden guardrails-service", version="0.1.0")

_engine: PolicyEngine = RulesBasedEngine()


class Health(BaseModel):
    status: str
    version: str


class ScoreOnly(BaseModel):
    score: int


class BoolOnly(BaseModel):
    flag: bool


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok", version="0.1.0")


@app.get("/metrics")
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@app.post("/classify", response_model=ScoreOnly)
def classify(request: ActionRequest) -> ScoreOnly:
    return ScoreOnly(score=_engine.classify(request))


@app.post("/score-blast-radius", response_model=ScoreOnly)
def score_blast_radius(request: ActionRequest) -> ScoreOnly:
    return ScoreOnly(score=_engine.score_blast_radius(request))


@app.post("/scan-colocation", response_model=BoolOnly)
def scan_colocation(request: ActionRequest) -> BoolOnly:
    return BoolOnly(flag=_engine.scan_colocation(request))


@app.post("/audit-credential-scope", response_model=BoolOnly)
def audit_credential_scope(request: ActionRequest) -> BoolOnly:
    return BoolOnly(flag=_engine.audit_credential_scope(request))


@app.post("/decide", response_model=Decision)
def decide(request: ActionRequest) -> Decision:
    start = time.perf_counter()
    decision = _engine.decide(request)
    elapsed = time.perf_counter() - start

    decisions_total.labels(verdict=decision.verdict.value).inc()
    decision_latency.observe(elapsed)
    irreversibility_score.observe(decision.scores.irreversibility)
    blast_radius_score.observe(decision.scores.blast_radius)

    return decision
