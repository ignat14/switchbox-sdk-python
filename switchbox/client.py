from __future__ import annotations

from typing import Any, Callable

from switchbox._version import __version__
from switchbox.cache import FlagCache
from switchbox.evaluator import evaluate
from switchbox.sync import SyncWorker
from switchbox.telemetry import TelemetryAggregator, TelemetryReporter

CDN_BASE_URL = "https://cdn.switchbox.dev"
SDK_NAME = "switchbox-python"


class Switchbox:
    """Switchbox feature flag client.

    Fetches flag configs from a CDN and evaluates them locally.

    Usage::

        client = Switchbox(sdk_key="your-sdk-key")
        if client.enabled("new_feature", user={"user_id": "42"}):
            ...
        client.close()

    Or as a context manager::

        with Switchbox(sdk_key="your-sdk-key") as client:
            if client.enabled("new_feature"):
                ...
    """

    def __init__(
        self,
        sdk_key: str,
        poll_interval: int = 10,
        on_error: Callable[[Exception], None] | None = None,
        timeout: int = 10,
        cdn_base_url: str | None = None,
        block_on_init: bool = True,
        telemetry: bool = True,
        on_evaluation: Callable[[str, Any, dict | None], None] | None = None,
    ) -> None:
        base = cdn_base_url or CDN_BASE_URL
        cdn_url = f"{base}/{sdk_key}/flags.json"
        self._cache = FlagCache()
        self._on_evaluation = on_evaluation
        self._on_error = on_error
        self._sync = SyncWorker(cdn_url, self._cache, poll_interval, on_error, timeout=timeout)

        # Anonymous usage telemetry (MEASUREMENT Phase 1 / ADR-055): on by
        # default, `telemetry=False` opts out. Counts evaluations locally and
        # flushes an aggregate summary to the CDN worker's ingest route on its
        # own ~60s cadence. Env key only — never identity/context. Fail-open.
        self._telemetry: TelemetryAggregator | None = None
        self._reporter: TelemetryReporter | None = None
        if telemetry:
            self._telemetry = TelemetryAggregator()
            self._reporter = TelemetryReporter(
                f"{base}/{sdk_key}/telemetry",
                self._telemetry,
                SDK_NAME,
                __version__,
            )
            self._reporter.start()

        # block_on_init=True (default): the constructor performs the first fetch
        # synchronously, so the client is `ready` on return. Set False to fetch in
        # the background instead — the constructor returns immediately and never
        # blocks on a slow/unreachable CDN (SEC-9). See `ready`.
        self._sync.start(block=block_on_init)

    @property
    def ready(self) -> bool:
        """Return True when configs have been loaded at least once."""
        return self._cache.get_config() is not None

    def _eval_flag(self, flag_key: str, user: dict | None, fallback: Any) -> Any:
        """Look up a flag and evaluate it, returning *fallback* if it's absent.

        The shared path behind enabled()/get_value() — they differ only in
        their fallback and how they coerce the result. Records usage telemetry
        (real evaluations only, not absent-flag fallbacks) and fires the
        ``on_evaluation`` hook (always, matching the JS SDK).
        """
        flag = self._cache.get_flag(flag_key)
        if flag is None:
            result = fallback
        else:
            result = evaluate(flag, user)
            if self._telemetry is not None:
                self._telemetry.record(flag_key, result)
        if self._on_evaluation is not None:
            try:
                self._on_evaluation(flag_key, result, user)
            except Exception as exc:
                # a caller's hook must never break evaluation (ADR-043) —
                # surfaced through on_error so the failure isn't invisible
                self._report_hook_error(exc)
        return result

    def _report_hook_error(self, exc: Exception) -> None:
        """Surface a caller-supplied hook's exception via on_error (never raise)."""
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                pass  # the on_error callback itself must never break evaluation

    def enabled(self, flag_key: str, user: dict | None = None) -> bool:
        """Check if a boolean flag is enabled for a user.

        Returns False if the flag doesn't exist (safe default).
        """
        return bool(self._eval_flag(flag_key, user, False))

    def get_value(
        self, flag_key: str, user: dict | None = None, default: Any = None
    ) -> Any:
        """Get the resolved value of any flag type.

        Returns *default* if the flag doesn't exist.
        """
        return self._eval_flag(flag_key, user, default)

    def get_all_flags(self, user: dict | None = None) -> dict[str, Any]:
        """Get all flag values resolved for a user."""
        config = self._cache.get_config()
        if config is None:
            return {}
        return {key: evaluate(flag, user) for key, flag in config.flags.items()}

    def close(self) -> None:
        """Stop the background sync + telemetry. Call on shutdown."""
        self._sync.stop()
        if self._reporter is not None:
            self._reporter.stop()  # final best-effort telemetry flush

    def __enter__(self) -> Switchbox:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
