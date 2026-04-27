"""Provider unit tests — exercises the not-initialized / error paths via mocks.

These tests use ``pytest-mock`` to swap out the ``quonfig.Quonfig`` constructor
so we never touch the real datadir or HTTP transport. The integration and
conformance suites cover the happy path against real fixtures.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from openfeature.flag_evaluation import ErrorCode, Reason
from quonfig.exceptions import (
    QuonfigInitTimeoutError,
    QuonfigKeyNotFoundError,
    QuonfigNotInitializedError,
)

from quonfig_openfeature import QuonfigProvider


@pytest.fixture
def mock_client(mocker):
    fake = MagicMock()
    fake.init = MagicMock(return_value=fake)
    fake.close = MagicMock()
    fake.get_bool = MagicMock(return_value=None)
    fake.get_string = MagicMock(return_value=None)
    fake.get_int = MagicMock(return_value=None)
    fake.get_float = MagicMock(return_value=None)
    fake.get_string_list = MagicMock(return_value=None)
    fake.get_json = MagicMock(return_value=None)
    mocker.patch("quonfig_openfeature.provider.Quonfig", return_value=fake)
    return fake


@pytest.fixture
def provider(mock_client) -> QuonfigProvider:
    return QuonfigProvider(sdk_key="test", datadir="/fake")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_initialize_calls_client_init(provider, mock_client):
    provider.initialize(None)
    mock_client.init.assert_called_once()


def test_shutdown_calls_client_close(provider, mock_client):
    provider.shutdown()
    mock_client.close.assert_called_once()


def test_initialize_propagates_init_errors(mock_client):
    mock_client.init.side_effect = RuntimeError("boom")
    p = QuonfigProvider(sdk_key="test", datadir="/fake")
    with pytest.raises(RuntimeError, match="boom"):
        p.initialize(None)


def test_metadata_is_quonfig(provider):
    assert provider.get_metadata().name == "quonfig"


# ---------------------------------------------------------------------------
# Boolean
# ---------------------------------------------------------------------------


def test_boolean_returns_targeting_match_when_flag_found(provider, mock_client):
    mock_client.get_bool.return_value = True
    result = provider.resolve_boolean_details("my-flag", False)
    assert result.value is True
    assert result.reason == Reason.TARGETING_MATCH
    assert result.error_code is None


def test_boolean_returns_default_and_flag_not_found_when_missing(provider, mock_client):
    mock_client.get_bool.return_value = None
    result = provider.resolve_boolean_details("missing", True)
    assert result.value is True
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_boolean_returns_default_and_flag_not_found_when_client_raises_key_error(
    provider, mock_client
):
    mock_client.get_bool.side_effect = QuonfigKeyNotFoundError("nope")
    result = provider.resolve_boolean_details("missing", False)
    assert result.value is False
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_boolean_returns_provider_not_ready_when_not_initialized(provider, mock_client):
    mock_client.get_bool.side_effect = QuonfigNotInitializedError("init first")
    result = provider.resolve_boolean_details("any", False)
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PROVIDER_NOT_READY


def test_boolean_returns_provider_not_ready_on_init_timeout(provider, mock_client):
    mock_client.get_bool.side_effect = QuonfigInitTimeoutError("too slow")
    result = provider.resolve_boolean_details("any", False)
    assert result.error_code == ErrorCode.PROVIDER_NOT_READY


def test_boolean_returns_general_for_unknown_error(provider, mock_client):
    mock_client.get_bool.side_effect = RuntimeError("kaboom")
    result = provider.resolve_boolean_details("any", False)
    assert result.error_code == ErrorCode.GENERAL


def test_boolean_type_mismatch_when_value_is_not_bool(provider, mock_client):
    mock_client.get_bool.return_value = "not-a-bool"
    result = provider.resolve_boolean_details("any", False)
    assert result.error_code == ErrorCode.TYPE_MISMATCH


# ---------------------------------------------------------------------------
# String
# ---------------------------------------------------------------------------


def test_string_returns_targeting_match_when_flag_found(provider, mock_client):
    mock_client.get_string.return_value = "hello"
    result = provider.resolve_string_details("my-string", "")
    assert result.value == "hello"
    assert result.reason == Reason.TARGETING_MATCH


def test_string_returns_default_when_missing(provider, mock_client):
    mock_client.get_string.return_value = None
    result = provider.resolve_string_details("missing", "fallback")
    assert result.value == "fallback"
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


# ---------------------------------------------------------------------------
# Integer / Float
# ---------------------------------------------------------------------------


def test_integer_returns_targeting_match(provider, mock_client):
    mock_client.get_int.return_value = 42
    result = provider.resolve_integer_details("my-int", 0)
    assert result.value == 42
    assert result.reason == Reason.TARGETING_MATCH


def test_integer_returns_default_when_missing(provider, mock_client):
    mock_client.get_int.return_value = None
    result = provider.resolve_integer_details("missing", 99)
    assert result.value == 99
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_float_returns_targeting_match(provider, mock_client):
    mock_client.get_float.return_value = 3.14
    result = provider.resolve_float_details("my-float", 0.0)
    assert result.value == 3.14
    assert result.reason == Reason.TARGETING_MATCH


def test_float_returns_default_when_missing(provider, mock_client):
    mock_client.get_float.return_value = None
    result = provider.resolve_float_details("missing", 1.0)
    assert result.value == 1.0
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


# ---------------------------------------------------------------------------
# Object
# ---------------------------------------------------------------------------


def test_object_returns_list_value(provider, mock_client):
    mock_client.get_json.return_value = ["a", "b", "c"]
    result = provider.resolve_object_details("my-list", [])
    assert result.value == ["a", "b", "c"]
    assert result.reason == Reason.TARGETING_MATCH


def test_object_returns_dict_value(provider, mock_client):
    mock_client.get_json.return_value = {"key": "value"}
    result = provider.resolve_object_details("my-json", {})
    assert result.value == {"key": "value"}
    assert result.reason == Reason.TARGETING_MATCH


def test_object_returns_default_when_missing(provider, mock_client):
    mock_client.get_json.return_value = None
    default = {"default": True}
    result = provider.resolve_object_details("missing", default)
    assert result.value == default
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_object_returns_type_mismatch_for_scalar_value(provider, mock_client):
    # If the underlying flag is a scalar (string/int/bool), we shouldn't try to
    # pass it back through OF's object channel.
    mock_client.get_json.return_value = "not-an-object"
    result = provider.resolve_object_details("scalar-flag", [])
    assert result.value == []
    assert result.error_code == ErrorCode.TYPE_MISMATCH


def test_object_returns_error_when_client_raises(provider, mock_client):
    mock_client.get_json.side_effect = RuntimeError("type mismatch")
    result = provider.resolve_object_details("bad", [])
    assert result.value == []
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.TYPE_MISMATCH


# ---------------------------------------------------------------------------
# Context wiring
# ---------------------------------------------------------------------------


def test_context_is_mapped_before_calling_native_client(provider, mock_client):
    from openfeature.evaluation_context import EvaluationContext

    mock_client.get_bool.return_value = True
    ec = EvaluationContext(targeting_key="user-123", attributes={"user.plan": "pro"})
    provider.resolve_boolean_details("my-flag", False, ec)

    mock_client.get_bool.assert_called_once()
    _, kwargs = mock_client.get_bool.call_args
    assert kwargs["contexts"] == {"user": {"id": "user-123", "plan": "pro"}}
    assert kwargs["default"] is None


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


def test_get_client_returns_underlying_quonfig(provider, mock_client):
    assert provider.get_client() is mock_client
