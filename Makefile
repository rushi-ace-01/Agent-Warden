SHELL := /bin/bash
CLUSTER_NAME := agent-warden
PYTHON := python3
VENV := .venv

.PHONY: help
help:
	@echo "agent-warden — runtime guardrails for AI agents on Kubernetes"
	@echo ""
	@echo "Setup:"
	@echo "  make install        Create venv and install all dependencies"
	@echo "  make cluster        Create a local kind cluster"
	@echo "  make cluster-down   Delete the local kind cluster"
	@echo ""
	@echo "Develop:"
	@echo "  make lint           Run ruff"
	@echo "  make test           Run pytest across all components"
	@echo "  make typecheck      Run mypy"
	@echo "  make check          lint + typecheck + test"
	@echo ""
	@echo "Deploy:"
	@echo "  make build          Build container images"
	@echo "  make deploy         Build, load, and apply manifests to the cluster"
	@echo "  make demo           Apply example ScopedAgents and show their logs"
	@echo "  make demo-webhook   Try (and fail) to mutate an agent's resources from outside"
	@echo "  make dashboard      Port-forward the approval dashboard to localhost:8080"
	@echo "  make demo-clean     Remove the demo resources"
	@echo "  make port-forward   Forward guardrails-service to localhost:8000"
	@echo "  make undeploy       Remove agent-warden from the cluster"
	@echo ""
	@echo "Tooling:"
	@echo "  make check-tools    Verify required CLIs are installed"

.PHONY: check-tools
check-tools:
	@command -v docker >/dev/null 2>&1 || { echo "missing: docker"; exit 1; }
	@command -v kind >/dev/null 2>&1 || { echo "missing: kind (https://kind.sigs.k8s.io/docs/user/quick-start/)"; exit 1; }
	@command -v kubectl >/dev/null 2>&1 || { echo "missing: kubectl"; exit 1; }
	@command -v $(PYTHON) >/dev/null 2>&1 || { echo "missing: $(PYTHON)"; exit 1; }
	@echo "all required tools present"

$(VENV)/bin/activate: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[guardrails-service,operator,admission-webhook,dashboard,dev]"
	@touch $(VENV)/bin/activate

.PHONY: install
install: $(VENV)/bin/activate
	@echo "installed. activate with: source $(VENV)/bin/activate"

.PHONY: cluster
cluster: check-tools
	@if kind get clusters | grep -q "^$(CLUSTER_NAME)$$"; then \
	  echo "cluster '$(CLUSTER_NAME)' already exists"; \
	else \
	  kind create cluster --name $(CLUSTER_NAME) --config deploy/local/kind-config.yaml; \
	fi
	kubectl cluster-info --context kind-$(CLUSTER_NAME)

.PHONY: cluster-down
cluster-down:
	kind delete cluster --name $(CLUSTER_NAME)

.PHONY: lint
lint: $(VENV)/bin/activate
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

.PHONY: format
format: $(VENV)/bin/activate
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

.PHONY: test
test: $(VENV)/bin/activate
	$(VENV)/bin/pytest

.PHONY: typecheck
typecheck: $(VENV)/bin/activate
	$(VENV)/bin/mypy guardrails_service agent_operator admission_webhook/app dashboard/app

.PHONY: check
check: lint typecheck test

.PHONY: build
build: build-guardrails build-operator build-webhook build-dashboard

.PHONY: build-guardrails
build-guardrails:
	docker build -t agent-warden/guardrails-service:dev -f guardrails_service/Dockerfile .

.PHONY: build-operator
build-operator:
	docker build -t agent-warden/agent-operator:dev -f agent_operator/Dockerfile .

.PHONY: build-webhook
build-webhook:
	docker build -t agent-warden/admission-webhook:dev -f admission_webhook/Dockerfile .

.PHONY: build-dashboard
build-dashboard:
	docker build -t agent-warden/dashboard:dev -f dashboard/Dockerfile .

