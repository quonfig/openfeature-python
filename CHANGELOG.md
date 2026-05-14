# Changelog

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
