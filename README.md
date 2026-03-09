# Switchbox

Feature flag SDK for Python. Zero dependencies. Reads configs from a CDN.

## Install

```
pip install switchbox
```

## Quick start

```python
from switchbox import Client

client = Client(cdn_url="https://your-cdn.r2.dev/project_id/production/flags.json")

# Boolean flag
if client.enabled("new_checkout", user={"user_id": "42", "email": "a@b.com"}):
    show_new_checkout()

# String flag
version = client.get_value("search_version", user={"user_id": "42"}, default="v1")

# All flags at once
flags = client.get_all_flags(user={"user_id": "42"})

# Cleanup
client.close()
```

Or use as a context manager:

```python
with Client(cdn_url="https://your-cdn.r2.dev/project_id/production/flags.json") as client:
    if client.enabled("new_checkout", user={"user_id": "42"}):
        show_new_checkout()
```

## How it works

- Fetches flag configs from CDN (static JSON, no server in the loop)
- Evaluates rules locally (sub-millisecond)
- Polls for updates every 30 seconds (configurable)
- Works offline — keeps using cached configs if CDN is unreachable
- Zero runtime dependencies — only Python stdlib

## Configuration

```python
client = Client(
    cdn_url="https://your-cdn.r2.dev/project_id/production/flags.json",
    poll_interval=60,          # poll every 60 seconds (default: 30)
    on_error=lambda e: print(e),  # optional error callback
)
```

## Evaluation logic

1. **Disabled flag** — returns `default_value`
2. **Rules** — if any rule matches the user context (OR logic), the flag is on
3. **Rollout** — deterministic percentage based on `sha256(user_id:flag_key)`
4. **Fallback** — returns `default_value`

## License

MIT
