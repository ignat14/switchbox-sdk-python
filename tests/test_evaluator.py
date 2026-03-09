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
