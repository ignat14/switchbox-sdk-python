"""Anonymous usage telemetry (MEASUREMENT Phase 1 / ADR-055).

The SDK counts flag *evaluations* locally and flushes a compact per-flag summary
every ~60s to the CDN worker's ingest route, which fans each `(flag, value)`
count into Cloudflare Analytics Engine. This is the value payoff of measurement
(per-flag counts, value distribution, per-flag liveness, stale-flag + outdated-
SDK views) *and* the KV-cost fix — see ARCHITECTURE.md §5/§6.

Invariants (do not weaken):
- **Anonymous.** The only identifier is the environment's SDK key (in the
  request path). Never send identity, user context, or cookies.
- **Aggregate.** One summary per window, not one message per evaluation, so cost
  scales with (flag count x distinct values x flush cadence x client count),
  *not* with evaluation volume.
- **Fail-open.** A flush never blocks or breaks evaluation; any error is
  swallowed (the counts for that window are simply dropped).
- **On by default, opt-out** via ``Switchbox(telemetry=False)``.

The value-repr and top-N-per-flag rules are pinned cross-SDK by the shared
fixture ``fixtures/telemetry/value_reprs.json`` — the JS SDK's ``telemetry.ts``
must produce identical reprs (it carries no evaluation logic, so it is outside
the ``sdk-parity`` skill's evaluator scope, but the emitted shape is pinned).
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("switchbox")

# ~60s flush window, its own request (decoupled from the flag poll). Chosen in
# ARCHITECTURE.md §5; keep in lockstep with the JS SDK.
DEFAULT_FLUSH_INTERVAL = 60
# Distinct values tracked per flag before folding the rest into "$other". Flags
# resolve to ~2 values, so this effectively never bites (ADR-055 open Q closed
# at 10). Guards a pathological flag whose value is derived from user input.
MAX_VALUES_PER_FLAG = 10
# Sentinel bucket for values beyond the cap. Never collides with a real repr:
# every real repr is JSON, so a string value "$other" reprs as '"$other"'.
OTHER_BUCKET = "$other"
FLUSH_TIMEOUT = 10


def value_repr(value: Any) -> str:
    """Canonical string key for a resolved flag value, for count bucketing.

    Compact, key-sorted JSON so it matches the JS SDK's ``valueRepr`` for every
    JSON value: ``true`` / ``false`` / ``42`` / ``"A"`` / ``null`` /
    ``{"a":1,"b":2}`` / non-ASCII like ``"café"`` (``ensure_ascii=False`` keeps
    the raw UTF-8 JS emits — without it Python would escape non-ASCII to
    backslash-u sequences and the same value would bucket under two AE rows
    depending on the SDK). (Residual,
    like ``_js_str``: an integer-valued float in the config — ``1.0`` — reprs
    ``"1.0"`` here vs ``"1"`` in JS; flags don't resolve to such values in
    practice.) Non-JSON values fall back to ``str``.
    """
    try:
        return json.dumps(
            value, separators=(",", ":"), sort_keys=True, ensure_ascii=False
        )
    except (TypeError, ValueError):
        return str(value)


class TelemetryAggregator:
    """Thread-safe in-memory ``counts[flag_key][value_repr] -> n`` accumulator."""

    def __init__(self, max_values: int = MAX_VALUES_PER_FLAG) -> None:
        self._counts: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()
        self._max_values = max_values

    def record(self, flag_key: str, value: Any) -> None:
        repr_ = value_repr(value)
        with self._lock:
            flag = self._counts.setdefault(flag_key, {})
            if repr_ in flag:
                flag[repr_] += 1
            elif len(flag) < self._max_values:
                flag[repr_] = 1
            else:
                flag[OTHER_BUCKET] = flag.get(OTHER_BUCKET, 0) + 1

    def drain(self) -> dict[str, dict[str, int]]:
        """Return the accumulated counts and reset the window atomically."""
        with self._lock:
            counts = self._counts
            self._counts = {}
        return counts


class TelemetryReporter:
    """Background thread that flushes the aggregator's window every interval.

    Flushes on the timer and once more on :meth:`stop`. Never raises.
    """

    def __init__(
        self,
        url: str,
        aggregator: TelemetryAggregator,
        sdk_name: str,
        sdk_version: str,
        interval: int = DEFAULT_FLUSH_INTERVAL,
        timeout: int = FLUSH_TIMEOUT,
    ) -> None:
        self._url = url
        self._aggregator = aggregator
        self._sdk_name = sdk_name
        self._sdk_version = sdk_version
        self._interval = interval
        self._timeout = timeout
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=self._interval):
            self.flush()

    def flush(self) -> None:
        """Drain and send the current window. Fail-open: drops the window on any
        error (never re-queues — that would risk unbounded growth and double
        counting on a transient outage)."""
        counts = self._aggregator.drain()
        if not counts:
            return
        try:
            payload = json.dumps(
                {
                    "sdk_name": self._sdk_name,
                    "sdk_version": self._sdk_version,
                    "flags": counts,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self._url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"{self._sdk_name}/{self._sdk_version}",
                },
            )
            with urllib.request.urlopen(req, timeout=self._timeout):
                pass
        except Exception as exc:  # noqa: BLE001 — telemetry must never surface
            logger.debug("Telemetry flush failed (dropped window): %s", exc)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        # Final best-effort flush of the last partial window on shutdown.
        self.flush()
