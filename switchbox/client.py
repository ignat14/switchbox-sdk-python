from __future__ import annotations

from typing import Any, Callable

from switchbox.cache import FlagCache
from switchbox.evaluator import evaluate
from switchbox.sync import SyncWorker

CDN_BASE_URL = "https://cdn.switchbox.dev"


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
        poll_interval: int = 30,
        on_error: Callable[[Exception], None] | None = None,
        timeout: int = 10,
        cdn_base_url: str | None = None,
        block_on_init: bool = True,
    ) -> None:
        base = cdn_base_url or CDN_BASE_URL
        cdn_url = f"{base}/{sdk_key}/flags.json"
        self._cache = FlagCache()
        self._sync = SyncWorker(cdn_url, self._cache, poll_interval, on_error, timeout=timeout)
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
        their fallback and how they coerce the result.
        """
        flag = self._cache.get_flag(flag_key)
        if flag is None:
            return fallback
        return evaluate(flag, user)

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
        """Stop the background sync. Call on shutdown."""
        self._sync.stop()

    def __enter__(self) -> Switchbox:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
