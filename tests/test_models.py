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
                "rules": [
                    {"attribute": "country", "operator": "equals", "value": "US"}
                ],
            }
        },
    }
    config = FlagConfig.from_dict(data)
    assert config.version == "2026-01-01T00:00:00Z"
    assert "feature_a" in config.flags
    flag = config.flags["feature_a"]
    assert flag.enabled is True
    assert flag.rollout_pct == 50
    assert len(flag.rules) == 1
    assert flag.rules[0].attribute == "country"


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


def test_flag_defaults():
    flag = Flag(key="f", enabled=True, rollout_pct=100, flag_type="boolean", default_value=False)
    assert flag.rules == []


def test_rule_stores_fields():
    rule = Rule(attribute="country", operator="equals", value="US")
    assert rule.attribute == "country"
    assert rule.operator == "equals"
    assert rule.value == "US"
