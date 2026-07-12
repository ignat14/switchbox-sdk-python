# switchbox-openfeature

[OpenFeature](https://openfeature.dev) provider for [Switchbox](https://switchbox.dev) feature flags.

## What is this?

A thin provider that plugs Switchbox into the vendor-neutral OpenFeature API. Your app codes against OpenFeature; Switchbox is one constructor line. Swap vendors by swapping the provider, not your call sites. That is the point: no lock-in.

The provider contains zero evaluation logic. It wraps [switchbox-flags](https://pypi.org/project/switchbox-flags/), which fetches static JSON from a CDN and evaluates rules locally in your process. Nothing about the architecture changes: same 30 second polling, same local evaluation, same deterministic rollouts. Every resolve is a direct in-process call, so evaluation costs zero network.

## Install

```bash
pip install switchbox-openfeature
```

This pulls in `openfeature-sdk` and `switchbox-flags`.

## Quick Start

```python
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from switchbox_openfeature import SwitchboxProvider

api.set_provider(SwitchboxProvider(sdk_key="your-sdk-key-from-dashboard"))
client = api.get_client()

context = EvaluationContext(targeting_key="user-42", attributes={"plan": "pro"})

if client.get_boolean_value("new_checkout", False, context):
    show_new_checkout()
```

`SwitchboxProvider(...)` accepts every `Switchbox` constructor option (`poll_interval`, `cdn_base_url`, `on_error`, ...). To share a client you already manage, pass it instead; the provider will not close it:

```python
provider = SwitchboxProvider(client=my_switchbox)
```

## Context mapping

OpenFeature's evaluation context maps onto the Switchbox user context:

| OpenFeature | Switchbox |
|---|---|
| `targeting_key` | `user_id` (deterministic rollout bucketing) |
| every other attribute | targeting attribute, passed through as-is |

## Error behavior

- Missing flag: OpenFeature returns your code default with `FLAG_NOT_FOUND`
- Evaluated value has the wrong type: code default with `TYPE_MISMATCH`
- CDN unreachable at startup: the provider reports not-ready and OpenFeature serves code defaults (the same fail-safe posture as the SDK itself)

## License

MIT