.PHONY: load
load: cluster build
	kind load docker-image agent-warden/guardrails-service:dev --name $(CLUSTER_NAME)
	kind load docker-image agent-warden/agent-operator:dev --name $(CLUSTER_NAME)
	kind load docker-image agent-warden/admission-webhook:dev --name $(CLUSTER_NAME)
	kind load docker-image agent-warden/dashboard:dev --name $(CLUSTER_NAME)

.PHONY: gen-certs
gen-certs: $(VENV)/bin/activate
	mkdir -p tls
	$(VENV)/bin/python scripts/gen-webhook-certs.py \
	  --service admission-webhook \
	  --namespace agent-warden-system \
	  --out-dir tls > tls/ca.b64

.PHONY: deploy
deploy: load gen-certs
	kubectl apply -k deploy/local
	kubectl -n agent-warden-system rollout status deploy/guardrails-service --timeout=60s
	kubectl -n agent-warden-system rollout status deploy/agent-operator --timeout=60s
	kubectl -n agent-warden-system rollout status deploy/dashboard --timeout=60s
	@echo "Applying webhook TLS Secret from generated certs..."
	kubectl -n agent-warden-system create secret tls admission-webhook-tls \
	  --cert=tls/tls.crt --key=tls/tls.key \
	  --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n agent-warden-system rollout restart deploy/admission-webhook
	kubectl -n agent-warden-system rollout status deploy/admission-webhook --timeout=60s
	@echo "Patching ValidatingWebhookConfiguration with CA bundle..."
	kubectl patch validatingwebhookconfiguration agent-warden \
	  --type='json' \
	  -p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\":\"$$(cat tls/ca.b64)\"}]"
	@echo "Deployed."

.PHONY: dashboard
dashboard:
	@echo "Open http://localhost:8080 in your browser"
	kubectl -n agent-warden-system port-forward svc/dashboard 8080:80

.PHONY: demo
demo:
	kubectl apply -f examples/00-demo-namespace.yaml
	kubectl apply -f examples/01-safe-agent.yaml
	kubectl apply -f examples/02-pocketos-replay.yaml
	kubectl apply -f examples/04-require-approval.yaml
	@echo
	@echo "Waiting for jobs to complete..."
	@sleep 5
	kubectl -n agent-warden-demo wait --for=condition=Complete job -l app.kubernetes.io/name=agent-warden --timeout=120s || true
	@echo
	@echo "=== ScopedAgents ==="
	kubectl -n agent-warden-demo get scopedagents
	@echo
	@echo "=== AgentActionRequests (open the dashboard to approve) ==="
	kubectl -n agent-warden-demo get agentactionrequests 2>/dev/null || echo "  (none yet)"
	@echo
	@echo "=== Safe agent logs ==="
	-kubectl -n agent-warden-demo logs job/log-triage-warden
	@echo
	@echo "=== PocketOS replay logs ==="
	-kubectl -n agent-warden-demo logs job/pocketos-replay-warden
	@echo
	@echo "=== Borderline (require-approval) logs ==="
	-kubectl -n agent-warden-demo logs job/borderline-deploy-bot-warden

.PHONY: demo-webhook
demo-webhook:
	scripts/demo-webhook.sh

.PHONY: demo-clean
demo-clean:
	kubectl delete -f examples/02-pocketos-replay.yaml --ignore-not-found
	kubectl delete -f examples/01-safe-agent.yaml --ignore-not-found
	kubectl delete -f examples/00-demo-namespace.yaml --ignore-not-found

.PHONY: port-forward
port-forward:
	@echo "Forwarding guardrails-service to http://localhost:8000"
	@echo "Try:  curl -X POST http://localhost:8000/decide -H 'Content-Type: application/json' -d @examples/pocketos-incident.json | jq"
	kubectl -n agent-warden-system port-forward svc/guardrails-service 8000:80

.PHONY: undeploy
undeploy:
	kubectl delete -k deploy/local --ignore-not-found
