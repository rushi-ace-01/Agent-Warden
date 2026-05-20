# Roadmap

## Phase 0 — Scaffold (current)

- [x] Repo structure, license, README
- [x] Python tooling: pyproject, ruff, mypy, pytest
- [x] Makefile entrypoint
- [x] Kind cluster config
- [x] Stub modules + first passing tests for each component
- [x] GitHub Actions CI

## Phase 1 — Guardrails service ✓

Wrap the policy checks behind an HTTP API.

- [x] `RulesBasedEngine` — transparent in-repo implementation
- [x] `POST /classify` — irreversibility classifier (score 0–10)
- [x] `POST /score-blast-radius` — blast radius scorer (score 0–100)
- [x] `POST /scan-colocation` — colocated risk scanner
- [x] `POST /audit-credential-scope` — credential scope auditor
- [x] `POST /decide` — composite decision endpoint
- [x] Dockerfile (multi-stage, non-root, ~70MB)
- [x] Kubernetes manifests (Deployment + Service)
- [x] PocketOS replay test — verifies the founding incident is denied
- [ ] **Deferred to Phase 1.5:** vendor the upstream `agent-guardrails` toolset
      and add `UpstreamEngine` that delegates to it. The upstream repo is
      still pre-PyPI and pre-stable, so we ship with `RulesBasedEngine`
      first and keep it as the test baseline.

## Phase 2 — ScopedAgent operator ✓

Custom resource and controller that materializes agent jobs.

- [x] `ScopedAgent` CRD (v1alpha1) with full openAPI schema and status subresource
- [x] Pure resource builders (`resources.py`) — fully unit-tested
- [x] kopf handlers: `on.create`, `on.field` for Job status mirroring
- [x] Materialize each ScopedAgent into:
  - [x] A scoped ServiceAccount
  - [x] A Role granting only self-read on its own CR
  - [x] A RoleBinding tying SA → Role
  - [x] A NetworkPolicy: default-deny ingress + DNS + guardrails egress
  - [x] A Job with strict pod security, `restartPolicy: Never`, `backoffLimit: 0`
- [x] Status subresource: `Pending` → `Running` → `Completed` / `Failed`
- [x] Owner-reference-driven garbage collection (no explicit cleanup needed)
- [x] Operator Dockerfile + Deployment + ClusterRole/Binding
- [x] Example agents: safe and pocketos-replay
- [ ] e2e test under `kind` — Phase 5

## Phase 3 — Admission webhook ✓

Intercept relevant cluster actions on agent-managed objects and consult guardrails.

- [x] `POST /validate` accepting AdmissionReview v1
- [x] Pure translation layer (`translation.py`) — AdmissionReview ↔ GuardrailsRequest
- [x] TLS bootstrap: self-signed CA + cert generated at deploy time (no cert-manager)
- [x] `ValidatingWebhookConfiguration` scoped via `objectSelector` to agent-labeled objects only
- [x] System namespace excluded so the webhook can never block itself
- [x] `failurePolicy: Ignore` to avoid breaking the cluster if the webhook is down
- [x] `BlockedAction` CRD — every denial is a first-class auditable object
- [x] Webhook records `BlockedAction` for every deny verdict
- [x] `make demo-webhook` — shell script that demonstrates the gate from outside

## Phase 4 — Approval workflow ✓

Turn the gray-zone `require_approval` verdict into a queue + dashboard.

- [x] `AgentActionRequest` CRD with `actionHash`, expiresAt, status phase
- [x] Deterministic action hashing (SHA-256 over agent, verb, resource, target, namespace)
- [x] Webhook state machine: ALLOW_AND_CONSUME / DENY_PENDING_EXISTS / DENY_HUMAN_REJECTED / CREATE_AND_DENY
- [x] Approvals are tightly scoped — one AAR honors exactly one matching retry, then marks itself Consumed
- [x] Operator timer reconciler — Pending AARs past their expiresAt move to Expired
- [x] Server-rendered dashboard (FastAPI + plain HTML, no JS framework)
- [x] HTML escaping verified by tests
- [x] Demo agent (`04-require-approval.yaml`) that lands in the gray zone

## Phase 5 — Hardening ✓

- [x] **Incident replay tests** — every `incidents/*.yaml` fixture is replayed against the live engine in CI; adding an incident is dropping a YAML file
- [x] **Helm chart** under `charts/agent-warden` with templated namespace, image refs, and per-component enable toggles
- [x] **Prometheus metrics** in guardrails-service: `decisions_total{verdict}`, `decision_latency_seconds`, score histograms
- [x] **Grafana dashboard** at `deploy/grafana/agent-warden-dashboard.json` — decisions/sec, latency p50/p95/p99, score heatmaps
- [x] **CI integration test** (`.github/workflows/integration.yml`) — spins up kind, deploys, runs demo, asserts a BlockedAction lands, uploads logs on failure
