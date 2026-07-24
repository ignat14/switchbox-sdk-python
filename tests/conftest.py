from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _no_telemetry_network():
    """Telemetry is on by default (MEASUREMENT Phase 1), and it flushes over its
    own ``switchbox.telemetry`` urllib import — separate from the sync worker's,
    which most tests mock. Neutralize the telemetry flush globally so no unit
    test makes a real HTTP call on ``close()``. Tests that assert on telemetry
    patch ``switchbox.telemetry.urllib.request.urlopen`` themselves (their patch
    stacks on top of this one)."""
    with patch("switchbox.telemetry.urllib.request.urlopen") as mock:
        resp = MagicMock()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        mock.return_value = resp
        yield mock
