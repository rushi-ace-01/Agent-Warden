"""FastAPI app for the approval dashboard.

GET  /                                   list pending + recent AARs
POST /aar/{namespace}/{name}/approve     mark Pending → Approved
POST /aar/{namespace}/{name}/deny        mark Pending → Denied

No authentication in v1. Run with a NetworkPolicy that restricts access
to the operator's IP range or behind kubectl port-forward.
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from dashboard.app.render import render_index

logger = logging.getLogger(__name__)

DECIDER_NAME = os.environ.get("AGENT_WARDEN_DECIDER", "dashboard-user")

app = FastAPI(title="agent-warden dashboard", version="0.1.0")


class Health(BaseModel):
    status: str
    version: str


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok", version="0.1.0")


def _custom_objects_api() -> Any:
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CustomObjectsApi()


def _list_aars() -> list[dict[str, Any]]:
    try:
        custom = _custom_objects_api()
        result = custom.list_cluster_custom_object(
            group="agent-warden.io",
            version="v1alpha1",
            plural="agentactionrequests",
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        return list(items)
    except Exception as e:
        logger.error("failed to list AARs: %s", e)
        return []


def _partition_aars(
    aars: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split AARs into (pending, recent). Recent is everything else, newest first."""
    pending = []
    recent = []
    for aar in aars:
        phase = (aar.get("status") or {}).get("phase", "Pending")
        if phase == "Pending":
            pending.append(aar)
        else:
            recent.append(aar)
    recent.sort(
        key=lambda a: (a.get("status") or {}).get("decidedAt") or "",
        reverse=True,
    )
    pending.sort(key=lambda a: (a.get("spec") or {}).get("requestedAt") or "")
    return pending, recent[:20]


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    aars = _list_aars()
    pending, recent = _partition_aars(aars)
    return HTMLResponse(render_index(pending, recent))


def _decide(namespace: str, name: str, *, phase: str) -> None:
    """Patch the AAR's status to Approved or Denied."""
    try:
        custom = _custom_objects_api()
        now = datetime.now(UTC).isoformat()
        custom.patch_namespaced_custom_object_status(
            group="agent-warden.io",
            version="v1alpha1",
            namespace=namespace,
            plural="agentactionrequests",
            name=name,
            body={
                "status": {
                    "phase": phase,
                    "decidedBy": DECIDER_NAME,
                    "decidedAt": now,
                    "message": f"{phase.lower()} via dashboard",
                }
            },
        )
    except Exception as e:
        logger.error("failed to patch AAR %s/%s: %s", namespace, name, e)
        raise HTTPException(status_code=500, detail="patch failed") from e


@app.post("/aar/{namespace}/{name}/approve")
def approve(namespace: str, name: str) -> RedirectResponse:
    _decide(namespace, name, phase="Approved")
    return RedirectResponse(url="/", status_code=303)


@app.post("/aar/{namespace}/{name}/deny")
def deny(namespace: str, name: str) -> RedirectResponse:
    _decide(namespace, name, phase="Denied")
    return RedirectResponse(url="/", status_code=303)
