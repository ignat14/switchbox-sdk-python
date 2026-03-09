import json
from unittest.mock import MagicMock, patch

from switchbox.client import Client

SAMPLE_CONFIG = {
    "version": "2026-04-07T12:00:00Z",
    "flags": {
        "new_dashboard": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "boolean",
            "default_value": False,
            "rules": [],
        },
        "search_version": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "string",
            "default_value": "v1",
            "rules": [],
        },
    },
}


def _mock_urlopen(data):
    """Create a mock that mimics urllib.request.urlopen response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_returns_false_for_nonexistent_flag(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Client(cdn_url="https://example.com/flags.json") as client:
        assert client.enabled("nonexistent") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_get_value_returns_default_for_nonexistent_flag(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Client(cdn_url="https://example.com/flags.json") as client:
        assert client.get_value("nonexistent", default="fallback") == "fallback"


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_works_with_mock_cdn(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Client(cdn_url="https://example.com/flags.json") as client:
        assert client.enabled("new_dashboard", user={"user_id": "1"}) is True
        assert client.get_value("search_version", user={"user_id": "1"}) == "v1"


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_cdn_failure_gracefully(mock_urlopen):
    mock_urlopen.side_effect = Exception("Network error")
    with Client(cdn_url="https://example.com/flags.json") as client:
        # Should return safe defaults, not crash
        assert client.enabled("new_dashboard") is False
        assert client.get_value("search_version", default="v1") == "v1"
