"""Translation, context-mapping, error-mapping and lifecycle tests.

The provider carries zero evaluation logic, so these tests run it over a REAL
Switchbox client against a mocked CDN (the same urlopen pattern as the core
suite) — pinning the translation onto real local evaluation, not a fake.
"""

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from openfeature.exception import (
    ErrorCode,
    FlagNotFoundError,
    ProviderNotReadyError,
    TypeMismatchError,
)
from switchbox_openfeature import SwitchboxProvider, to_user_context

from switchbox import Switchbox

TEST_SDK_KEY = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHM"
TEST_CDN = "https://example.com"

CONFIG = {
    "version": "2026-07-12T12:00:00Z",
    "flags": {
        "bool_flag": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "boolean",
            "default_value": False,
            "rules": [],
        },
        "greeting": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "string",
            "default_value": "Shop",
            "enabled_value": "Buy now",
            "rules": [],
        },
        "limit": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "number",
            "default_value": 10,
            "enabled_value": 25,
            "rules": [],
        },
        "theme": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "json",
            "default_value": {"mode": "light"},
            "enabled_value": {"mode": "dark"},
            "rules": [],
        },
        "pro_only": {
            "enabled": True,
            "rollout_pct": 0,
            "flag_type": "string",
            "default_value": "basic",
            "enabled_value": "pro",
            "rules": [
                {"conditions": [{"attribute": "plan", "operator": "equals", "value": "pro"}]}
            ],
        },
    },
}

PRO_USER = EvaluationContext(targeting_key="user-1", attributes={"plan": "pro"})


def _mock_urlopen(data):
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture
def provider():
    with patch("switchbox.sync.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_urlopen(CONFIG)
        p = SwitchboxProvider(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
        yield p
        p.shutdown()


def test_to_user_context_maps_targeting_key_to_user_id():
    ctx = EvaluationContext(targeting_key="u1", attributes={"plan": "pro"})
    assert to_user_context(ctx) == {"user_id": "u1", "plan": "pro"}


def test_to_user_context_empty_context_is_no_user():
    assert to_user_context(None) is None
    assert to_user_context(EvaluationContext()) is None


def test_to_user_context_attributes_only():
    assert to_user_context(EvaluationContext(attributes={"plan": "pro"})) == {"plan": "pro"}


def test_to_user_context_targeting_key_beats_a_user_id_attribute():
    ctx = EvaluationContext(targeting_key="u1", attributes={"user_id": "legacy-7"})
    assert to_user_context(ctx) == {"user_id": "u1"}


def test_constructor_requires_exactly_one_of_client_or_options():
    with pytest.raises(ValueError):
        SwitchboxProvider()
    with pytest.raises(ValueError):
        SwitchboxProvider(client=MagicMock(spec=Switchbox), sdk_key="x")


def test_resolves_each_flag_type(provider):
    assert provider.resolve_boolean_details("bool_flag", False, PRO_USER).value is True
    assert provider.resolve_string_details("greeting", "x", PRO_USER).value == "Buy now"
    assert provider.resolve_integer_details("limit", 0, PRO_USER).value == 25
    float_details = provider.resolve_float_details("limit", 0.0, PRO_USER)
    assert float_details.value == 25.0
    assert isinstance(float_details.value, float)
    assert provider.resolve_object_details("theme", {}, PRO_USER).value == {"mode": "dark"}


def test_targeting_rules_see_mapped_context_attributes(provider):
    assert provider.resolve_string_details("pro_only", "x", PRO_USER).value == "pro"
    free_user = EvaluationContext(targeting_key="user-1")
    assert provider.resolve_string_details("pro_only", "x", free_user).value == "basic"


def test_missing_flag_raises_flag_not_found(provider):
    with pytest.raises(FlagNotFoundError):
        provider.resolve_boolean_details("nope", False, PRO_USER)


def test_wrong_type_raises_type_mismatch(provider):
    with pytest.raises(TypeMismatchError):
        provider.resolve_boolean_details("greeting", False, PRO_USER)
    with pytest.raises(TypeMismatchError):
        # bool is an int in Python; the provider must not leak that quirk.
        provider.resolve_integer_details("bool_flag", 0, PRO_USER)
    with pytest.raises(TypeMismatchError):
        provider.resolve_object_details("limit", {}, PRO_USER)


def test_end_to_end_through_the_openfeature_api(provider):
    """The marketing-visible claim: app code written only against OpenFeature."""
    api.set_provider(provider)
    try:
        client = api.get_client()
        assert client.get_boolean_value("bool_flag", False, PRO_USER) is True
        assert client.get_string_value("greeting", "x", PRO_USER) == "Buy now"

        # Errors surface as the CODE default plus an error code — never a guess.
        details = client.get_string_details("nope", "code-default", PRO_USER)
        assert details.value == "code-default"
        assert details.error_code == ErrorCode.FLAG_NOT_FOUND

        mismatch = client.get_boolean_details("greeting", True, PRO_USER)
        assert mismatch.value is True
        assert mismatch.error_code == ErrorCode.TYPE_MISMATCH
    finally:
        api.shutdown()


def test_initialize_raises_when_first_fetch_failed():
    with patch("switchbox.sync.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("CDN unreachable")
        provider = SwitchboxProvider(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
        try:
            with pytest.raises(ProviderNotReadyError):
                provider.initialize(EvaluationContext())
        finally:
            provider.shutdown()


def test_owned_client_is_closed_on_shutdown():
    with patch("switchbox.sync.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_urlopen(CONFIG)
        provider = SwitchboxProvider(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
        provider._client.close = MagicMock()
        provider.shutdown()
        provider._client.close.assert_called_once()


def test_shared_client_is_left_alone():
    shared = MagicMock(spec=Switchbox)
    provider = SwitchboxProvider(client=shared)
    provider.initialize(EvaluationContext())  # caller's readiness, not ours
    provider.shutdown()
    shared.close.assert_not_called()
