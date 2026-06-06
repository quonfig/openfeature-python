# Changelog

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
