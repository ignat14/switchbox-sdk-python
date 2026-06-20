"""CDN JSON contract — Python SDK side of the 3-repo handshake (TESTING Phase 2).

Parses the canonical fixtures (`tests/fixtures/cdn-json/`, synced from the workspace
`fixtures/cdn-json/` by `fixtures/sync.py`) and pins how `FlagConfig.from_dict`
interprets the format the backend publisher emits. A format change that isn't mirrored
here fails these tests; see the workspace `fixtures/cdn-json/README.md`.
"""

import json
from pathlib import Path

import pytest

from switchbox.models import FlagConfig

FIXTURES = Path(__file__).parent / "fixtures" / "cdn-json"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.mark.parametrize(
    "name",
    ["full_config", "defaults", "unknown_fields", "legacy_flat_rules", "empty"],
)
def test_every_fixture_parses(name):
    """Every canonical fixture parses without error."""
    config = FlagConfig.from_dict(load(name))
    assert isinstance(config, FlagConfig)
    assert config.version  # all fixtures carry a version string


def test_full_config_flag_types_and_values():
    flags = FlagConfig.from_dict(load("full_config")).flags

    assert flags["bool_on"].flag_type == "boolean"
    assert flags["bool_on"].enabled is True
    assert flags["bool_on"].rollout_pct == 100
    assert flags["bool_on"].rules == []

    assert flags["bool_off"].enabled is False

    # Variations carry enabled_value; booleans do not.
    assert flags["string_ab"].flag_type == "string"
    assert flags["string_ab"].default_value == "control"
    assert flags["string_ab"].enabled_value == "treatment"
    assert flags["number_rollout"].enabled_value == 42
    assert flags["number_rollout"].rollout_pct == 25
    assert flags["json_variant"].default_value == {"theme": "light"}
    assert flags["json_variant"].enabled_value == {"theme": "dark"}
    assert flags["bool_on"].enabled_value is None


def test_full_config_all_seven_operators_present():
    flags = FlagConfig.from_dict(load("full_config")).flags
    groups = flags["all_operators"].rules
    ops = {c.operator for g in groups for c in g.conditions}
    assert ops == {
        "equals",
        "not_equals",
        "contains",
        "ends_with",
        "in_list",
        "gt",
        "lt",
    }
    # in_list value stays a list (both evaluators do membership against a list).
    in_list = next(c for g in groups for c in g.conditions if c.operator == "in_list")
    assert in_list.value == ["US", "CA", "GB"]


def test_full_config_dnf_structure():
    """Two-level DNF: a flag is OR of AND-groups."""
    flags = FlagConfig.from_dict(load("full_config")).flags
    groups = flags["all_operators"].rules
    assert len(groups) == 3  # three OR'd groups
    assert [len(g.conditions) for g in groups] == [2, 2, 3]


def test_segments_are_inlined_not_referenced():
    """The publisher expands segments to flat conditions — the SDK never sees a
    segment reference."""
    flags = FlagConfig.from_dict(load("full_config")).flags
    seg = flags["segment_flag"]
    assert len(seg.rules) == 1
    cond = seg.rules[0].conditions[0]
    assert (cond.attribute, cond.operator, cond.value) == (
        "plan",
        "equals",
        "enterprise",
    )


def test_defaults_applied_for_omitted_fields():
    flag = FlagConfig.from_dict(load("defaults")).flags["minimal"]
    assert flag.enabled is True
    assert flag.rollout_pct == 0
    assert flag.flag_type == "boolean"
    assert flag.default_value is None
    assert flag.enabled_value is None
    assert flag.rules == []


def test_unknown_fields_are_ignored():
    config = FlagConfig.from_dict(load("unknown_fields"))
    flag = config.flags["fwd_compat"]
    # Known fields parsed; unknown ones simply don't appear on the dataclass.
    assert flag.enabled is True
    assert not hasattr(flag, "some_future_field")


def test_legacy_flat_rule_becomes_single_condition_group():
    flag = FlagConfig.from_dict(load("legacy_flat_rules")).flags["legacy"]
    assert len(flag.rules) == 1
    assert len(flag.rules[0].conditions) == 1
    cond = flag.rules[0].conditions[0]
    assert (cond.attribute, cond.operator, cond.value) == ("country", "equals", "US")


def test_empty_flags_object():
    config = FlagConfig.from_dict(load("empty"))
    assert config.flags == {}
