from typing import Any, Callable

from switchbox.cache import FlagCache
from switchbox.evaluator import evaluate
from switchbox.sync import SyncWorker


class Client:
    """Switchbox feature flag client.

    Fetches flag configs from a CDN and evaluates them locally.

    Usage::

        client = Client(cdn_url="https://cdn.example.com/proj/production/flags.json")
        if client.enabled("new_feature", user={"user_id": "42"}):
            ...
        client.close()

    Or as a context manager::

        with Client(cdn_url="...") as client:
            if client.enabled("new_feature"):
                ...
    """

    def __init__(
        self,
        cdn_url: str,
        poll_interval: int = 30,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._cache = FlagCache()
        self._sync = SyncWorker(cdn_url, self._cache, poll_interval, on_error)
        self._sync.start()

    def enabled(self, flag_key: str, user: dict | None = None) -> bool:
        """Check if a boolean flag is enabled for a user.

        Returns False if the flag doesn't exist (safe default).
        """
        flag = self._cache.get_flag(flag_key)
        if flag is None:
            return False
        result = evaluate(flag, user)
        return bool(result)

    def get_value(
        self, flag_key: str, user: dict | None = None, default: Any = None
    ) -> Any:
        """Get the resolved value of any flag type.

        Returns *default* if the flag doesn't exist.
        """
        flag = self._cache.get_flag(flag_key)
        if flag is None:
            return default
        return evaluate(flag, user)

    def get_all_flags(self, user: dict | None = None) -> dict[str, Any]:
        """Get all flag values resolved for a user."""
        config = self._cache.get_config()
        if config is None:
            return {}
        return {key: evaluate(flag, user) for key, flag in config.flags.items()}

    def close(self) -> None:
        """Stop the background sync. Call on shutdown."""
        self._sync.stop()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
