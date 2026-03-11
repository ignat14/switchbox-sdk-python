import threading

from switchbox.cache import FlagCache
from switchbox.models import Flag, FlagConfig


def _make_config(version="v1"):
    return FlagConfig(
        version=version,
        flags={
            "flag_a": Flag(
                key="flag_a",
                enabled=True,
                rollout_pct=100,
                flag_type="boolean",
                default_value=False,
                rules=[],
            ),
        },
    )


def test_cache_starts_empty():
    cache = FlagCache()
    assert cache.get_config() is None
    assert cache.get_version() is None
    assert cache.get_flag("anything") is None


def test_set_and_get_config():
    cache = FlagCache()
    config = _make_config()
    cache.set_config(config)
    assert cache.get_config() is config
    assert cache.get_version() == "v1"


def test_get_flag_returns_correct_flag():
    cache = FlagCache()
    cache.set_config(_make_config())
    flag = cache.get_flag("flag_a")
    assert flag is not None
    assert flag.key == "flag_a"


def test_get_flag_returns_none_for_missing_key():
    cache = FlagCache()
    cache.set_config(_make_config())
    assert cache.get_flag("nonexistent") is None


def test_thread_safety():
    """Concurrent reads and writes should not raise or corrupt data."""
    cache = FlagCache()
    errors = []

    def writer():
        try:
            for i in range(200):
                cache.set_config(_make_config(version=f"v{i}"))
        except Exception as e:
            errors.append(e)

    def reader():
        try:
            for _ in range(200):
                cache.get_config()
                cache.get_flag("flag_a")
                cache.get_version()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer) for _ in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []


def test_get_version_returns_version():
    cache = FlagCache()
    cache.set_config(_make_config(version="2026-01-01T00:00:00Z"))
    assert cache.get_version() == "2026-01-01T00:00:00Z"
