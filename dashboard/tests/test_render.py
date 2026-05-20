"""Tests for the dashboard HTML renderer.

Pure-function tests: given AAR dicts, the rendered HTML should contain
the agent name, action verb, scores, and the right buttons.
"""

from typing import Any

from dashboard.app.render import render_index


def _aar(
    *,
    name: str = "cursor-delete-abc123",
    namespace: str = "demo",
    agent: str = "cursor",
    verb: str = "delete",
    resource: str = "pvc",
    target: str = "production-db",
    phase: str = "Pending",
    irr: int = 7,
    blast: int = 80,
    reasons: list[str] | None = None,
    decided_by: str | None = None,
) -> dict[str, Any]:
    aar: dict[str, Any] = {
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "agentName": agent,
            "action": {"verb": verb, "resource": resource, "target": target, "namespace": namespace},
            "scores": {"irreversibility": irr, "blastRadius": blast},
            "reasons": reasons or ["near the limit"],
        },
        "status": {"phase": phase},
    }
    if decided_by:
        aar["status"]["decidedBy"] = decided_by
    return aar


def test_empty_state_renders_without_error() -> None:
    html = render_index([], [])
    assert "<table" not in html
    assert "Pending" in html and "none" in html


def test_pending_aar_renders_approve_and_deny_forms() -> None:
    html = render_index([_aar()], [])
    assert "/aar/demo/cursor-delete-abc123/approve" in html
    assert "/aar/demo/cursor-delete-abc123/deny" in html
    assert "<button" in html


def test_recent_aar_has_no_action_buttons() -> None:
    html = render_index([], [_aar(phase="Approved", decided_by="alice")])
    assert "/approve" not in html
    assert "/deny" not in html
    assert "alice" in html


def test_html_escapes_dangerous_input() -> None:
    """An attacker can't inject HTML via agent names or targets."""
    aar = _aar(agent="<script>alert(1)</script>", target="bad&quote")
    html = render_index([aar], [])
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html
    assert "bad&amp;quote" in html


def test_action_verb_and_target_visible() -> None:
    html = render_index([_aar(verb="patch", resource="deployment", target="checkout")], [])
    assert "patch" in html
    assert "deployment" in html
    assert "checkout" in html


def test_scores_rendered() -> None:
    html = render_index([_aar(irr=9, blast=95)], [])
    assert "irr=9" in html
    assert "blast=95" in html


def test_reasons_rendered_as_list_items() -> None:
    html = render_index([_aar(reasons=["irreversibility too high", "colocates"])], [])
    assert "<li>irreversibility too high</li>" in html
    assert "<li>colocates</li>" in html


def test_phase_class_applied() -> None:
    html = render_index([], [_aar(phase="Denied", decided_by="alice")])
    assert "phase-Denied" in html
