# Switchbox

Feature flags served from a CDN. Zero dependencies. Sub-millisecond evaluation.

[![PyPI](https://img.shields.io/pypi/v/switchbox-flags)](https://pypi.org/project/switchbox-flags/)
[![Python](https://img.shields.io/pypi/pyversions/switchbox-flags)](https://pypi.org/project/switchbox-flags/)
[![License](https://img.shields.io/pypi/l/switchbox-flags)](https://github.com/ignat14/switchbox-sdk-python/blob/main/LICENSE)

## What is this?

Switchbox is a feature flag SDK that reads configs from a CDN instead of an API server. Flag configs are static JSON files on the edge — your app fetches them directly. Rules and rollouts are evaluated locally in the SDK, not on a server.

## Install

```
pip install switchbox-flags
```

## Quick Start

```python
from switchbox import Client

client = Client(sdk_key="your-sdk-key-from-dashboard")

if client.enabled("new_checkout", user={"user_id": "42"}):
    show_new_checkout()

client.close()
```

## Features

- **CDN-first** — fetches flag configs from static JSON on a CDN, no server in the read path
- **Zero dependencies** — Python stdlib only, nothing to install beyond the package
- **Sub-millisecond evaluation** — rules and rollouts evaluated locally in-process
- **Background polling** — syncs configs every 30 seconds (configurable)
- **Offline resilient** — keeps working on cached configs if the CDN is unreachable
- **Thread-safe** — safe to use from multiple threads
- **Context manager** — supports `with Client(...) as client:` for automatic cleanup

## Usage

### Boolean Flags

```python
from switchbox import Client

client = Client(sdk_key="your-sdk-key-from-dashboard")

if client.enabled("dark_mode"):
    enable_dark_mode()

client.close()
```

### String / Number Flags

```python
version = client.get_value("search_algorithm", user={"user_id": "42"}, default="v1")
print(f"Using search {version}")

max_results = client.get_value("max_search_results", user={"user_id": "42"}, default=10)
```

### All Flags at Once

```python
flags = client.get_all_flags(user={"user_id": "42"})
# {"dark_mode": True, "search_algorithm": "v2", "max_search_results": 50}
```

### Targeting Rules

Pass a `user` dict with attributes you want to target on. Rules are configured in the dashboard.

```python
user = {
    "user_id": "42",
    "email": "alice@company.com",
    "plan": "enterprise",
    "age": "30",
}

# Flag with rule: email ends_with "@company.com"
client.enabled("internal_tools", user=user)  # True

# Flag with rule: plan equals "enterprise"
client.enabled("advanced_analytics", user=user)  # True

# Flag with rule: plan in_list ["pro", "enterprise"]
client.enabled("export_csv", user=user)  # True
```

Supported operators: `equals`, `not_equals`, `contains`, `ends_with`, `in_list`, `gt`, `lt`.

Rules use OR logic — if any rule matches, the flag is on for that user.

### Percentage Rollouts

Rollouts use deterministic hashing (`sha256(user_id:flag_key) % 100`). The same user always gets the same result for a given flag — no flickering between requests.

```python
# Flag with rollout_pct=25 — 25% of users get this flag
client.enabled("new_onboarding", user={"user_id": "42"})  # deterministic True/False
```

A `user_id` (or `id`) key is required in the user dict for percentage rollouts.

### Offline / Fail-safe Behavior

If the CDN is unreachable, the SDK keeps using the last successfully fetched config. Your flags keep working.

If the SDK has never successfully fetched a config (e.g., CDN is down on first startup), `enabled()` returns `False` and `get_value()` returns the `default` you pass in. No exceptions are raised.

### Context Manager

```python
with Client(sdk_key="your-sdk-key-from-dashboard") as client:
    if client.enabled("new_checkout", user={"user_id": "42"}):
        show_new_checkout()
# client.close() is called automatically
```

## Configuration

```python
client = Client(
    sdk_key="your-sdk-key-from-dashboard",  # required — get from Environments tab
    poll_interval=60,                       # seconds between polls (default: 30)
    on_error=lambda e: logger.warning(e),   # called on fetch errors (default: None)
)
```

| Parameter       | Type                           | Default | Description                                    |
|-----------------|--------------------------------|---------|------------------------------------------------|
| `sdk_key`       | `str`                          | —       | SDK key from the environment in the dashboard  |
| `poll_interval` | `int`                          | `30`    | Seconds between background config refreshes    |
| `on_error`      | `Callable[[Exception], None]`  | `None`  | Callback invoked when a fetch or parse fails   |

The SDK builds the CDN URL automatically from the SDK key. You can override with `cdn_base_url` if self-hosting.

## How It Works

```
┌──────────┐       ┌──────────┐       ┌─────────────┐
│Dashboard │──────>│ API      │──────>│  Postgres   │
│          │ HTTP  │ (Fly.io) │  SQL  │  (Neon)     │
└──────────┘       └────┬─────┘       └─────────────┘
                        │
                        │ publish on every change
                        v
                 ┌─────────────┐       ┌──────────────┐
                 │CDN Publisher│──────>│Cloudflare R2 │
                 │             │  PUT  │(static JSON) │
                 └─────────────┘       └──────┬───────┘
                                              │
                                              │ HTTP GET (SDK polls)
                                              v
                                       ┌──────────────┐
                                       │  Your App    │
                                       │  (this SDK)  │
                                       └──────────────┘
```

1. You create and toggle flags in the dashboard or API
2. On every change, the API generates a static JSON file and uploads it to Cloudflare R2
3. This SDK polls that JSON file from the CDN every 30 seconds
4. Flag evaluation (rules, rollouts) happens locally — no network call per flag check

The API server is only in the write path. All read traffic goes to the CDN.

## API Reference

### `Client(sdk_key, poll_interval=30, on_error=None)`

Creates a new client. Performs an initial synchronous fetch on creation, then starts background polling.

### `client.enabled(flag_key, user=None) -> bool`

Check if a boolean flag is enabled. Returns `False` if the flag doesn't exist.

| Parameter  | Type           | Description                          |
|------------|----------------|--------------------------------------|
| `flag_key` | `str`          | The flag key to check                |
| `user`     | `dict \| None` | User context for targeting/rollouts  |

### `client.get_value(flag_key, user=None, default=None) -> Any`

Get the resolved value of any flag type (string, number, JSON). Returns `default` if the flag doesn't exist.

| Parameter  | Type           | Description                          |
|------------|----------------|--------------------------------------|
| `flag_key` | `str`          | The flag key to check                |
| `user`     | `dict \| None` | User context for targeting/rollouts  |
| `default`  | `Any`          | Value returned if flag doesn't exist |

### `client.get_all_flags(user=None) -> dict[str, Any]`

Get all flag values resolved for a user. Returns an empty dict if no config is available.

### `client.close() -> None`

Stop background polling. Call this on application shutdown.

## Contributing

```sh
git clone https://github.com/ignat14/switchbox-sdk-python.git
cd switchbox-sdk-python
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT
