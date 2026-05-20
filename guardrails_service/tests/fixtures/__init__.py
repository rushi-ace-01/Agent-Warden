"""Test fixtures: known incidents replayed as ActionRequest objects.

Each fixture corresponds to an entry that should land in incidents/ in
the upstream agent-guardrails repo. Treating these as code (not just
docs) means we can assert the policy engine catches every one.
"""

from guardrails_service.app.types import ActionRequest


POCKETOS_DB_DELETION = ActionRequest(
    verb="delete",
    resource="pvc",
    target="production-db-backup-volume",
    namespace="production",
    agent_name="cursor-staging-agent",
    agent_max_irreversibility=4,
    agent_max_blast_radius=30,
)
"""April 2026: Cursor agent deletes a PVC holding the production database
AND its colocated backups. Reconstructed from the incident description in
the upstream agent-guardrails README. Used as the headline replay test.
"""


SAFE_LOG_READ = ActionRequest(
    verb="get",
    resource="pod",
    target="frontend-7d9c4b",
    namespace="staging",
    agent_name="log-triage-agent",
    agent_max_irreversibility=8,
    agent_max_blast_radius=60,
)
"""A boring, fully-allowed action - reading a pod in staging."""


BORDERLINE_DEPLOY_PATCH = ActionRequest(
    verb="patch",
    resource="deployment",
    target="checkout-service",
    namespace="production",
    agent_name="deploy-bot",
    agent_max_irreversibility=6,
    agent_max_blast_radius=60,
)
"""Edits a production deployment - should land in REQUIRE_APPROVAL."""
