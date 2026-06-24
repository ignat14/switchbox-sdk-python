import json
import logging
import threading
import urllib.error
import urllib.request
from typing import Callable

from switchbox.cache import FlagCache
from switchbox.exceptions import ConfigFetchError
from switchbox.models import FlagConfig

logger = logging.getLogger("switchbox")


class SyncWorker:
    """Background thread that polls the CDN for updated flag configs."""

    def __init__(
        self,
        cdn_url: str,
        cache: FlagCache,
        interval: int = 30,
        on_error: Callable[[Exception], None] | None = None,
        timeout: int = 10,
    ) -> None:
        self._cdn_url = cdn_url
        self._cache = cache
        self._interval = interval
        self._on_error = on_error
        self._timeout = timeout
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, block: bool = True) -> None:
        """Start polling. Fetch the first config, then poll in the background.

        ``block=True`` (default): fetch synchronously before returning, so the
        client is ``ready`` the moment construction completes (at the cost of
        blocking up to ``timeout`` if the CDN is slow/unreachable).

        ``block=False`` (SEC-9): return immediately and fetch the first config on
        the background thread, so a slow CDN never stalls app startup. The client
        starts not-ready; poll ``client.ready`` (or rely on flag defaults) until
        the first fetch lands.
        """
        if block:
            # Initial synchronous fetch — block until we have configs.
            self._poll()
            poll_immediately = False
        else:
            # Defer the first fetch onto the background thread so __init__ returns
            # right away rather than waiting on the network.
            poll_immediately = True

        self._thread = threading.Thread(
            target=self._run, args=(poll_immediately,), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread gracefully."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self, poll_immediately: bool = False) -> None:
        """Main loop for the background thread.

        ``poll_immediately`` does one fetch before the first interval wait — used
        by non-blocking start so the config still arrives ASAP rather than after a
        full poll interval.
        """
        if poll_immediately:
            try:
                self._poll()
            except Exception as exc:
                logger.warning("Unexpected error in initial sync: %s", exc)
        while not self._stop_event.wait(timeout=self._interval):
            try:
                self._poll()
            except Exception as exc:
                logger.warning("Unexpected error in sync loop: %s", exc)

    def _poll(self) -> None:
        """Fetch config from CDN, parse, and update cache if changed."""
        try:
            req = urllib.request.Request(
                self._cdn_url,
                headers={"User-Agent": "switchbox-python/0.6.0"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # Skip parsing if version hasn't changed
            new_version = data.get("version", "")
            current_version = self._cache.get_version()
            if current_version and new_version == current_version:
                return

            config = FlagConfig.from_dict(data)
            self._cache.set_config(config)
            logger.debug("Updated flag config to version %s", config.version)

        except urllib.error.HTTPError as exc:
            self._handle_error(f"HTTP error {exc.code} {exc.reason}", exc)
        except urllib.error.URLError as exc:
            self._handle_error(f"URL error: {exc.reason}", exc)
        except json.JSONDecodeError as exc:
            self._handle_error(f"Invalid JSON: {exc}", exc)
        except TimeoutError as exc:
            self._handle_error(f"Timeout: {exc}", exc)
        except Exception as exc:
            self._handle_error(str(exc), exc)

    def _handle_error(self, message: str, exc: Exception) -> None:
        """Log a fetch error and notify the on_error callback if set."""
        logger.warning("Failed to fetch flag config from %s: %s", self._cdn_url, message)
        if self._on_error is not None:
            try:
                self._on_error(ConfigFetchError(str(exc)))
            except Exception:
                pass
