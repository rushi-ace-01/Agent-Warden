# Contributing

Thanks for your interest. agent-warden is in early development — the easiest contributions right now are reviewing the roadmap in `docs/roadmap.md` and opening issues that challenge the design.

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/agent-warden.git
cd agent-warden
make install        # creates .venv and installs everything
source .venv/bin/activate
make check          # runs lint, typecheck, and tests
```

## Local cluster

You'll need [Docker](https://www.docker.com/), [kind](https://kind.sigs.k8s.io/), and [kubectl](https://kubernetes.io/docs/tasks/tools/) installed.

```bash
make check-tools    # verifies your toolchain
make cluster        # spins up a local kind cluster
```

## Code style

- Python 3.11+, formatted with `ruff format`, linted with `ruff check`.
- Public functions are type-annotated; `mypy --strict` must pass.
- Tests live next to the code they cover (e.g. `guardrails_service/tests/`).

## Commit messages

Conventional Commits — `feat:`, `fix:`, `chore:`, `docs:`, `test:`.

## Pull requests

CI must pass before review. Keep PRs focused on one phase item where possible.
