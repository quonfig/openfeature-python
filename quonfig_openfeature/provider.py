"""``QuonfigProvider`` — OpenFeature provider that wraps the ``quonfig`` Python SDK."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEventDetails
from openfeature.exception import ProviderNotReadyError
from openfeature.flag_evaluation import ErrorCode, FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata
from quonfig import EvaluationDetails, Quonfig, QuonfigInitError

from .context import map_context

logger = logging.getLogger(__name__)


# Map the Quonfig SDK's EvaluationDetails reason strings to OpenFeature's
# ``Reason`` enum. The SDK has been deliberately aligned with OF's
# ``StandardResolutionReasons`` subset so this is a 1:1 lookup.
_REASON_MAP = {
    "STATIC": Reason.STATIC,
    "TARGETING_MATCH": Reason.TARGETING_MATCH,
    "SPLIT": Reason.SPLIT,
    "STALE": Reason.STALE,
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
    "PROVIDER_NOT_READY": ErrorCode.PROVIDER_NOT_READY,
}

# SDK reasons that carry a real (non-default) value.
_VALUE_REASONS = ("STATIC", "TARGETING_MATCH", "SPLIT", "STALE")


class QuonfigProvider(AbstractProvider):
    """OpenFeature provider backed by the ``quonfig`` Python SDK.

    Usage::

        from openfeature import api
        from quonfig_openfeature import QuonfigProvider

        provider = QuonfigProvider(sdk_key="qf_sk_...")
        api.set_provider(provider)
        client = api.get_client()
        enabled = client.get_boolean_value("my-flag", False)

    Extra keyword arguments go to the ``quonfig.Quonfig`` constructor, so
    ``on_init_failure`` (``"fail"`` (default) / ``"wait"`` / ``"continue"``)
    and ``init_timeout_ms`` pass straight through. Provider status follows the
    SDK's init outcome:

    * config loaded: READY.
    * ``"fail"`` and no config by the timeout: ``initialize`` raises
      ``ProviderNotReadyError`` (the ``QuonfigInitError`` is its
      ``__cause__``), so the status is ERROR. The client is kept and keeps
      retrying in the background; when it loads config the provider emits
      PROVIDER_READY.
    * ``"wait"``: ``initialize`` blocks (status NOT_READY) until config loads.
    * ``"continue"`` and no config: status ERROR as for ``"fail"`` (OpenFeature
      Python only marks a provider ERROR when ``initialize`` raises), then
      PROVIDER_READY on heal. Evaluations meanwhile return the caller default
      with ``PROVIDER_NOT_READY``.

    Every later config install emits PROVIDER_CONFIGURATION_CHANGED.
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
        self._user_on_config_update: Optional[Callable[[], None]] = quonfig_kwargs.pop(
            "on_config_update", None
        )
        self._event_lock = threading.Lock()
        # True once OpenFeature has (or will have) marked us READY.
        self._live = False
        # True while initialize() failed and we owe OpenFeature a READY on heal.
        self._heal_pending = False
        # Forward only the kwargs the user explicitly passed. The Quonfig
        # constructor reads its own env-var fallbacks (QUONFIG_SDK_KEY,
        # QUONFIG_DIR, QUONFIG_ENVIRONMENT) so passing ``None`` here is fine.
        self._client = Quonfig(
            sdk_key=sdk_key,
            datadir=datadir,
            environment=environment,
            on_config_update=self._on_config_update,
            **quonfig_kwargs,
        )

    # ------------------------------------------------------------------
    # OpenFeature lifecycle
    # ------------------------------------------------------------------

    def get_metadata(self) -> Metadata:
        return Metadata(name="quonfig")

    def initialize(self, evaluation_context: EvaluationContext) -> None:  # noqa: ARG002
        try:
            self._client.init()
        except QuonfigInitError as err:
            # Keep the client: it keeps retrying and heals in the background.
            if self._await_heal():
                raise ProviderNotReadyError(
                    f"Quonfig init failed (reason={err.reason}): {err}"
                ) from err
            return
        if self._await_heal():
            # on_init_failure="continue" (or no data source): init returned
            # without a config, so every evaluation is a code default.
            raise ProviderNotReadyError(
                "Quonfig has not loaded a config yet; serving code defaults until it does"
            )

    def _await_heal(self) -> bool:
        """After init: return False when the client holds config (READY),
        else arm the PROVIDER_READY-on-heal event and return True.

        Checked under the lock so a heal that lands while init() is raising is
        not lost. A heal in the few instructions between this returning True
        and OpenFeature dispatching the init ERROR can still be overtaken by
        that ERROR, leaving the status ERROR while the client serves config.
        The window is tiny, and evaluations are unaffected (OpenFeature does
        not short-circuit on ERROR)."""
        with self._event_lock:
            if self._client.is_ready():
                self._live = True
                return False
            self._heal_pending = True
            return True

    def _on_config_update(self) -> None:
        """SDK hook, fired after every accepted config install (any thread)."""
        try:
            with self._event_lock:
                heal, live = self._heal_pending, self._live
                self._heal_pending = False
                self._live = live or heal
            if heal:
                self.emit_provider_ready(ProviderEventDetails(message="Quonfig config loaded"))
            elif live:
                self.emit_provider_configuration_changed(ProviderEventDetails())
            # Otherwise this is the first install inside initialize(); the
            # OpenFeature SDK emits READY itself when initialize() returns.
        finally:
            if self._user_on_config_update is not None:
                self._user_on_config_update()

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
        if details.reason in _VALUE_REASONS and isinstance(details.value, list):
            return FlagResolutionDetails(value=details.value, reason=_REASON_MAP[details.reason])

        json_details = self._client.get_json_details(flag_key, contexts=mapped)
        if json_details.reason in _VALUE_REASONS:
            value = json_details.value
            if isinstance(value, (list, dict)):
                return FlagResolutionDetails(value=value, reason=_REASON_MAP[json_details.reason])
            # Found a successful resolution but it's a scalar — surface as
            # TYPE_MISMATCH so callers can detect the wrong-channel use.
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=(
                    f"Flag '{flag_key}' is not an object/array; got " f"{type(value).__name__}"
                ),
            )

        # Both attempts came back ERROR or DEFAULT — surface using whichever
        # signal is more specific. Prefer the JSON path for non-FLAG_NOT_FOUND
        # errors (e.g. an explicit TYPE_MISMATCH from list coercion is less
        # informative for a JSON-typed config than the JSON-side failure).
        chosen = json_details if json_details.error_code != "FLAG_NOT_FOUND" else details
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
    flag_metadata = details.flag_metadata or {}

    if details.reason == "ERROR":
        error_code = _ERROR_CODE_MAP.get(details.error_code or "", ErrorCode.GENERAL)
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.ERROR,
            error_code=error_code,
            error_message=details.error_message or f"Flag '{flag_key}' could not be resolved",
            variant=details.variant,
            flag_metadata=flag_metadata,
        )

    if details.reason == "DEFAULT" or details.value is None:
        # DEFAULT means flag-exists-but-no-rule-matched — give the caller
        # back their fallback value.
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.DEFAULT,
            variant=details.variant,
            flag_metadata=flag_metadata,
        )

    return FlagResolutionDetails(
        value=details.value,
        reason=reason,
        variant=details.variant,
        flag_metadata=flag_metadata,
    )
