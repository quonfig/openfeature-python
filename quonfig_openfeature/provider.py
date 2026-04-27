"""``QuonfigProvider`` — OpenFeature provider that wraps the ``quonfig`` Python SDK."""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from openfeature.evaluation_context import EvaluationContext
from openfeature.flag_evaluation import ErrorCode, FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata
from quonfig import EvaluationDetails, Quonfig

from .context import map_context

logger = logging.getLogger(__name__)


# Map the Quonfig SDK's EvaluationDetails reason strings to OpenFeature's
# ``Reason`` enum. The SDK has been deliberately aligned with OF's
# ``StandardResolutionReasons`` subset so this is a 1:1 lookup.
_REASON_MAP = {
    "STATIC": Reason.STATIC,
    "TARGETING_MATCH": Reason.TARGETING_MATCH,
    "SPLIT": Reason.SPLIT,
    "DEFAULT": Reason.DEFAULT,
    "ERROR": Reason.ERROR,
}

# The SDK's error_code strings line up with ``ErrorCode``'s identifiers, but
# we go through an explicit map so a future SDK-side addition (e.g. PARSE_ERROR)
# can't silently break our mapping.
_ERROR_CODE_MAP = {
    "FLAG_NOT_FOUND": ErrorCode.FLAG_NOT_FOUND,
    "TYPE_MISMATCH": ErrorCode.TYPE_MISMATCH,
    "GENERAL": ErrorCode.GENERAL,
}


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
            flag_key, default_value, evaluation_context, self._client.get_bool_details
        )

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[str]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_string_details
        )

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[int]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_int_details
        )

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[float]:
        return self._resolve(
            flag_key, default_value, evaluation_context, self._client.get_float_details
        )

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: Union[Sequence[Any], Mapping[str, Any]],
        evaluation_context: Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[Union[Sequence[Any], Mapping[str, Any]]]:
        mapped = map_context(evaluation_context, self._targeting_key_mapping)

        # Try string-list first so ``string_list`` configs surface as a list,
        # then fall back to JSON for dict / generic JSON values. Both code
        # paths now use the *_details API and inherit the same reason mapping.
        details = self._client.get_string_list_details(flag_key, contexts=mapped)
        if details.reason in ("STATIC", "TARGETING_MATCH", "SPLIT") and isinstance(
            details.value, list
        ):
            return FlagResolutionDetails(
                value=details.value, reason=_REASON_MAP[details.reason]
            )

        json_details = self._client.get_json_details(flag_key, contexts=mapped)
        if json_details.reason in ("STATIC", "TARGETING_MATCH", "SPLIT"):
            value = json_details.value
            if isinstance(value, (list, dict)):
                return FlagResolutionDetails(
                    value=value, reason=_REASON_MAP[json_details.reason]
                )
            # Found a successful resolution but it's a scalar — surface as
            # TYPE_MISMATCH so callers can detect the wrong-channel use.
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=(
                    f"Flag '{flag_key}' is not an object/array; got "
                    f"{type(value).__name__}"
                ),
            )

        # Both attempts came back ERROR or DEFAULT — surface using whichever
        # signal is more specific. Prefer the JSON path for non-FLAG_NOT_FOUND
        # errors (e.g. an explicit TYPE_MISMATCH from list coercion is less
        # informative for a JSON-typed config than the JSON-side failure).
        chosen = (
            json_details
            if json_details.error_code != "FLAG_NOT_FOUND"
            else details
        )
        return _details_to_of(chosen, default_value, flag_key)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve(
        self,
        flag_key: str,
        default_value: Any,
        evaluation_context: Optional[EvaluationContext],
        getter: Callable[..., EvaluationDetails[Any]],
    ) -> FlagResolutionDetails[Any]:
        mapped = map_context(evaluation_context, self._targeting_key_mapping)
        # The new *_details methods never raise — they return ERROR-reason
        # EvaluationDetails for every failure path (missing flag, type
        # mismatch, unexpected exception). The provider becomes a pure
        # mapping layer; no try/except gymnastics.
        details = getter(flag_key, contexts=mapped)
        return _details_to_of(details, default_value, flag_key)

    # ------------------------------------------------------------------
    # Escape hatch
    # ------------------------------------------------------------------

    def get_client(self) -> Quonfig:
        """Return the underlying ``quonfig.Quonfig`` client.

        Use this for native-only features (``should_log``, ``keys``, etc.) that
        OpenFeature doesn't expose.
        """
        return self._client


def _details_to_of(
    details: EvaluationDetails[Any], default_value: Any, flag_key: str
) -> FlagResolutionDetails[Any]:
    """Translate a ``quonfig.EvaluationDetails`` into an OpenFeature
    ``FlagResolutionDetails``, substituting the caller-provided default when
    the SDK couldn't produce a value."""
    reason = _REASON_MAP.get(details.reason, Reason.UNKNOWN)

    if details.reason == "ERROR":
        error_code = _ERROR_CODE_MAP.get(
            details.error_code or "", ErrorCode.GENERAL
        )
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.ERROR,
            error_code=error_code,
            error_message=details.error_message
            or f"Flag '{flag_key}' could not be resolved",
        )

    if details.reason == "DEFAULT" or details.value is None:
        # DEFAULT means flag-exists-but-no-rule-matched — give the caller
        # back their fallback value.
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.DEFAULT,
        )

    return FlagResolutionDetails(value=details.value, reason=reason)
