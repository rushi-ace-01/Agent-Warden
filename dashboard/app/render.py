"""Server-rendered HTML for the approval dashboard.

Pure functions: input is AAR data, output is HTML strings. No FastAPI,
no I/O. The handlers in main.py call these and return the strings.
"""

import html
from typing import Any


_CSS = """
:root { color-scheme: light dark; }
body { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 0; padding: 2rem; max-width: 64rem; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 1.5rem; }
h2 { font-size: 1.1rem; margin: 2rem 0 0.75rem; color: #555; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
th, td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #e0e0e0; vertical-align: top; }
th { font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: #666; }
tr:last-child td { border-bottom: none; }
.scores { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: #555; }
.phase-Pending { color: #b76e00; font-weight: 600; }
.phase-Approved { color: #007a3d; font-weight: 600; }
.phase-Denied { color: #c8102e; font-weight: 600; }
.phase-Expired { color: #888; }
.phase-Consumed { color: #555; }
.reasons { color: #555; font-size: 13px; }
form.inline { display: inline; }
button { font: inherit; padding: 0.35rem 0.85rem; border-radius: 4px; border: 1px solid #888; background: #f6f6f6; cursor: pointer; }
button.approve { border-color: #007a3d; color: #007a3d; }
button.deny { border-color: #c8102e; color: #c8102e; }
button:hover { background: #eee; }
.empty { color: #888; font-style: italic; padding: 1rem 0; }
.muted { color: #888; font-size: 12px; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _row_for_aar(aar: dict[str, Any], allow_actions: bool) -> str:
    spec = aar.get("spec") or {}
    status = aar.get("status") or {}
    action = spec.get("action") or {}
    scores = spec.get("scores") or {}
    name = aar.get("metadata", {}).get("name", "")
    namespace = aar.get("metadata", {}).get("namespace", "")
    phase = status.get("phase", "Pending")
    reasons = spec.get("reasons", [])

    action_cell = f"<code>{_esc(action.get('verb',''))} {_esc(action.get('resource',''))}/{_esc(action.get('target',''))}</code>"
    if action.get("namespace"):
        action_cell += f"<div class='muted'>in {_esc(action['namespace'])}</div>"

    scores_cell = (
        f"<span class='scores'>irr={_esc(scores.get('irreversibility','?'))} "
        f"blast={_esc(scores.get('blastRadius','?'))}</span>"
    )
    if scores.get("colocationRisk"):
        scores_cell += " <span class='muted'>colocation</span>"

    reasons_cell = "<ul class='reasons'>" + "".join(
        f"<li>{_esc(r)}</li>" for r in reasons
    ) + "</ul>"

    if allow_actions and phase == "Pending":
        actions_cell = (
            f"<form class='inline' method='post' action='/aar/{_esc(namespace)}/{_esc(name)}/approve'>"
            f"<button type='submit' class='approve'>Approve</button></form> "
            f"<form class='inline' method='post' action='/aar/{_esc(namespace)}/{_esc(name)}/deny'>"
            f"<button type='submit' class='deny'>Deny</button></form>"
        )
    else:
        decided = status.get("decidedBy")
        actions_cell = f"<span class='muted'>by {_esc(decided)}</span>" if decided else ""

    return (
        f"<tr><td><strong>{_esc(spec.get('agentName',''))}</strong>"
        f"<div class='muted'>{_esc(name)}</div></td>"
        f"<td>{action_cell}</td>"
        f"<td>{scores_cell}</td>"
        f"<td>{reasons_cell}</td>"
        f"<td class='phase-{_esc(phase)}'>{_esc(phase)}</td>"
        f"<td>{actions_cell}</td></tr>"
    )


def _table(title: str, aars: list[dict[str, Any]], allow_actions: bool) -> str:
    if not aars:
        return f"<h2>{_esc(title)}</h2><div class='empty'>none</div>"
    body = "".join(_row_for_aar(a, allow_actions) for a in aars)
    return (
        f"<h2>{_esc(title)}</h2>"
        f"<table><thead><tr>"
        f"<th>Agent</th><th>Action</th><th>Scores</th><th>Reasons</th><th>Phase</th><th></th>"
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def render_index(
    pending: list[dict[str, Any]],
    recent: list[dict[str, Any]],
) -> str:
    """Render the index page: pending AARs (with buttons) + recent history."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>agent-warden approvals</title>"
        f"<style>{_CSS}</style></head><body>"
        "<h1>agent-warden approvals</h1>"
        + _table("Pending", pending, allow_actions=True)
        + _table("Recent", recent, allow_actions=False)
        + "</body></html>"
    )
