import threading

from switchbox.models import Flag, FlagConfig


class FlagCache:
    """Thread-safe in-memory store for flag configs."""

    def __init__(self) -> None:
        self._config: FlagConfig | None = None
        self._lock = threading.Lock()

    def get_config(self) -> FlagConfig | None:
        with self._lock:
            return self._config

    def set_config(self, config: FlagConfig) -> None:
        with self._lock:
            self._config = config

    def get_flag(self, key: str) -> Flag | None:
        with self._lock:
            if self._config is None:
                return None
            return self._config.flags.get(key)

    def get_version(self) -> str | None:
        with self._lock:
            if self._config is None:
                return None
            return self._config.version
