"""Runs the shared cross-SDK parity vectors (SEC-4 / TESTING Phase 5).

The vectors are the canonical `fixtures/parity/parity_vectors.json` (workspace root),
synced into this repo by `python3 fixtures/sync.py`; the JS suite runs the same bytes.
Both must stay green so the two SDKs evaluate identical inputs identically. Edit the
canonical and re-sync — never hand-edit this copy. See the sdk-parity skill and
DECISIONS.md ADR-013 (coercion) + ADR-024 (shared-fixture mechanism).
"""

import json
from pathlib import Path

import pytest

from switchbox.evaluator import _check_rollout, _match_rule, evaluate
from switchbox.models import FlagConfig, Rule

_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "parity" / "parity_vectors.json").read_text()
)


def _bucket(user_id: str, flag_key: str) -> int:
    """Recover the rollout bucket from the real `_check_rollout` code path (which
    the SDK has no public bucket accessor for): it returns `bucket < pct`, so the
    smallest pct that flips it True is `bucket + 1`."""
    return min(p for p in range(101) if _check_rollout(user_id, flag_key, p)) - 1


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


@pytest.mark.parametrize("case", _VECTORS["rollout_bucket"], ids=lambda c: c["name"])
def test_rollout_bucket_vectors(case):
    """The rollout hash itself must produce identical buckets across SDKs —
    sha256(f'{user_id}:{flag_key}') % 100. The JS suite asserts the same values."""
    assert _bucket(case["user_id"], case["flag_key"]) == case["expected"]


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
