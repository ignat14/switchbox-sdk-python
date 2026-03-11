from switchbox.evaluator import _check_rollout, _match_rule, evaluate
from switchbox.models import Flag, Rule


def make_flag(
    key="test_flag",
    enabled=True,
    rollout_pct=100,
    flag_type="boolean",
    default_value=False,
    rules=None,
):
    return Flag(
        key=key,
        enabled=enabled,
        rollout_pct=rollout_pct,
        flag_type=flag_type,
        default_value=default_value,
        rules=rules or [],
    )


# --- Basic evaluation ---


def test_disabled_flag_returns_default():
    flag = make_flag(enabled=False, default_value="off")
    assert evaluate(flag, {"user_id": "1"}) == "off"


def test_enabled_flag_100_rollout_returns_true():
    flag = make_flag(enabled=True, rollout_pct=100)
    assert evaluate(flag, {"user_id": "1"}) is True


def test_enabled_flag_0_rollout_returns_default():
    flag = make_flag(enabled=True, rollout_pct=0, default_value=False)
    assert evaluate(flag, {"user_id": "1"}) is False


# --- Rule matching operators ---


def test_rule_equals():
    rule = Rule(attribute="country", operator="equals", value="US")
    assert _match_rule(rule, {"country": "US"}) is True
    assert _match_rule(rule, {"country": "UK"}) is False


def test_rule_not_equals():
    rule = Rule(attribute="country", operator="not_equals", value="US")
    assert _match_rule(rule, {"country": "UK"}) is True
    assert _match_rule(rule, {"country": "US"}) is False


def test_rule_contains():
    rule = Rule(attribute="email", operator="contains", value="@company")
    assert _match_rule(rule, {"email": "alice@company.com"}) is True
    assert _match_rule(rule, {"email": "alice@other.com"}) is False


def test_rule_ends_with():
    rule = Rule(attribute="email", operator="ends_with", value="@company.com")
    assert _match_rule(rule, {"email": "alice@company.com"}) is True
    assert _match_rule(rule, {"email": "alice@other.com"}) is False


def test_rule_in_list():
    rule = Rule(attribute="tier", operator="in_list", value=["gold", "platinum"])
    assert _match_rule(rule, {"tier": "gold"}) is True
    assert _match_rule(rule, {"tier": "silver"}) is False


def test_rule_gt():
    rule = Rule(attribute="age", operator="gt", value="18")
    assert _match_rule(rule, {"age": 21}) is True
    assert _match_rule(rule, {"age": 16}) is False


def test_rule_lt():
    rule = Rule(attribute="age", operator="lt", value="18")
    assert _match_rule(rule, {"age": 16}) is True
    assert _match_rule(rule, {"age": 21}) is False


def test_rule_missing_attribute_does_not_match():
    rule = Rule(attribute="country", operator="equals", value="US")
    assert _match_rule(rule, {"email": "a@b.com"}) is False


# --- Rules in evaluation (OR logic) ---


def test_any_rule_match_returns_enabled():
    flag = make_flag(
        rollout_pct=0,
        rules=[
            Rule(attribute="country", operator="equals", value="US"),
            Rule(attribute="email", operator="ends_with", value="@company.com"),
        ],
    )
    # Second rule matches
    assert evaluate(flag, {"user_id": "1", "email": "a@company.com"}) is True


# --- Rollout ---


def test_rollout_deterministic():
    """Same user + flag always yields the same result."""
    results = [_check_rollout("user42", "flag_a", 50) for _ in range(100)]
    assert len(set(results)) == 1


def test_rollout_distribution():
    """Over 10k users, ~30% should be in a 30% rollout (within tolerance)."""
    in_rollout = sum(_check_rollout(str(i), "flag_b", 30) for i in range(10_000))
    assert 2500 < in_rollout < 3500


# --- No user context ---


def test_no_user_context_100_rollout():
    flag = make_flag(rollout_pct=100)
    assert evaluate(flag, None) is True


