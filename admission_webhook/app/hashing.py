"""Hash a proposed agent action into a stable identifier.

When the webhook denies an action with verdict=require_approval, it
creates an AgentActionRequest carrying this hash. When the agent retries
the same action later, the webhook recomputes the hash and looks for an
Approved AAR with a matching hash.

The fields included in the hash are exactly the ones that define what
makes two requests 'the same action' for approval purposes. Notably we
do NOT include timestamps or request UIDs - those would change between
the original attempt and the retry, defeating the lookup.
"""

import hashlib

from admission_webhook.app.types import GuardrailsRequest


def action_hash(request: GuardrailsRequest) -> str:
    """Return a 64-char hex SHA-256 of the action's stable identity."""
    parts = [
        request.agent_name,
        request.verb.lower(),
        request.resource.lower(),
        request.target,
        request.namespace or "",
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
