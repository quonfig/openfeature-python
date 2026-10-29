"""``QuonfigProvider`` — OpenFeature provider that wraps the ``quonfig`` Python SDK."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from openfeature.evaluation_context import EvaluationContext
from openfeature.event import ProviderEventDetails
from openfeature.exception import ErrorCode as ExceptionErrorCode
from openfeature.exception import ProviderNotReadyError
from openfeature.flag_evaluation import ErrorCode, FlagResolutionDetails, Reason
from openfeature.provider import AbstractProvider, Metadata, ProviderStatus
from quonfig import EvaluationDetails, Quonfig, QuonfigInitError

from .context import map_context

logger = logging.getLogger(__name__)

try:  # The registry has lived here since openfeature-sdk 0.7 (our floor).
    from openfeature.provider._registry import provider_registry as _provider_registry
except ImportError:  # pragma: no cover - future SDK layout change
    _provider_registry = None  # type: ignore[assignment]


def _of_status(provider: Any) -> Optional[ProviderStatus]:
    """The status OpenFeature has recorded for ``provider``, or ``None`` when
    the registry is not reachable."""
    if _provider_registry is None:
        return None
    try:
        return _provider_registry.get_provider_status(provider)
    except Exception:  # noqa: BLE001
        return None


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
# we go through an explicit map so a future SDK-side addition can't silently
# break our mapping. PARSE_ERROR: a value of the requested type that cannot be
# parsed (malformed stored number/duration, unparseable ENV_VAR) (qfg-9xsl).
_ERROR_CODE_MAP = {
    "FLAG_NOT_FOUND": ErrorCode.FLAG_NOT_FOUND,
    "TYPE_MISMATCH": ErrorCode.TYPE_MISMATCH,
    "PARSE_ERROR": ErrorCode.PARSE_ERROR,
    "GENERAL": ErrorCode.GENERAL,
    "PROVIDER_NOT_READY": ErrorCode.PROVIDER_NOT_READY,
}

# Stored config types resolve_string_details returns as text. A duration has
# no OpenFeature type, so its ISO 8601 text is how OpenFeature reads it.
_STRING_READ_TYPES = ("string", "log_level", "duration")

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
    * ``"continue"`` and no config: ``initialize`` returns (OpenFeature records
      READY), then the provider emits a non-fatal PROVIDER_ERROR, so the status
      is ERROR; PROVIDER_READY on heal. Evaluations meanwhile return the
      caller default with ``PROVIDER_NOT_READY``.

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
                self._reconcile_after_init(emit_error=False)
                raise ProviderNotReadyError(
                    f"Quonfig init failed (reason={err.reason}): {err}"
                ) from err
            return
        if self._await_heal():
            # on_init_failure="continue" (or no data source): init returned
            # without a config, so every evaluation is a code default. Resolve
            # (OpenFeature records READY), then report a non-fatal ERROR.
            self._reconcile_after_init(emit_error=True)

    def _await_heal(self) -> bool:
        """After init: return False when the client holds config (READY),
        else arm the PROVIDER_READY-on-heal event and return True."""
        with self._event_lock:
            if self._client.is_ready():
                self._live = True
                return False
            self._heal_pending = True
            return True

    def _reconcile_after_init(self, *, emit_error: bool) -> None:
        """OpenFeature records the init outcome (READY when ``initialize``
        returns, ERROR when it raises) only after ``initialize`` exits, so any
        event emitted from inside it would be overwritten. Finish on a daemon
        thread once that outcome is recorded:

        * still no config and ``emit_error``: emit the non-fatal
          PROVIDER_ERROR (``continue``), so ERROR lands after READY;
        * healed meanwhile: make sure the status ends READY even if the heal's
          PROVIDER_READY was overtaken by OpenFeature's init ERROR (``fail``).
        """

        def _run() -> None:
            # continue: initialize returned, so OpenFeature records READY;
            # fail: it raised, so OpenFeature records ERROR.
            self._await_of_init_status(ProviderStatus.READY if emit_error else ProviderStatus.ERROR)
            with self._event_lock:
                if self._heal_pending:
                    if emit_error:
                        self.emit_provider_error(
                            ProviderEventDetails(
                                message=(
                                    "Quonfig has not loaded a config yet "
                                    "(on_init_failure=continue); serving code defaults"
                                ),
                                error_code=ExceptionErrorCode.PROVIDER_NOT_READY,
                            )
                        )
                elif _of_status(self) not in (None, ProviderStatus.READY) or (
                    _of_status(self) is None and not emit_error
                ):
                    self.emit_provider_ready(ProviderEventDetails(message="Quonfig config loaded"))

        threading.Thread(target=_run, name="quonfig-of-init-status", daemon=True).start()

    def _await_of_init_status(self, expected: ProviderStatus, timeout_s: float = 5.0) -> None:
        """Wait until OpenFeature has recorded this provider's init outcome
        (``expected``). Bounded, for providers driven outside the OpenFeature
        registry."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            status = _of_status(self)
            if status == expected:
                return
            if status is None:
                time.sleep(0.05)  # registry unavailable: brief grace, then go
                return
            time.sleep(0.005)

    def _on_config_update(self) -> None:
        """SDK hook, fired after every accepted config install (any thread)."""
        try:
            # Emit under the lock so events keep their order relative to the
            # deferred init-status emit above.
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
        mapped = map_context(evaluation_context, self._targeting_key_mapping)
        # One evaluation per resolution (qfg-pwrv, qfg-177f decision b):
        # evaluate_details() returns the stored form. For a string or
        # log_level config that is the answer, and a duration (no OpenFeature
        # type) reads as its stored ISO 8601 text, unchanged ("PT90S" stays
        # "PT90S"). The SDK validates it: a malformed stored duration or
        # ENV_VAR value is PARSE_ERROR. A failed read carries no value_type and
        # maps as is (FLAG_NOT_FOUND, GENERAL, ...).
        details = self._client.evaluate_details(flag_key, contexts=mapped)
        if details.value_type is None or details.value_type in _STRING_READ_TYPES:
            return _details_to_of(details, default_value, flag_key)
        # Any other type is a wrong-type read: TYPE_MISMATCH, as from
        # get_string_details, without evaluating (and counting) it twice.
        message = f'Config "{flag_key}" has type {details.value_type}, expected string'
        warn = getattr(self._client, "_warn_read_failure", None)
        if callable(warn):  # the SDK's once-per-key WARN for a failed read
            warn(flag_key, message)
        return FlagResolutionDetails(
            value=default_value,
            reason=Reason.ERROR,
            error_code=ErrorCode.TYPE_MISMATCH,
            error_message=message,
            variant=details.variant,
            flag_metadata=details.flag_metadata or {},
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
