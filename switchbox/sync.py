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

    def start(self) -> None:
        """Fetch configs synchronously first, then start background polling."""
        # Initial synchronous fetch — block until we have configs
        self._poll()

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background polling thread gracefully."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        """Main loop for the background thread."""
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
                headers={"User-Agent": "switchbox-python/0.1.0"},
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
            logger.warning("HTTP error fetching flag config from %s: %s %s", self._cdn_url, exc.code, exc.reason)
            if self._on_error is not None:
                try:
                    self._on_error(ConfigFetchError(str(exc)))
                except Exception:
                    pass
        except urllib.error.URLError as exc:
            logger.warning("URL error fetching flag config from %s: %s", self._cdn_url, exc.reason)
            if self._on_error is not None:
                try:
                    self._on_error(ConfigFetchError(str(exc)))
                except Exception:
                    pass
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in flag config from %s: %s", self._cdn_url, exc)
            if self._on_error is not None:
                try:
                    self._on_error(ConfigFetchError(str(exc)))
                except Exception:
                    pass
        except TimeoutError as exc:
            logger.warning("Timeout fetching flag config from %s: %s", self._cdn_url, exc)
            if self._on_error is not None:
                try:
                    self._on_error(ConfigFetchError(str(exc)))
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Failed to fetch flag config from %s: %s", self._cdn_url, exc)
            if self._on_error is not None:
                try:
                    self._on_error(ConfigFetchError(str(exc)))
                except Exception:
                    pass
