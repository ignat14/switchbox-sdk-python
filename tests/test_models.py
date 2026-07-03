from switchbox.models import Flag, FlagConfig, Rule


def test_flag_config_from_dict_valid():
    data = {
        "version": "2026-01-01T00:00:00Z",
        "flags": {
            "feature_a": {
                "enabled": True,
                "rollout_pct": 50,
                "flag_type": "boolean",
                "default_value": False,
                "rules": [{"attribute": "country", "operator": "equals", "value": "US"}],
            }
        },
    }
    config = FlagConfig.from_dict(data)
    assert config.version == "2026-01-01T00:00:00Z"
    assert "feature_a" in config.flags
    flag = config.flags["feature_a"]
    assert flag.enabled is True
    assert flag.rollout_pct == 50
    # Legacy flat rule is parsed into a single-condition group (back-compat).
    assert len(flag.rules) == 1
    assert flag.rules[0].conditions[0].attribute == "country"


def test_flag_config_from_dict_missing_fields():
    """from_dict should handle missing optional fields gracefully."""
    data = {
        "version": "v1",
        "flags": {
            "basic": {
                "enabled": False,
            }
        },
    }
    config = FlagConfig.from_dict(data)
    flag = config.flags["basic"]
    assert flag.enabled is False
    assert flag.rollout_pct == 0
    assert flag.flag_type == "boolean"
    assert flag.default_value is None
    assert flag.rules == []


def test_flag_config_from_dict_empty_flags():
    data = {"version": "v1", "flags": {}}
    config = FlagConfig.from_dict(data)
    assert config.flags == {}
    assert config.version == "v1"


def test_flag_config_from_dict_with_rules():
    data = {
        "version": "v1",
        "flags": {
            "f": {
                "enabled": True,
                "rules": [
                    {"attribute": "email", "operator": "ends_with", "value": "@test.com"},
                    {"attribute": "tier", "operator": "in_list", "value": ["gold"]},
                ],
            }
        },
    }
    config = FlagConfig.from_dict(data)
    assert len(config.flags["f"].rules) == 2


def test_flag_config_from_dict_with_dnf_groups():
    """The two-level shape: a group with multiple AND'd conditions."""
    data = {
        "version": "v1",
        "flags": {
            "f": {
                "enabled": True,
                "rules": [
                    {
                        "conditions": [
                            {"attribute": "country", "operator": "equals", "value": "US"},
                            {"attribute": "device", "operator": "equals", "value": "mobile"},
                        ]
                    },
                    {"conditions": [{"attribute": "plan", "operator": "equals", "value": "ent"}]},
                ],
            }
        },
    }
    flag = FlagConfig.from_dict(data).flags["f"]
    assert len(flag.rules) == 2  # two groups (OR)
    assert len(flag.rules[0].conditions) == 2  # AND within the first group
    assert flag.rules[1].conditions[0].attribute == "plan"


def test_flag_defaults():
    flag = Flag(key="f", enabled=True, rollout_pct=100, flag_type="boolean", default_value=False)
    assert flag.rules == []


def test_rule_stores_fields():
    rule = Rule(attribute="country", operator="equals", value="US")
    assert rule.attribute == "country"
    assert rule.operator == "equals"
    assert rule.value == "US"


def test_from_dict_skips_a_malformed_flag_keeps_the_rest():
    """Per-flag tolerance (FABLE_IMPROVEMENTS 2.3): one bad flag from a future
    publisher bug must not discard the whole config — that froze every Python
    client on the old version while the JS SDK kept updating."""
    data = {
        "version": "v1",
        "flags": {
            "good": {
                "enabled": True,
                "rollout_pct": 100,
                "flag_type": "boolean",
                "default_value": False,
                "rules": [],
            },
            "missing_enabled": {
                "rollout_pct": 100,
                "flag_type": "boolean",
                "default_value": False,
                "rules": [],
            },
            "not_a_dict": None,
            "garbage_rules": {
                "enabled": True,
                "rollout_pct": 0,
                "flag_type": "boolean",
                "default_value": False,
                "rules": [{"conditions": [{"nope": 1}]}],
            },
        },
    }
    config = FlagConfig.from_dict(data)
    assert set(config.flags) == {"good"}
    assert config.version == "v1"


def test_from_dict_null_rules_parses_as_no_rules():
    """A null `rules` is tolerated as [] (JS toRuleGroups(null) → []), not fatal."""
    data = {
        "version": "v1",
        "flags": {
            "f": {
                "enabled": True,
                "rollout_pct": 100,
                "flag_type": "boolean",
                "default_value": False,
                "rules": None,
            }
        },
    }
    flag = FlagConfig.from_dict(data).flags["f"]
    assert flag.rules == []
