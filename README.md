# agent-warden

Runtime guardrails for AI agents running on Kubernetes.

Builds on the static-analysis work in [`rushi-ace-01/AI-Security`](https://github.com/rushi-ace-01/AI-Security) (`agent-guardrails`) by turning its irreversibility / blast-radius / colocation checks into a **runtime enforcement layer** that sits between agents and the Kubernetes API.

## The idea

`agent-guardrails` answers questions like *"how irreversible is this action?"* and *"how much damage could this credential do?"* — but only as static analysis you run *before* deployment. `agent-warden` makes those same checks fire **every time a running agent tries to do something**.

```
┌────────────────────────┐
│ Agent pod              │
│ (ephemeral, scoped SA) │
└──────────┬─────────────┘
           │ "I want to delete a PVC"
           ▼
┌────────────────────────┐
│ Admission webhook      │  ──► calls guardrails-service
│ (ValidatingWebhook)    │      → irreversibility score
└──────────┬─────────────┘      → blast radius score
           │ allow / deny       → policy decision
           ▼
┌────────────────────────┐
│ Kubernetes API         │
└────────────────────────┘
```

## Components

| Component | What it does | Language |
|---|---|---|
| `guardrails_service/` | Wraps the `agent-guardrails` toolset behind a FastAPI HTTP API | Python |
| `agent_operator/` | Watches `ScopedAgent` custom resources and spawns scoped agent pods | Python (kopf) |
| `admission_webhook/` | ValidatingAdmissionWebhook — calls guardrails-service on every relevant action | Python (FastAPI) |
| `crds/` | Custom resource definitions: `ScopedAgent`, `AgentActionRequest`, `BlockedAction` | YAML |
| `deploy/` | Kustomize manifests (base + local overlay for `kind`) | YAML |

## Status

- **Phase 0 — Scaffold:** ✓
- **Phase 1 — Guardrails service:** ✓
- **Phase 2 — ScopedAgent operator:** ✓
- **Phase 3 — Admission webhook:** ✓
- **Phase 4 — Approval workflow:** ✓
- **Phase 5 — Hardening:** ✓

The project is feature-complete. See [`docs/roadmap.md`](docs/roadmap.md) for details and [`incidents/README.md`](incidents/README.md) for how to add new failure-mode fixtures.

## Try it locally

```bash
make install              # set up the venv
make check                # lint + typecheck + test (includes incident replays)
make cluster              # spin up a local kind cluster
make deploy               # build images, generate TLS certs, apply manifests
make demo                 # apply example ScopedAgents and show their logs
make demo-webhook         # try (and fail) to mutate an agent's resources from outside
make dashboard            # port-forward the approval dashboard to localhost:8080
```

### Or install via Helm

```bash
helm install agent-warden ./charts/agent-warden \
  --create-namespace --namespace agent-warden-system
# Then follow the TLS bootstrap step printed in the NOTES output.
```

The `demo` target creates three `ScopedAgent` resources demonstrating the full policy spectrum:

- `log-triage` — calls `/decide` on a safe action and sees `allow`
- `pocketos-replay` — attempts the PocketOS-style PVC deletion and sees `deny`
- `borderline-deploy-bot` — attempts a borderline patch and sees `require_approval`

For the `require_approval` case, an `AgentActionRequest` is created. Open the dashboard (`make dashboard` → http://localhost:8080) to approve or deny. After approval, the agent's retry is let through exactly once.

You can also probe the guardrails API directly:

```bash
make port-forward
# in another terminal:
curl -X POST http://localhost:8000/decide \
  -H 'Content-Type: application/json' \
  -d @examples/pocketos-incident.json | jq
```

## License

MIT.
