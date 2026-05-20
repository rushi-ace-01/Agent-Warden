"""Replay every fixture in `incidents/` against the policy engine.

This is the project's headline test: each fixture is a documented or
reconstructed failure mode, and the engine must produce the expected
verdict for every one. Adding a new incident is dropping a YAML file
in `incidents/` — the harness picks it up automatically.

The test is parameterized by fixture id so failures point at the exact
incident that broke.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from guardrails_service.app.main import app

INCIDENTS_DIR = Path(__file__).resolve().parents[2] / "incidents"


def _load_fixtures() -> list[tuple[str, dict[str, Any]]]:
    fixtures: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(INCIDENTS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or "id" not in data:
            continue
        fixtures.append((data["id"], data))
    return fixtures


_FIXTURES = _load_fixtures()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_incidents_directory_is_not_empty() -> None:
    """Guards against accidental deletion or misconfiguration."""
    assert _FIXTURES, f"no fixtures found in {INCIDENTS_DIR}"


@pytest.mark.parametrize("incident_id,fixture", _FIXTURES, ids=[f[0] for f in _FIXTURES])
def test_replay(incident_id: str, fixture: dict[str, Any], client: TestClient) -> None:
    response = client.post("/decide", json=fixture["request"])
    assert response.status_code == 200, f"{incident_id}: {response.text}"

    body = response.json()
    expected = fixture["expected"]

    assert body["verdict"] == expected["verdict"], (
        f"{incident_id}: expected verdict={expected['verdict']!r}, "
        f"got {body['verdict']!r}. Reasons: {body['reasons']}"
    )

    min_reasons = expected.get("min_reasons", 0)
    assert len(body["reasons"]) >= min_reasons, (
        f"{incident_id}: expected at least {min_reasons} reasons, got {len(body['reasons'])}: "
        f"{body['reasons']}"
    )

    for keyword in expected.get("must_mention", []):
        joined = " | ".join(body["reasons"]).lower()
        assert keyword.lower() in joined, (
            f"{incident_id}: expected reason mentioning {keyword!r}, "
            f"got reasons: {body['reasons']}"
        )
