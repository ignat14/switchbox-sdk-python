"""Runs the shared cross-SDK parity vectors (SEC-4).

`parity_vectors.json` is byte-identical to the copy in switchbox-sdk-js; the JS
suite runs the same file. Both must stay green so the two SDKs evaluate identical
inputs identically. See the sdk-parity skill and DECISIONS.md ADR-013.
"""

import json
from pathlib import Path

import pytest

from switchbox.evaluator import _match_rule, evaluate
from switchbox.models import FlagConfig, Rule

_VECTORS = json.loads((Path(__file__).parent / "parity_vectors.json").read_text())


def _flag_from(case):
    """Build a Flag from a vector's CDN-shaped flag dict (reuses the real parser)."""
    config = FlagConfig.from_dict({"flags": {case["flag_key"]: case["flag"]}})
    return config.flags[case["flag_key"]]


@pytest.mark.parametrize("case", _VECTORS["rule_match"], ids=lambda c: c["name"])
def test_rule_match_vectors(case):
    rule = Rule(**case["rule"])
    assert _match_rule(rule, case["context"]) == case["expected"]


@pytest.mark.parametrize("case", _VECTORS["evaluate"], ids=lambda c: c["name"])
def test_evaluate_vectors(case):
    assert evaluate(_flag_from(case), case["user"]) == case["expected"]


def test_user_id_resolution_ignores_id_when_user_id_present():
    """Null-only (`??`) fallback: `user_id` wins over `id`, so two contexts with
    the same user_id but different id must bucket — and therefore resolve —
    identically. (An empty-string user_id is a real id, not falsy.)"""
    flag = FlagConfig.from_dict(
        {
            "flags": {
                "f": {
                    "enabled": True,
                    "rollout_pct": 50,
                    "flag_type": "boolean",
                    "default_value": False,
                    "rules": [],
                }
            }
        }
    ).flags["f"]
    a = evaluate(flag, {"user_id": "stable", "id": "aaa"})
    b = evaluate(flag, {"user_id": "stable", "id": "bbb"})
    assert a == b
