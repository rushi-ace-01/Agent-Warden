import pytest

from agent_operator.scoped_agent.main import ScopedAgentSpec, SpecError, validate_spec


def test_valid_spec_parses() -> None:
    spec = validate_spec(
        {
            "task": "review PR #42 and post comments",
            "maxIrreversibility": 6,
            "maxBlastRadius": 40,
            "allowedTools": ["github", "slack"],
        }
    )
    assert spec == ScopedAgentSpec(
        task="review PR #42 and post comments",
        max_irreversibility=6,
        max_blast_radius=40,
        allowed_tools=("github", "slack"),
    )


def test_allowed_tools_defaults_to_empty() -> None:
    spec = validate_spec(
        {"task": "noop", "maxIrreversibility": 0, "maxBlastRadius": 0}
    )
    assert spec.allowed_tools == ()


@pytest.mark.parametrize(
    "field, raw",
    [
        ("task", {"maxIrreversibility": 5, "maxBlastRadius": 5}),
        ("maxIrreversibility", {"task": "x", "maxBlastRadius": 5}),
        ("maxBlastRadius", {"task": "x", "maxIrreversibility": 5}),
    ],
)
def test_missing_required_field_raises(field: str, raw: dict[str, object]) -> None:
    with pytest.raises(SpecError, match=field):
        validate_spec(raw)


@pytest.mark.parametrize(
    "raw",
    [
        {"task": "", "maxIrreversibility": 5, "maxBlastRadius": 5},
        {"task": "x", "maxIrreversibility": 11, "maxBlastRadius": 5},
        {"task": "x", "maxIrreversibility": -1, "maxBlastRadius": 5},
        {"task": "x", "maxIrreversibility": 5, "maxBlastRadius": 101},
        {"task": "x", "maxIrreversibility": 5, "maxBlastRadius": 5, "allowedTools": "github"},
    ],
)
def test_out_of_range_values_raise(raw: dict[str, object]) -> None:
    with pytest.raises(SpecError):
        validate_spec(raw)
