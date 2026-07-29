import json
import time
from unittest.mock import MagicMock, patch

from switchbox.client import Switchbox

TEST_SDK_KEY = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHM"
TEST_CDN = "https://example.com"

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


def _mock_urlopen(data, etag=None):
    """Create a mock that mimics urllib.request.urlopen response."""
    resp = MagicMock()
    resp.read.return_value = json.dumps(data).encode("utf-8")
    resp.headers.get.return_value = etag
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_returns_false_for_nonexistent_flag(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("nonexistent") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_get_value_returns_default_for_nonexistent_flag(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.get_value("nonexistent", default="fallback") == "fallback"


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_works_with_mock_cdn(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("new_dashboard", user={"user_id": "1"}) is True
        assert client.get_value("search_version", user={"user_id": "1"}) == "v1"


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_cdn_failure_gracefully(mock_urlopen):
    mock_urlopen.side_effect = Exception("Network error")
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        # Should return safe defaults, not crash
        assert client.enabled("new_dashboard") is False
        assert client.get_value("search_version", default="v1") == "v1"


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_get_all_flags_empty_when_no_flags(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen({"version": "v1", "flags": {}})
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.get_all_flags() == {}


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_invalid_json(mock_urlopen):
    resp = MagicMock()
    resp.read.return_value = b"not json"
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("any_flag") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_404(mock_urlopen):
    from urllib.error import HTTPError
    mock_urlopen.side_effect = HTTPError("https://example.com", 404, "Not Found", {}, None)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("any") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_500(mock_urlopen):
    from urllib.error import HTTPError
    mock_urlopen.side_effect = HTTPError("https://example.com", 500, "Server Error", {}, None)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("any") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_handles_timeout(mock_urlopen):
    from urllib.error import URLError
    mock_urlopen.side_effect = URLError("timed out")
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as client:
        assert client.enabled("any") is False


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_keeps_cached_data_after_failure(mock_urlopen):
    """First call succeeds, second fails — client should keep using cached data."""
    good_resp = _mock_urlopen(SAMPLE_CONFIG)
    mock_urlopen.return_value = good_resp
    client = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, poll_interval=9999)
    assert client.enabled("new_dashboard") is True

    # Now simulate failure on next poll
    mock_urlopen.side_effect = Exception("Network down")
    # The sync worker won't poll for 9999s, but the cache should still work
    assert client.enabled("new_dashboard") is True
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_context_manager(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN) as c:
        assert c.enabled("new_dashboard") is True
    # After exiting context, sync should be stopped
    assert c._sync._stop_event.is_set()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_close_stops_sync(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    c = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
    c.close()
    assert c._sync._stop_event.is_set()


# --- REF-8: conditional fetch (ETag / If-None-Match) ---


def _sent_if_none_match(mock_urlopen, call_index):
    """The If-None-Match header on the nth urlopen call (urllib capitalizes it)."""
    request = mock_urlopen.call_args_list[call_index][0][0]
    return request.get_header("If-none-match")


@patch("switchbox.sync.urllib.request.urlopen")
def test_first_fetch_has_no_validator_then_echoes_the_etag(mock_urlopen):
    """Nothing to validate against on the first fetch; every poll after it sends
    the ETag back so an unchanged config costs no payload."""
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG, etag='"abc"')
    with Switchbox(
        sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, poll_interval=9999
    ) as client:
        assert _sent_if_none_match(mock_urlopen, 0) is None
        client._sync._poll()
        assert _sent_if_none_match(mock_urlopen, 1) == '"abc"'


@patch("switchbox.sync.urllib.request.urlopen")
def test_304_keeps_the_cached_config_and_is_not_an_error(mock_urlopen):
    """urllib raises on any non-2xx, but a 304 is the success case: config
    unchanged, cache kept, no on_error callback."""
    from urllib.error import HTTPError

    errors = []
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG, etag='"abc"')
    with Switchbox(
        sdk_key=TEST_SDK_KEY,
        cdn_base_url=TEST_CDN,
        poll_interval=9999,
        on_error=errors.append,
    ) as client:
        version = client._cache.get_version()
        mock_urlopen.side_effect = HTTPError(TEST_CDN, 304, "Not Modified", {}, None)
        client._sync._poll()

        assert client._cache.get_version() == version
        assert client.enabled("new_dashboard", user={"user_id": "1"}) is True
        assert errors == []


@patch("switchbox.sync.urllib.request.urlopen")
def test_an_unparsed_body_does_not_leave_a_validator_behind(mock_urlopen):
    """A 200 whose body never reaches the cache must not have its ETag
    remembered: sending that validator back would earn a 304 forever, freezing
    the client on defaults until the next publish. Kept identical to the JS SDK."""
    # Valid JSON, wrong shape — parsed, then fails on the way to the cache.
    mock_urlopen.return_value = _mock_urlopen([], etag='"broken"')
    client = Switchbox(
        sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, poll_interval=9999
    )
    assert client.ready is False

    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG, etag='"abc"')
    client._sync._poll()
    assert _sent_if_none_match(mock_urlopen, 1) is None
    # …so the retry is a full fetch and the client recovers.
    assert client.enabled("new_dashboard", user={"user_id": "1"}) is True
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_a_cdn_without_etags_is_never_sent_a_validator(mock_urlopen):
    """Local nginx / the cdn_output fallback issue no ETag — we must not send a
    validator the current CDN never handed us."""
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    with Switchbox(
        sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, poll_interval=9999
    ) as client:
        client._sync._poll()
        assert _sent_if_none_match(mock_urlopen, 1) is None


# --- SEC-9: block_on_init ---


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_block_on_init_true_ready_immediately(mock_urlopen):
    """Default: the first fetch is synchronous, so the client is ready on return."""
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    client = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
    assert client.ready is True
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_block_on_init_false_does_not_raise_on_failure(mock_urlopen):
    """Non-blocking construction never blocks or raises on a down CDN — flag
    checks just fall back to defaults until the background fetch succeeds."""
    mock_urlopen.side_effect = Exception("CDN down")
    client = Switchbox(
        sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, block_on_init=False
    )
    assert client.enabled("new_dashboard") is False
    assert client.get_value("search_version", default="v1") == "v1"
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_block_on_init_false_becomes_ready(mock_urlopen):
    """With block_on_init=False the config still arrives — on the background
    thread — so the client becomes ready shortly after construction."""
    mock_urlopen.return_value = _mock_urlopen(SAMPLE_CONFIG)
    client = Switchbox(
        sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, block_on_init=False
    )
    deadline = time.monotonic() + 5
    while not client.ready and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client.ready is True
    assert client.enabled("new_dashboard", user={"user_id": "1"}) is True
    client.close()
