"""Decide how to handle a require_approval verdict.

The webhook can be in one of these states for a given (agent, action) hash:
  - No AAR exists                                  → create Pending, deny.
  - One or more Pending AARs exist (not expired)   → already queued, deny.
  - An Approved AAR exists, unconsumed, unexpired  → honor it, consume, allow.
  - An Approved AAR exists but expired or consumed → create a fresh Pending, deny.
  - A Denied AAR exists                            → respect the human's no, deny.

This module isolates that decision so it can be tested without a cluster.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ApprovalOutcome(str, Enum):
    """What the webhook should do after consulting existing AARs."""

    ALLOW_AND_CONSUME = "allow_and_consume"
    """An Approved AAR matches and is still valid - honor it once."""

    DENY_PENDING_EXISTS = "deny_pending_exists"
    """A Pending AAR is already queued - don't duplicate, just deny."""

    DENY_HUMAN_REJECTED = "deny_human_rejected"
    """A human explicitly denied this action - respect that."""

    CREATE_AND_DENY = "create_and_deny"
    """No usable AAR exists - create a new Pending and deny."""


@dataclass(frozen=True)
class ApprovalLookupResult:
    outcome: ApprovalOutcome
    matching_aar_name: str | None = None
    reason: str | None = None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def evaluate_existing_aars(
    aars: list[dict[str, Any]],
    *,
    action_hash: str,
    now: datetime,
) -> ApprovalLookupResult:
    """Pick the most useful AAR (if any) for this action hash.

    Approval beats pending beats denied beats expired. Among Approved
    candidates, prefer the one with the latest decidedAt that hasn't
    been consumed yet.
    """
    matching = [a for a in aars if a.get("spec", {}).get("actionHash") == action_hash]
    if not matching:
        return ApprovalLookupResult(outcome=ApprovalOutcome.CREATE_AND_DENY)

    approved: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []
    for aar in matching:
        phase = (aar.get("status") or {}).get("phase", "Pending")
        if phase == "Approved":
            approved.append(aar)
        elif phase == "Pending":
            pending.append(aar)
        elif phase == "Denied":
            denied.append(aar)

    for aar in approved:
        status = aar.get("status") or {}
        spec = aar.get("spec") or {}
        if status.get("phase") != "Approved":
            continue
        if status.get("consumedAt"):
            continue
        expires_at = _parse_iso(spec.get("expiresAt"))
        if expires_at and expires_at < now:
            continue
        return ApprovalLookupResult(
            outcome=ApprovalOutcome.ALLOW_AND_CONSUME,
            matching_aar_name=aar["metadata"]["name"],
            reason=f"approved by {status.get('decidedBy', '<unknown>')}",
        )

    for aar in pending:
        expires_at = _parse_iso((aar.get("spec") or {}).get("expiresAt"))
        if expires_at and expires_at < now:
            continue
        return ApprovalLookupResult(
            outcome=ApprovalOutcome.DENY_PENDING_EXISTS,
            matching_aar_name=aar["metadata"]["name"],
            reason="approval already requested and pending",
        )

    if denied:
        latest = max(denied, key=lambda a: (a.get("status") or {}).get("decidedAt", ""))
        return ApprovalLookupResult(
            outcome=ApprovalOutcome.DENY_HUMAN_REJECTED,
            matching_aar_name=latest["metadata"]["name"],
            reason="action was explicitly denied by a human",
        )

    return ApprovalLookupResult(outcome=ApprovalOutcome.CREATE_AND_DENY)
