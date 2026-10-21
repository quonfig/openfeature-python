"""Init-failure status mapping (design B.5, qfg-9p4i.12).

sdk-python 2.0 makes ``init()`` block and, under the default
``on_init_failure="fail"``, raise ``QuonfigInitError``. These tests pin how the
provider maps that onto OpenFeature provider status and events:

* ``fail``: ``initialize`` raises a non-fatal ``ProviderNotReadyError`` ->
  status ERROR; the client stays alive and, on heal, the provider emits
  PROVIDER_READY.
* ``continue`` with no config: ``initialize`` resolves (OF records READY),
  then the provider emits a non-fatal PROVIDER_ERROR -> ERROR; PROVIDER_READY
  on heal.
* healthy init: READY; later config installs emit CONFIGURATION_CHANGED.
* an SDK outage at evaluation time surfaces as ``PROVIDER_NOT_READY``.

OpenFeature >= 0.10 runs ``set_provider`` initialization on a background
thread, so every test that checks status right away uses
``set_provider_and_wait``.
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock

import pytest
from openfeature import api
from openfeature.event import ProviderEvent
from openfeature.exception import ErrorCode as ExcErrorCode
from openfeature.exception import ProviderNotReadyError
from openfeature.flag_evaluation import ErrorCode, Reason
from openfeature.provider import ProviderStatus
from quonfig import EvaluationDetails, QuonfigInitError

from quonfig_openfeature import QuonfigProvider, to_error_code


@pytest.fixture
def fake_client(mocker):
    """A fake Quonfig client; the constructor kwargs are captured so tests can
    fire the SDK's ``on_config_update`` hook by hand."""
    fake = MagicMock()
    fake.is_ready = MagicMock(return_value=False)
    fake.close = MagicMock()
    ctor = mocker.patch("quonfig_openfeature.provider.Quonfig", return_value=fake)
    fake.ctor = ctor
    return fake


def _fire_config_update(fake) -> None:
    fake.is_ready.return_value = True
    fake.ctor.call_args.kwargs["on_config_update"]()


@pytest.fixture
def domain():
    name = f"qfg-{uuid.uuid4().hex}"
    yield name
    api.clear_providers()


def _status(domain: str) -> ProviderStatus:
    return api.get_client(domain).get_provider_status()


def test_fail_maps_to_error_status_and_keeps_client_alive(fake_client, domain):
    fake_client.init.side_effect = QuonfigInitError(
        "no config", reason="unavailable", leg_errors="primary=x: refused"
    )
    provider = QuonfigProvider(sdk_key="k")

    with pytest.raises(ProviderNotReadyError) as exc:
        api.set_provider_and_wait(provider, domain)

    assert isinstance(exc.value.__cause__, QuonfigInitError)
    assert _status(domain) == ProviderStatus.ERROR
    fake_client.close.assert_not_called()


def test_fail_then_heal_emits_provider_ready(fake_client, domain):
    fake_client.init.side_effect = QuonfigInitError("no config")
    provider = QuonfigProvider(sdk_key="k")
    with pytest.raises(ProviderNotReadyError):
        api.set_provider_and_wait(provider, domain)

    _fire_config_update(fake_client)

    assert _status(domain) == ProviderStatus.READY


