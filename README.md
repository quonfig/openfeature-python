# quonfig-openfeature

OpenFeature provider for [Quonfig](https://quonfig.com) -- Python server-side SDK.

This package wraps the `quonfig` native SDK and implements the
[OpenFeature](https://openfeature.dev) Python server-side `AbstractProvider`
interface.

## Install

```bash
pip install quonfig-openfeature quonfig openfeature-sdk
```

## Usage

```python
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from quonfig_openfeature import QuonfigProvider

provider = QuonfigProvider(
    sdk_key="qf_sk_production_...",
    # targeting_key_mapping="user.id",  # default
)

api.set_provider(provider)
client = api.get_client()

# Boolean flag
enabled = client.get_boolean_value("my-feature", False)

# String config
welcome = client.get_string_value("welcome-message", "Hello!")

# Number config
timeout_ms = client.get_integer_value("request-timeout-ms", 5000)

# Object config (JSON or string_list)
allowed_plans = client.get_object_value("allowed-plans", [])

# With evaluation context (per-request)
is_pro = client.get_boolean_value(
    "pro-feature",
    False,
    EvaluationContext(
        targeting_key="user-123",          # maps to user.id by default
        attributes={
            "user.plan": "pro",
            "org.tier": "enterprise",
        },
    ),
)
```

## Context mapping

OpenFeature context is flat; Quonfig context is nested by namespace. This
provider maps between them using dot-notation:

| OpenFeature context key | Quonfig namespace | Quonfig property |
|-------------------------|-------------------|------------------|
| `targeting_key` | `user` | `id` (configurable via `targeting_key_mapping`) |
| `"user.email"` | `user` | `email` |
| `"org.tier"` | `org` | `tier` |
| `"country"` (no dot) | `""` (default) | `country` |
| `"user.ip.address"` | `user` | `ip.address` (first dot only) |

### Customizing targeting_key mapping

```python
provider = QuonfigProvider(
    sdk_key="qf_sk_...",
    targeting_key_mapping="account.id",  # maps targeting_key to {account: {id: ...}}
)
```

## Accessing native SDK features

The `get_client()` escape hatch returns the underlying `quonfig.Quonfig`
client for features not available in OpenFeature:

```python
native = provider.get_client()

# Log level integration
should_log = native.should_log(
    config_key="log-level.auth",
    desired_level="DEBUG",
    contexts={"user": {"id": "user-123"}},
)

# List all config keys
keys = native.keys()
```

## What you lose vs. the native SDK

OpenFeature is designed for feature flags, not general configuration. Some
Quonfig features require the native `quonfig` SDK:

1. **Log levels** -- `should_log()` is native-only.
2. **`string_list` configs** -- accessed via `get_object_value()`, returned as a Python `list[str]`.
3. **`duration` configs** -- return the raw float seconds via `get_float_value()` (or use `get_duration()` natively).
4. **`bytes` configs** -- not accessible via OpenFeature (no binary type in OF).
5. **`keys()` and raw config access** -- native-only via `get_client()`.
6. **Context keys use dot-notation** -- `"user.email"`, not nested objects.
7. **`targeting_key` maps to `user.id` by default** -- configure `targeting_key_mapping` if different.

## Configuration changed events

The provider extends OpenFeature's `AbstractProvider`, so you can register
event handlers via the standard `api` if you want to know when configs
update. The native `quonfig` SDK pushes live updates over SSE; surfacing
those as `PROVIDER_CONFIGURATION_CHANGED` events is on the roadmap.

## Development

```bash
poetry install
poetry run ruff check .
poetry run pytest -v
```

The package depends on the local sibling `sdk-python/` repo via a Poetry
path dependency; CI checks that out as a sibling directory and installs
the same way.
