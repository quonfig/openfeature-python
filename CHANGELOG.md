# Changelog

## 2.1.0 - 2026-10-23

- Require `quonfig` (sdk-python) `>=2.1.0` so provider users inherit sdk-python
  2.1.0: size caps on delivery payloads (4 MiB per SSE event, 16 MiB per
  `/api/v2/configs` body; qfg-6vno.20.4), `quonfig_sdk_callback_errors_total`
  so a raising user callback counts as a callback error rather than a worker
  restart (qfg-6vno.29), linear-time SSE parsing of large events, and getters
  that return the default on malformed input instead of raising (qfg-6vno.14).
  No code change in this provider.
- **UPGRADE (inherited from sdk-python 2.1.0, qfg-6vno.23).** Under the default
  `on_init_failure="fail"`, a forked child whose lazy re-initialization cannot
  load a config now raises `QuonfigInitError` from the SDK's content getters,
  matching a fresh boot. Through this provider, evaluations in that child
  resolve to the default with error code `PROVIDER_NOT_READY`. Approved as a
  minor under Decision 1 (qfg-6vno.16, 2026-10-22; prod corpus scan: n/a, this
  changes init-failure handling, not who matches a rule).

## 2.0.0 - 2026-10-22

**BREAKING / UPGRADE (major, qfg-9p4i.12).** This release tracks sdk-python
2.0.0. With the default `on_init_failure="fail"`, a provider that cannot load
config now ends in OpenFeature status ERROR instead of READY, and
`api.set_provider_and_wait()` raises `ProviderNotReadyError` at startup. If you
relied on startup never raising, catch `ProviderNotReadyError` or pass
`on_init_failure="continue"` to the provider. Evaluations made before any
config loads now report error code `PROVIDER_NOT_READY` instead of `GENERAL`.

- Require `quonfig` (sdk-python) `>=2.0.0` (qfg-9p4i.12). The SDK's 2.0 init
  behavior now flows through the provider: `initialize()` blocks until the
  first config loads, and by default (`on_init_failure="fail"`) fails when none
  loads within `init_timeout_ms`. Both options pass through as provider kwargs.
- Init failure now maps to OpenFeature status ERROR instead of READY (design
  B.5). `initialize()` raises a non-fatal `ProviderNotReadyError` (cause: the
  `QuonfigInitError`) under `"fail"`; `api.set_provider_and_wait()` re-raises
  it. Under `"continue"` with no config (or with no data source at all),
  `initialize()` returns, OpenFeature records READY, and the provider then
  emits a non-fatal `PROVIDER_ERROR`, so the status ends ERROR without
  raising. The client is kept and keeps retrying; when it loads config the
  provider emits `PROVIDER_READY`, and the status ends READY even if the heal
  races the init ERROR.
- The provider now emits events: `PROVIDER_READY` on heal and
  `PROVIDER_CONFIGURATION_CHANGED` on every later config install. A
  user-supplied `on_config_update` callback still fires.
- The SDK's `PROVIDER_NOT_READY` error code (evaluations before any config
  loads) now maps to OpenFeature `PROVIDER_NOT_READY` instead of `GENERAL`, and
  an SDK `STALE` reason maps to OpenFeature `STALE`. `to_error_code()` maps any
  `QuonfigInitError` to `PROVIDER_NOT_READY`.

## 1.0.2 - 2026-10-09

- Raise the `quonfig` dependency floor from `>=1.4.1` to `>=1.7.1` so provider
  users inherit sdk-python 1.7.1: no SSE clean-EOF reconnect storm, mid-body
  fetch errors fail over, `scoped_context` per asyncio task, weighted-variant
  redaction and `close()` dropping the SSE stream (qfg-goi1.2.12, qfg-goi1.2.13,
  qfg-goi1.2.22, qfg-goi1.2.45). No change to this provider's behavior.

## 1.0.1 - 2026-09-11

- Raise the `quonfig` dependency floor from `>=1.0.0` to `>=1.4.1` so provider
  users inherit the SDK's fork-safety fix (a forked worker rebuilds its own
  config stream instead of going silently stale; sdk-python 1.4.0, epic
  qfg-lv4n) and the 1.4.1 follow-ups (a real per-instance `instanceHash`,
  strictly-older `guardRejected`). No change to this provider's behavior.
  Parity with `quonfig-openfeature` (Ruby) 1.0.1, which floors at sdk-ruby
  >= 1.4.0.

## 1.0.0 - 2026-06-06

- **Stable 1.0.0 release.** The Quonfig OpenFeature provider for Python is now declared
  stable and depends on the `quonfig` SDK >= 1.0.0. No API or behavior changes from
  0.0.10 — this is a coordinated 1.0.0 version stamp across the entire Quonfig SDK
  family.

## 0.0.10 - 2026-06-02

- Raise the `quonfig` dependency floor from `>=0.0.18` to `>=0.0.21` to inherit dev-context injection default-on (qfg-bw7g.9, via qfg-bw7g.4). No change to this provider's behavior — dev-context lives below the OpenFeature layer, so OpenFeature users now get `quonfig-user.email` injection by default in local dev (gated on the `qfg login` token file; inert in production).

## 0.0.9 - 2026-05-28

- Bump `quonfig` runtime floor to `>=0.0.18`, tracking the latest published
  Python SDK release on PyPI (sdk-1.0-unification).

## 0.0.8 - 2026-05-21

- Bump `quonfig` runtime floor to `>=0.0.17`, tracking the latest published
  Python SDK release on PyPI.

## 0.0.7 - 2026-05-14

- Forward `variant` and `flag_metadata` from the Quonfig SDK through to
  `FlagResolutionDetails`. (qfg-9dbl)
- Bump `quonfig` runtime floor to `>=0.0.15`, resolved from the published
  PyPI distribution. The previous local `path` override on the sibling
  `sdk-python` checkout has been removed.
- Raise the minimum supported Python to `3.10`, tracking `quonfig` 0.0.15,
  which dropped Python 3.9 support.

## 0.0.6 - 2026-05-07

- Bump `quonfig` runtime floor to `>=0.0.13` to ensure providers resolve a
  Python SDK version that supports the `IS_PRESENT` / `IS_NOT_PRESENT`
  targeting operators. (qfg-7jnb.11)
