"""``QuonfigProvider`` — OpenFeature provider that wraps the ``quonfig`` Python SDK."""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Sequence, Union

from openfeature.evaluation_context import EvaluationContext
from openfeature.flag_evaluation import ErrorCode, FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata
from quonfig import Quonfig
from quonfig.exceptions import QuonfigKeyNotFoundError

from .context import map_context
from .errors import to_error_code

logger = logging.getLogger(__name__)


class QuonfigProvider(AbstractProvider):
    """OpenFeature provider backed by the ``quonfig`` Python SDK.

    Usage::

        from openfeature import api
        from quonfig_openfeature import QuonfigProvider

        provider = QuonfigProvider(sdk_key="qf_sk_...")
        api.set_provider(provider)
        client = api.get_client()
        enabled = client.get_boolean_value("my-flag", False)
    """

    def __init__(
        self,
        sdk_key: Optional[str] = None,
        *,
        datadir: Optional[str] = None,
        environment: Optional[str] = None,
        targeting_key_mapping: str = "user.id",
        **quonfig_kwargs: Any,
    ) -> None:
        super().__init__()
        self._targeting_key_mapping = targeting_key_mapping
        # Forward only the kwargs the user explicitly passed. The Quonfig
        # constructor reads its own env-var fallbacks (QUONFIG_SDK_KEY,
        # QUONFIG_DIR, QUONFIG_ENVIRONMENT) so passing ``None`` here is fine.
        self._client = Quonfig(
            sdk_key=sdk_key,
            datadir=datadir,
            environment=environment,
            **quonfig_kwargs,
        )

    # ------------------------------------------------------------------
    # OpenFeature lifecycle
    # ------------------------------------------------------------------

    def get_metadata(self) -> Metadata:
        return Metadata(name="quonfig")

    def initialize(self, evaluation_context: EvaluationContext) -> None:  # noqa: ARG002
        self._client.init()

    def shutdown(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Resolvers
    # ------------------------------------------------------------------

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[bool]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_bool, bool
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[str]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_string, str
        )

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[int]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_int, int
        )

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[float]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_float, float
        )

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Union[Sequence[Any], Mapping[str, Any]],
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[Union[Sequence[Any], Mapping[str, Any]]]:
        mapped = map_context(evaluation_context, self._targeting_key_mapping)
        try:
            # `get_json` returns the raw resolved value (list / dict / scalar),
            # so it handles both `string_list` and `json` configs without the
            # str-coercion that `get_string_list` does. We expose a list/dict
            # through OF's object channel directly; if a scalar slipped into
            # this method we fall through to FLAG_NOT_FOUND so callers can
            # detect the type mismatch via the default path.
            value = self._client.get_json(flag_key, default=None, contexts=mapped)
            if isinstance(value, (list, dict)):
                return FlagResolutionDetails(value=value, reason=Reason.TARGETING_MATCH)

            if value is None:
                return FlagResolutionDetails(
                    value=default_value,
                    reason=Reason.ERROR,
                    error_code=ErrorCode.FLAG_NOT_FOUND,
                    error_message=f"Flag '{flag_key}' not found",
                )

            # Found a value but it's a scalar — surface as TYPE_MISMATCH.
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=(
                    f"Flag '{flag_key}' is not an object/array; got "
                    f"{type(value).__name__}"
                ),
            )
        except QuonfigKeyNotFoundError as e:
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.FLAG_NOT_FOUND,
                error_message=str(e),
            )
        except Exception as e:  # noqa: BLE001 — surface every error as ERROR result
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=to_error_code(e),
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve(
        self,
        flag_key: str,
        default_value: Any,
        evaluation_context: Optional[EvaluationContext],
        getter: Any,
        py_type: type,
    ) -> FlagResolutionDetails[Any]:
        mapped = map_context(evaluation_context, self._targeting_key_mapping)
        try:
            # `default=None` is the documented "missing-flag" sentinel for the
            # Python SDK: `_handle_missing` returns None instead of raising
            # QuonfigKeyNotFoundError, which lets us distinguish missing from
            # falsy without try/except gymnastics on every call.
            value = getter(flag_key, default=None, contexts=mapped)
            if value is None:
                return FlagResolutionDetails(
                    value=default_value,
                    reason=Reason.ERROR,
                    error_code=ErrorCode.FLAG_NOT_FOUND,
                    error_message=f"Flag '{flag_key}' not found",
                )
            # Type guard so a string-typed config doesn't sneak through a
            # boolean resolver. ``bool`` is a subclass of ``int`` so check it
            # explicitly first.
            if py_type is bool:
                if not isinstance(value, bool):
                    return _type_mismatch(default_value, flag_key, py_type, value)
            elif py_type in (int, float):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return _type_mismatch(default_value, flag_key, py_type, value)
            elif py_type is str and not isinstance(value, str):
                return _type_mismatch(default_value, flag_key, py_type, value)

            # Coerce int/float to the exact python type (e.g. an int stored as
            # float, or vice versa) to keep the FlagResolutionDetails value
            # exactly what callers asked for.
            if py_type is int:
                value = int(value)
            elif py_type is float:
                value = float(value)

            return FlagResolutionDetails(value=value, reason=Reason.TARGETING_MATCH)
        except QuonfigKeyNotFoundError as e:
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.FLAG_NOT_FOUND,
                error_message=str(e),
            )
        except Exception as e:  # noqa: BLE001
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=to_error_code(e),
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # Escape hatch
    # ------------------------------------------------------------------

    def get_client(self) -> Quonfig:
        """Return the underlying ``quonfig.Quonfig`` client.

        Use this for native-only features (``should_log``, ``keys``, etc.) that
        OpenFeature doesn't expose.
        """
        return self._client


def _type_mismatch(
    default_value: Any, flag_key: str, expected: type, actual_value: Any
) -> FlagResolutionDetails[Any]:
    return FlagResolutionDetails(
        value=default_value,
        reason=Reason.ERROR,
        error_code=ErrorCode.TYPE_MISMATCH,
        error_message=(
            f"Flag '{flag_key}' expected {expected.__name__}, got "
            f"{type(actual_value).__name__}"
        ),
    )
