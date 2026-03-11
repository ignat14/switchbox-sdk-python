"""Pure evaluation engine for Switchbox feature flags.

Zero external dependencies — only Python stdlib.
"""

import hashlib
from typing import Any

from switchbox.models import Flag, Rule


def evaluate(flag: Flag, user_context: dict | None = None) -> bool | str | int | Any:
    """Evaluate a flag for a given user context.

    Returns the flag's resolved value.

    Evaluation order:
    1. Flag disabled → default_value
    2. No user context → enabled value if rollout == 100, else default_value
    3. Rules match (OR logic) → enabled value
    4. Rollout percentage check → enabled value or default_value
    5. Nothing matched → default_value
    """
    try:
        # 1. Disabled flag always returns default
        if not flag.enabled:
            return flag.default_value

        # 2. No user context
        if not user_context:
            if flag.rollout_pct == 100:
                return _enabled_value(flag)
            return flag.default_value

        # 3. Check rules (OR logic — any match wins)
        if flag.rules:
            for rule in flag.rules:
                if _match_rule(rule, user_context):
                    return _enabled_value(flag)

        # 4. Rollout percentage
        user_id = user_context.get("user_id") or user_context.get("id")
        if user_id is not None:
            if _check_rollout(str(user_id), flag.key, flag.rollout_pct):
                return _enabled_value(flag)
        else:
            # No user ID for hashing — can only serve 100% rollouts
            if flag.rollout_pct == 100:
                return _enabled_value(flag)
            return flag.default_value

        # 5. Nothing matched
        return flag.default_value
    except Exception:
        return flag.default_value


def _enabled_value(flag: Flag) -> bool | str | int | Any:
    """Return the appropriate 'enabled' value based on flag type."""
    if flag.flag_type == "boolean":
        return True
    return flag.default_value


def _match_rule(rule: Rule, user_context: dict) -> bool:
    """Check if a single rule matches the user context."""
    if rule.attribute not in user_context:
        return False

    context_value = user_context[rule.attribute]

    if context_value is None:
        return False

    if rule.operator == "equals":
        return str(context_value) == str(rule.value)
    elif rule.operator == "not_equals":
        return str(context_value) != str(rule.value)
    elif rule.operator == "contains":
        return str(rule.value) in str(context_value)
    elif rule.operator == "ends_with":
        return str(context_value).endswith(str(rule.value))
    elif rule.operator == "in_list":
        return str(context_value) in rule.value
    elif rule.operator == "gt":
        try:
            return float(context_value) > float(rule.value)
        except (ValueError, TypeError):
            return False
    elif rule.operator == "lt":
        try:
            return float(context_value) < float(rule.value)
        except (ValueError, TypeError):
            return False

    return False


def _check_rollout(user_id: str, flag_key: str, rollout_pct: int) -> bool:
    """Deterministic percentage rollout using consistent hashing."""
    hash_input = f"{user_id}:{flag_key}"
    hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)
    bucket = hash_value % 100
    return bucket < rollout_pct
