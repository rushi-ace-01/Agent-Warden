"""ScopedAgent operator entrypoint.

Phase 2 wires this up to kopf handlers that watch ScopedAgent CRDs and
materialize them into Pods with the right ServiceAccount, RoleBinding,
NetworkPolicy, and resource limits.

For now we just expose a pure spec-validation function that CI can test
without needing a cluster.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScopedAgentSpec:
    """Validated form of a ScopedAgent custom resource."""

    task: str
    max_irreversibility: int
    max_blast_radius: int
    allowed_tools: tuple[str, ...]


class SpecError(ValueError):
    """Raised when a ScopedAgent spec is malformed."""


def validate_spec(raw: dict[str, object]) -> ScopedAgentSpec:
    """Parse a ScopedAgent.spec dict into a validated ScopedAgentSpec.

    Raises SpecError on missing fields or out-of-range values.
    """
    try:
        task = raw["task"]
        max_irr = raw["maxIrreversibility"]
        max_blast = raw["maxBlastRadius"]
        tools = raw.get("allowedTools", [])
    except KeyError as e:
        raise SpecError(f"missing required field: {e.args[0]}") from None

    if not isinstance(task, str) or not task.strip():
        raise SpecError("task must be a non-empty string")
    if not isinstance(max_irr, int) or not 0 <= max_irr <= 10:
        raise SpecError("maxIrreversibility must be an int in [0, 10]")
    if not isinstance(max_blast, int) or not 0 <= max_blast <= 100:
        raise SpecError("maxBlastRadius must be an int in [0, 100]")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise SpecError("allowedTools must be a list of strings")

    return ScopedAgentSpec(
        task=task,
        max_irreversibility=max_irr,
        max_blast_radius=max_blast,
        allowed_tools=tuple(tools),
    )
