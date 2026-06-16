"""Pure evaluation engine for Switchbox feature flags.

Zero external dependencies — only Python stdlib.
"""

import hashlib
import re
from typing import Any

from switchbox.models import Flag, Rule

# Leading numeric prefix, matching JS parseFloat (e.g. "25px" -> 25, "1e3" -> 1000).
_NUMERIC_PREFIX = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?")


def _js_str(value: Any) -> str:
    """Coerce a value to a string the way JavaScript's String() does — the
    canonical coercion for cross-SDK rule parity (SEC-4, ADR-013):

    - booleans are lowercase ("true"/"false"), not Python's "True"/"False"
    - None becomes "null"
    - an integer-valued float drops its trailing ".0" (JS has no int/float split)
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _to_number(value: Any) -> float | None:
    """Mimic JS parseFloat(String(value)): parse a leading numeric prefix, or
    return None (JS NaN) when there isn't one. Booleans are NaN, matching
    parseFloat("true")."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMERIC_PREFIX.match(str(value).lstrip())
    return float(match.group(0)) if match else None


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

        # 4. Rollout. Resolve the id with a null-only fallback (JS `??`, not
        # `or`): an empty-string user_id is a real id, not falsy.
        user_id = user_context.get("user_id")
        if user_id is None:
            user_id = user_context.get("id")
        if user_id is not None:
            in_bucket = _check_rollout(_js_str(user_id), flag.key, flag.rollout_pct)
            return _enabled_value(flag) if in_bucket else flag.default_value

        # 5. No usable id to hash → only a full (100%) rollout reaches everyone
        # (matches the no-user-context branch above; ADR-008).
        return _enabled_value(flag) if flag.rollout_pct == 100 else flag.default_value
    except Exception:
        return flag.default_value


def _enabled_value(flag: Flag) -> bool | str | int | Any:
    """Return the appropriate 'enabled' value based on flag type."""
    if flag.flag_type == "boolean":
        return True
    return flag.default_value


def _match_rule(rule: Rule, user_context: dict) -> bool:
    """Check if a single rule matches the user context.

    All string comparisons coerce via _js_str (so `equals "true"` matches a
    boolean True, and a None value coerces to "null" rather than never matching
    — matching the JS SDK). gt/lt parse a leading numeric prefix like
    parseFloat. See SEC-4 / ADR-013.
    """
    if rule.attribute not in user_context:
        return False

    context_value = user_context[rule.attribute]

    if rule.operator == "equals":
        return _js_str(context_value) == _js_str(rule.value)
    elif rule.operator == "not_equals":
        return _js_str(context_value) != _js_str(rule.value)
    elif rule.operator == "contains":
        return _js_str(rule.value) in _js_str(context_value)
    elif rule.operator == "ends_with":
        return _js_str(context_value).endswith(_js_str(rule.value))
    elif rule.operator == "in_list":
        return _js_str(context_value) in rule.value
    elif rule.operator == "gt":
        a, b = _to_number(context_value), _to_number(rule.value)
        return a is not None and b is not None and a > b
    elif rule.operator == "lt":
        a, b = _to_number(context_value), _to_number(rule.value)
        return a is not None and b is not None and a < b

    return False


def _check_rollout(user_id: str, flag_key: str, rollout_pct: int) -> bool:
    """Deterministic percentage rollout using consistent hashing."""
    hash_input = f"{user_id}:{flag_key}"
    hash_value = int(hashlib.sha256(hash_input.encode()).hexdigest(), 16)
    bucket = hash_value % 100
    return bucket < rollout_pct
