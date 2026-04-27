"""Map an OpenFeature ``EvaluationContext`` to Quonfig's nested ``Contexts``."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Union

from openfeature.evaluation_context import EvaluationContext


def map_context(
    of_context: Optional[Union[EvaluationContext, Mapping[str, Any]]],
    targeting_key_mapping: str = "user.id",
) -> Dict[str, Dict[str, Any]]:
    """Map an OpenFeature flat context to Quonfig's nested ``{namespace: {prop: value}}`` shape.

    Rules:
    - ``targetingKey`` (or ``EvaluationContext.targeting_key``) maps to the
      namespace + property given by ``targeting_key_mapping``.
      Defaults to ``"user.id"`` -> ``{"user": {"id": value}}``.
    - Keys with a dot are split on the **first** dot only:
      ``"user.email"`` -> ``{"user": {"email": value}}``;
      ``"user.ip.address"`` -> ``{"user": {"ip.address": value}}``.
    - Keys without a dot go into the default (empty-string) namespace:
      ``"country"`` -> ``{"": {"country": value}}``.
    - ``None`` values are skipped.
    """
    result: Dict[str, Dict[str, Any]] = {}

    if of_context is None:
        return result

    targeting_key: Optional[str] = None
    flat: Mapping[str, Any]

    if isinstance(of_context, EvaluationContext):
        targeting_key = of_context.targeting_key
        flat = of_context.attributes or {}
    else:
        # Plain mapping form — pull `targetingKey` out of the dict so it gets
        # routed via the configured `targeting_key_mapping`.
        flat = of_context
        if "targetingKey" in flat:
            tk = flat.get("targetingKey")
            if tk is not None:
                targeting_key = str(tk)

    if targeting_key is not None:
        ns, prop = _split_first_dot(targeting_key_mapping)
        result.setdefault(ns, {})[prop] = targeting_key

    for key, value in flat.items():
        if key == "targetingKey":
            continue
        if value is None:
            continue
        ns, prop = _split_first_dot(key, default_namespace="")
        result.setdefault(ns, {})[prop] = value

    return result


def _split_first_dot(key: str, default_namespace: str = "") -> tuple:
    """Split ``key`` on its first ``.``.

    If there is no dot, return ``(default_namespace, key)``. The caller decides
    the default-namespace policy: targeting-key mapping uses the key itself as
    the property name, while flat context entries use the empty-string
    namespace.
    """
    dot_idx = key.find(".")
    if dot_idx == -1:
        return (default_namespace, key)
    return (key[:dot_idx], key[dot_idx + 1 :])
