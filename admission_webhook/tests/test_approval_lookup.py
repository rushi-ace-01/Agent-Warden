"""Tests for the approval lookup logic.

These exhaustively cover the state machine: given a list of AARs and an
action hash, what should the webhook do? Pure functions, no I/O.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from admission_webhook.app.approval_lookup import (
    ApprovalOutcome,
    evaluate_existing_aars,
)


NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
TARGET_HASH = "a" * 64
OTHER_HASH = "b" * 64


def _aar(
    *,
    name: str,
    phase: str = "Pending",
    hash_value: str = TARGET_HASH,
    expires_in_minutes: int = 15,
    decided_at_offset_minutes: int | None = None,
    consumed: bool = False,
    decided_by: str | None = None,
) -> dict[str, Any]:
    expires_at = NOW + timedelta(minutes=expires_in_minutes)
    aar: dict[str, Any] = {
        "metadata": {"name": name, "namespace": "demo"},
        "spec": {
            "actionHash": hash_value,
            "expiresAt": expires_at.isoformat(),
        },
        "status": {"phase": phase},
    }
    if decided_at_offset_minutes is not None:
        decided_at = NOW + timedelta(minutes=decided_at_offset_minutes)
        aar["status"]["decidedAt"] = decided_at.isoformat()
    if consumed:
        aar["status"]["consumedAt"] = NOW.isoformat()
    if decided_by:
        aar["status"]["decidedBy"] = decided_by
    return aar


def test_no_matching_aar_returns_create_and_deny() -> None:
    result = evaluate_existing_aars([], action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.CREATE_AND_DENY


def test_aar_with_different_hash_is_ignored() -> None:
    aars = [_aar(name="other", hash_value=OTHER_HASH, phase="Approved")]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.CREATE_AND_DENY


def test_approved_unconsumed_unexpired_means_allow() -> None:
    aars = [_aar(name="x", phase="Approved", decided_by="alice")]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.ALLOW_AND_CONSUME
    assert result.matching_aar_name == "x"
    assert "alice" in (result.reason or "")


def test_approved_but_consumed_falls_through_to_create_and_deny() -> None:
    aars = [_aar(name="x", phase="Approved", consumed=True)]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.CREATE_AND_DENY


def test_approved_but_expired_falls_through_to_create_and_deny() -> None:
    aars = [_aar(name="x", phase="Approved", expires_in_minutes=-5)]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.CREATE_AND_DENY


def test_pending_unexpired_means_deny_pending_exists() -> None:
    aars = [_aar(name="x", phase="Pending")]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.DENY_PENDING_EXISTS
    assert result.matching_aar_name == "x"


def test_pending_but_expired_falls_through_to_create_and_deny() -> None:
    aars = [_aar(name="x", phase="Pending", expires_in_minutes=-5)]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.CREATE_AND_DENY


def test_denied_aar_means_deny_human_rejected() -> None:
    aars = [_aar(name="x", phase="Denied", decided_at_offset_minutes=-1)]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.DENY_HUMAN_REJECTED


def test_approved_wins_over_pending() -> None:
    """If both a Pending and an Approved exist, approval wins."""
    aars = [
        _aar(name="pending-one", phase="Pending"),
        _aar(name="approved-one", phase="Approved"),
    ]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.ALLOW_AND_CONSUME
    assert result.matching_aar_name == "approved-one"


def test_approved_wins_over_denied() -> None:
    """If a fresh approval exists alongside a stale denial, the approval wins."""
    aars = [
        _aar(name="old-denied", phase="Denied", decided_at_offset_minutes=-30),
        _aar(name="fresh-approved", phase="Approved"),
    ]
    result = evaluate_existing_aars(aars, action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.ALLOW_AND_CONSUME


def test_pending_with_unparseable_expiry_is_treated_as_pending() -> None:
    """Defensive: bad timestamps shouldn't make us silently skip."""
    aar = _aar(name="x", phase="Pending")
    aar["spec"]["expiresAt"] = "not a timestamp"
    result = evaluate_existing_aars([aar], action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == ApprovalOutcome.DENY_PENDING_EXISTS


@pytest.mark.parametrize(
    "missing_status, expected",
    [
        (True, ApprovalOutcome.DENY_PENDING_EXISTS),
        (False, ApprovalOutcome.DENY_PENDING_EXISTS),
    ],
)
def test_aar_with_no_status_is_treated_as_pending(
    missing_status: bool, expected: ApprovalOutcome
) -> None:
    aar = _aar(name="x", phase="Pending")
    if missing_status:
        aar.pop("status")
    result = evaluate_existing_aars([aar], action_hash=TARGET_HASH, now=NOW)
    assert result.outcome == expected