def _wait_for_status(domain: str, want: ProviderStatus, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while _status(domain) != want and time.monotonic() < deadline:
        time.sleep(0.01)


def _record_events(domain: str) -> list:
    seen: list = []
    client = api.get_client(domain)
    for ev in (ProviderEvent.PROVIDER_READY, ProviderEvent.PROVIDER_ERROR):
        client.add_handler(ev, lambda d, ev=ev: seen.append(ev))
    return seen


def test_fail_heal_racing_the_init_error_still_ends_ready(fake_client, domain, mocker):
    # The client heals right as init() raises: the heal's PROVIDER_READY can
    # reach OpenFeature before OpenFeature records the init ERROR. The
    # provider must still end READY.
    fake_client.init.side_effect = QuonfigInitError("no config")
    provider = QuonfigProvider(sdk_key="k")
    real_await = provider._await_of_init_status

    def heal_then_wait(expected):
        _fire_config_update(fake_client)  # READY emitted before OF's ERROR
        real_await(expected)

    mocker.patch.object(provider, "_await_of_init_status", side_effect=heal_then_wait)
    with pytest.raises(ProviderNotReadyError):
        api.set_provider_and_wait(provider, domain)

    _wait_for_status(domain, ProviderStatus.READY)
    time.sleep(0.05)
    assert _status(domain) == ProviderStatus.READY


def test_continue_without_config_resolves_then_emits_error(fake_client, domain):
    # on_init_failure="continue": init() returns, but nothing is installed.
    # B.5: initialize resolves (OF records READY), then the provider emits a
    # non-fatal PROVIDER_ERROR that must land AFTER that READY.
    fake_client.init.return_value = fake_client
    provider = QuonfigProvider(sdk_key="k", on_init_failure="continue")
    api.set_provider_and_wait(provider, domain)  # must not raise

    # Status updates are synchronous and ordered (handlers run on a pool, so
    # their order is not): ERROR must be the final status, not overwritten by
    # OpenFeature's READY.
    _wait_for_status(domain, ProviderStatus.ERROR)
    time.sleep(0.05)
    assert _status(domain) == ProviderStatus.ERROR
    assert fake_client.ctor.call_args.kwargs["on_init_failure"] == "continue"
    fake_client.close.assert_not_called()

    _fire_config_update(fake_client)
    assert _status(domain) == ProviderStatus.READY


def test_continue_without_config_error_ordering_on_background_set_provider(fake_client, domain):
    fake_client.init.return_value = fake_client
    provider = QuonfigProvider(sdk_key="k", on_init_failure="continue")

    api.set_provider(provider, domain)  # initialize runs on a background thread

    _wait_for_status(domain, ProviderStatus.ERROR)
    time.sleep(0.05)  # nothing may flip it back to READY afterwards
    assert _status(domain) == ProviderStatus.ERROR


def test_continue_heal_before_deferred_error_skips_the_error(fake_client, domain, mocker):
    fake_client.init.return_value = fake_client
    provider = QuonfigProvider(sdk_key="k", on_init_failure="continue")
    # The client heals while the deferred emitter is still waiting for
    # OpenFeature's READY: no ERROR may follow.
    mocker.patch.object(
        provider,
        "_await_of_init_status",
        side_effect=lambda expected: _fire_config_update(fake_client),
    )
    seen = _record_events(domain)
    api.set_provider_and_wait(provider, domain)
    time.sleep(0.1)
    assert _status(domain) == ProviderStatus.READY
    assert ProviderEvent.PROVIDER_ERROR not in seen


def test_healthy_init_is_ready_and_updates_emit_configuration_changed(fake_client, domain):
    def _init():
        # The SDK installs the first config (and fires on_config_update)
        # inside init(); that must not emit an event of its own.
        _fire_config_update(fake_client)
        return fake_client

    fake_client.init.side_effect = _init
    provider = QuonfigProvider(sdk_key="k")
    emitted = []
    provider.attach(lambda p, ev, details: emitted.append(ev))
    provider.initialize(None)  # type: ignore[arg-type]
    assert emitted == []

    _fire_config_update(fake_client)
    assert emitted == [ProviderEvent.PROVIDER_CONFIGURATION_CHANGED]


def test_user_on_config_update_callback_still_fires(fake_client):
    calls = []
    QuonfigProvider(sdk_key="k", on_config_update=lambda: calls.append(1))
    _fire_config_update(fake_client)
    assert calls == [1]


def test_init_options_pass_through_to_client(fake_client):
    QuonfigProvider(sdk_key="k", on_init_failure="wait", init_timeout_ms=2500)
    kwargs = fake_client.ctor.call_args.kwargs
    assert kwargs["on_init_failure"] == "wait"
    assert kwargs["init_timeout_ms"] == 2500


def test_provider_not_ready_error_code_maps_through(fake_client):
    fake_client.get_bool_details.return_value = EvaluationDetails(
        value=None,
        reason="ERROR",
        error_code="PROVIDER_NOT_READY",
        error_message="Quonfig has not loaded a config yet",
    )
    provider = QuonfigProvider(sdk_key="k")
    result = provider.resolve_boolean_details("flag", True)
    assert result.value is True
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PROVIDER_NOT_READY


def test_stale_reason_maps_to_of_stale(fake_client):
    fake_client.get_bool_details.return_value = EvaluationDetails(value=False, reason="STALE")
    provider = QuonfigProvider(sdk_key="k")
    result = provider.resolve_boolean_details("flag", True)
    assert result.value is False
    assert result.reason == Reason.STALE


def test_to_error_code_maps_init_error_to_provider_not_ready():
    assert to_error_code(QuonfigInitError("x", reason="unauthorized")) == (
        ExcErrorCode.PROVIDER_NOT_READY
    )


def test_real_sdk_fail_default_raises_and_evaluates_to_default(domain):
    """Through the real sdk-python 2.0 client: with no reachable delivery leg
    the default ``fail`` mode lands the provider in ERROR, and evaluations
    return the caller default with PROVIDER_NOT_READY."""
    provider = QuonfigProvider(
        sdk_key="qf_sk_test",
        api_urls=["http://127.0.0.1:9"],
        init_timeout_ms=0,
        enable_sse=False,
        fallback_poll_enabled=False,
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    with pytest.raises(ProviderNotReadyError):
        api.set_provider_and_wait(provider, domain)
    assert _status(domain) == ProviderStatus.ERROR

    details = api.get_client(domain).get_boolean_details("any-flag", True)
    assert details.value is True
    assert details.error_code == ErrorCode.PROVIDER_NOT_READY
