import json
from pathlib import Path
from unittest.mock import patch

from switchbox.client import Switchbox
from switchbox.telemetry import (
    MAX_VALUES_PER_FLAG,
    OTHER_BUCKET,
    TelemetryAggregator,
    TelemetryReporter,
    value_repr,
)

FIXTURE = Path(__file__).parent / "fixtures" / "telemetry" / "value_reprs.json"

TEST_SDK_KEY = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHM"
TEST_CDN = "https://example.com"

SAMPLE_CONFIG = {
    "version": "v1",
    "flags": {
        "new_dashboard": {
            "enabled": True,
            "rollout_pct": 100,
            "flag_type": "boolean",
            "default_value": False,
            "rules": [],
        },
    },
}


# --- value_repr: cross-SDK contract (shared fixture) ---


def test_value_repr_matches_shared_fixture():
    """Pinned against the canonical fixture the JS SDK's `valueRepr` also runs."""
    data = json.loads(FIXTURE.read_text())
    assert data["max_values_per_flag"] == MAX_VALUES_PER_FLAG
    assert data["other_bucket"] == OTHER_BUCKET
    for case in data["cases"]:
        assert value_repr(case["value"]) == case["repr"], case


# --- aggregator ---


def test_aggregator_counts_and_drains():
    agg = TelemetryAggregator()
    agg.record("f", True)
    agg.record("f", True)
    agg.record("f", False)
    agg.record("g", "A")
    assert agg.drain() == {"f": {"true": 2, "false": 1}, "g": {'"A"': 1}}
    # drain resets the window
    assert agg.drain() == {}


def test_aggregator_caps_distinct_values_into_other():
    agg = TelemetryAggregator()
    # MAX distinct values fill the map, everything beyond folds into $other.
    for i in range(MAX_VALUES_PER_FLAG):
        agg.record("f", f"v{i}")
    agg.record("f", "overflow_a")
    agg.record("f", "overflow_b")
    counts = agg.drain()["f"]
    assert len([k for k in counts if k != OTHER_BUCKET]) == MAX_VALUES_PER_FLAG
    assert counts[OTHER_BUCKET] == 2


def test_aggregator_constructor_flag_key_is_safe():
    """A flag key colliding with a dict/proto name must not blow up (parity with
    the JS null-prototype maps)."""
    agg = TelemetryAggregator()
    agg.record("constructor", True)
    assert agg.drain() == {"constructor": {"true": 1}}


# --- reporter ---


def test_reporter_flush_posts_expected_payload():
    agg = TelemetryAggregator()
    agg.record("f", True)
    reporter = TelemetryReporter(
        "https://example.com/key/telemetry", agg, "switchbox-python", "9.9.9"
    )
    with patch("switchbox.telemetry.urllib.request.urlopen") as mock:
        reporter.flush()
    assert mock.called
    req = mock.call_args.args[0]
    assert req.full_url == "https://example.com/key/telemetry"
    assert req.method == "POST"
    body = json.loads(req.data.decode("utf-8"))
    assert body == {
        "sdk_name": "switchbox-python",
        "sdk_version": "9.9.9",
        "flags": {"f": {"true": 1}},
    }
    # window drained → a second flush sends nothing
    with patch("switchbox.telemetry.urllib.request.urlopen") as mock2:
        reporter.flush()
    assert not mock2.called


def test_reporter_flush_is_fail_open():
    agg = TelemetryAggregator()
    agg.record("f", True)
    reporter = TelemetryReporter("https://x/telemetry", agg, "sdk", "1")
    with patch(
        "switchbox.telemetry.urllib.request.urlopen",
        side_effect=Exception("network down"),
    ):
        reporter.flush()  # must not raise


# --- client integration ---


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_telemetry_on_by_default(mock_urlopen, _no_telemetry_network):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.read.return_value = json.dumps(SAMPLE_CONFIG).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    client = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN)
    assert client._telemetry is not None
    client.enabled("new_dashboard", user={"user_id": "1"})
    assert client._telemetry.drain() == {"new_dashboard": {"true": 1}}
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_telemetry_opt_out(mock_urlopen):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.read.return_value = json.dumps(SAMPLE_CONFIG).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    client = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, telemetry=False)
    assert client._telemetry is None
    assert client._reporter is None
    client.enabled("new_dashboard", user={"user_id": "1"})  # must not blow up
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_on_evaluation_fires(mock_urlopen):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.read.return_value = json.dumps(SAMPLE_CONFIG).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    events = []
    client = Switchbox(
        sdk_key=TEST_SDK_KEY,
        cdn_base_url=TEST_CDN,
        on_evaluation=lambda k, v, u: events.append((k, v, u)),
    )
    user = {"user_id": "1"}
    client.enabled("new_dashboard", user)
    client.get_value("nonexistent", user, default="d")  # absent → fires with fallback
    assert events == [("new_dashboard", True, user), ("nonexistent", "d", user)]
    client.close()


@patch("switchbox.sync.urllib.request.urlopen")
def test_client_on_evaluation_error_never_breaks_eval(mock_urlopen):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.read.return_value = json.dumps(SAMPLE_CONFIG).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    def boom(*args):
        raise RuntimeError("hook exploded")

    client = Switchbox(sdk_key=TEST_SDK_KEY, cdn_base_url=TEST_CDN, on_evaluation=boom)
    assert client.enabled("new_dashboard", {"user_id": "1"}) is True  # ADR-043
    client.close()