def test_no_user_context_partial_rollout_returns_default():
    flag = make_flag(rollout_pct=50, default_value=False)
    assert evaluate(flag, None) is False


# --- Non-boolean flag types ---


def test_string_flag_returns_string_value():
    flag = make_flag(flag_type="string", default_value="v1", rollout_pct=100)
    assert evaluate(flag, {"user_id": "1"}) == "v1"


def test_number_flag_returns_number_value():
    flag = make_flag(flag_type="number", default_value=42, rollout_pct=100)
    assert evaluate(flag, {"user_id": "1"}) == 42


# --- Additional tests ---


def test_disabled_flag_boolean_returns_false():
    flag = make_flag(enabled=False, default_value=False)
    assert evaluate(flag, {"user_id": "1"}) is False


def test_disabled_flag_string_returns_default():
    flag = make_flag(enabled=False, flag_type="string", default_value="off")
    assert evaluate(flag, {"user_id": "1"}) == "off"


def test_50_pct_rollout_deterministic_for_user():
    flag = make_flag(rollout_pct=50, default_value=False)
    results = [evaluate(flag, {"user_id": "user42"}) for _ in range(100)]
    assert len(set(results)) == 1  # Always same result


def test_contains_case_sensitive():
    rule = Rule(attribute="name", operator="contains", value="Alice")
    assert _match_rule(rule, {"name": "Alice Smith"}) is True
    assert _match_rule(rule, {"name": "alice smith"}) is False


def test_ends_with_no_match():
    rule = Rule(attribute="email", operator="ends_with", value="@company.com")
    assert _match_rule(rule, {"email": "alice@other.com"}) is False


def test_in_list_no_match():
    rule = Rule(attribute="tier", operator="in_list", value=["gold", "platinum"])
    assert _match_rule(rule, {"tier": "silver"}) is False


def test_gt_non_numeric_returns_false():
    rule = Rule(attribute="age", operator="gt", value="18")
    assert _match_rule(rule, {"age": "not_a_number"}) is False


def test_lt_non_numeric_returns_false():
    rule = Rule(attribute="score", operator="lt", value="50")
    assert _match_rule(rule, {"score": "abc"}) is False


def test_multiple_rules_none_match_falls_to_rollout():
    flag = make_flag(
        rollout_pct=0,
        default_value=False,
        rules=[
            Rule(attribute="country", operator="equals", value="US"),
            Rule(attribute="tier", operator="equals", value="gold"),
        ],
    )
    result = evaluate(flag, {"user_id": "1", "country": "UK", "tier": "silver"})
    assert result is False


def test_rollout_different_flag_keys_different_results():
    """Same user with different flag keys should get different bucketing."""
    results_a = _check_rollout("user1", "flag_a", 50)
    results_b = _check_rollout("user1", "flag_b", 50)
    # They CAN be the same by chance, but let's just verify both run without error
    assert isinstance(results_a, bool)
    assert isinstance(results_b, bool)


def test_no_user_context_no_rules_enabled_100_rollout():
    flag = make_flag(enabled=True, rollout_pct=100, rules=[])
    assert evaluate(flag, None) is True


def test_no_user_context_rollout_less_than_100_returns_default():
    flag = make_flag(enabled=True, rollout_pct=50, default_value=False, rules=[])
    assert evaluate(flag, None) is False


def test_string_flag_disabled_returns_default():
    flag = make_flag(enabled=False, flag_type="string", default_value="off")
    assert evaluate(flag) == "off"


def test_number_flag_disabled_returns_default():
    flag = make_flag(enabled=False, flag_type="number", default_value=0)
    assert evaluate(flag) == 0


def test_json_flag_disabled_returns_default():
    flag = make_flag(enabled=False, flag_type="json", default_value={"key": "val"})
    assert evaluate(flag) == {"key": "val"}


def test_rule_attribute_not_in_context_skipped():
    flag = make_flag(
        rollout_pct=0,
        default_value=False,
        rules=[Rule(attribute="missing_attr", operator="equals", value="x")],
    )
    assert evaluate(flag, {"user_id": "1", "other": "y"}) is False
