"""Provider unit tests — exercise the mapping layer with a mocked Quonfig
client whose ``*_details`` methods return hand-crafted ``EvaluationDetails``.

The provider is now a pure mapping layer over the SDK's *_details API;
these tests pin the mapping so a future SDK reason or error_code can't
silently drift.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from openfeature.flag_evaluation import ErrorCode, Reason
from quonfig import EvaluationDetails

from quonfig_openfeature import QuonfigProvider


@pytest.fixture
def mock_client(mocker):
    fake = MagicMock()
    fake.init = MagicMock(return_value=fake)
    fake.close = MagicMock()
    # Default to FLAG_NOT_FOUND so any test that doesn't explicitly stub a
    # method still produces a sensible ERROR result.
    not_found = EvaluationDetails(
        value=None,
        reason="ERROR",
        error_code="FLAG_NOT_FOUND",
        error_message="Flag 'x' not found",
    )
    fake.get_bool_details = MagicMock(return_value=not_found)
    fake.get_string_details = MagicMock(return_value=not_found)
    fake.get_int_details = MagicMock(return_value=not_found)
    fake.get_float_details = MagicMock(return_value=not_found)
    fake.get_string_list_details = MagicMock(return_value=not_found)
    fake.get_json_details = MagicMock(return_value=not_found)
    mocker.patch("quonfig_openfeature.provider.Quonfig", return_value=fake)
    return fake


@pytest.fixture
def provider(mock_client) -> QuonfigProvider:
    return QuonfigProvider(sdk_key="test", datadir="/fake")


def _ok(value, reason="TARGETING_MATCH"):
    return EvaluationDetails(value=value, reason=reason)


def _err(error_code, message="boom"):
    return EvaluationDetails(
        value=None, reason="ERROR", error_code=error_code, error_message=message
    )


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
# Reason mapping (the regression test for the new pipeline)
# ---------------------------------------------------------------------------


def test_static_reason_passes_through(provider, mock_client):
    mock_client.get_bool_details.return_value = _ok(True, reason="STATIC")
    result = provider.resolve_boolean_details("flag", False)
    assert result.value is True
    assert result.reason == Reason.STATIC
    assert result.error_code is None


def test_targeting_match_reason_passes_through(provider, mock_client):
    mock_client.get_bool_details.return_value = _ok(True, reason="TARGETING_MATCH")
    result = provider.resolve_boolean_details("flag", False)
    assert result.value is True
    assert result.reason == Reason.TARGETING_MATCH


def test_split_reason_passes_through(provider, mock_client):
    mock_client.get_string_details.return_value = _ok("variant-b", reason="SPLIT")
    result = provider.resolve_string_details("flag", "")
    assert result.value == "variant-b"
    assert result.reason == Reason.SPLIT


def test_default_reason_returns_default_value(provider, mock_client):
    mock_client.get_bool_details.return_value = EvaluationDetails(
        value=None, reason="DEFAULT"
    )
    result = provider.resolve_boolean_details("flag", True)
    assert result.value is True
    assert result.reason == Reason.DEFAULT
    assert result.error_code is None


# ---------------------------------------------------------------------------
# Boolean
# ---------------------------------------------------------------------------


def test_boolean_returns_targeting_match_when_flag_found(provider, mock_client):
    mock_client.get_bool_details.return_value = _ok(True)
    result = provider.resolve_boolean_details("my-flag", False)
    assert result.value is True
    assert result.reason == Reason.TARGETING_MATCH
    assert result.error_code is None


def test_boolean_returns_default_and_flag_not_found_when_missing(provider, mock_client):
    mock_client.get_bool_details.return_value = _err("FLAG_NOT_FOUND", "missing")
    result = provider.resolve_boolean_details("missing", True)
    assert result.value is True
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_boolean_returns_general_for_general_error(provider, mock_client):
    mock_client.get_bool_details.return_value = _err("GENERAL", "kaboom")
    result = provider.resolve_boolean_details("any", False)
    assert result.error_code == ErrorCode.GENERAL


def test_boolean_type_mismatch_when_sdk_reports_type_mismatch(provider, mock_client):
    mock_client.get_bool_details.return_value = _err(
        "TYPE_MISMATCH", "not a bool"
    )
    result = provider.resolve_boolean_details("any", False)
    assert result.error_code == ErrorCode.TYPE_MISMATCH


# ---------------------------------------------------------------------------
# String
# ---------------------------------------------------------------------------


def test_string_returns_targeting_match_when_flag_found(provider, mock_client):
    mock_client.get_string_details.return_value = _ok("hello")
    result = provider.resolve_string_details("my-string", "")
    assert result.value == "hello"
    assert result.reason == Reason.TARGETING_MATCH


def test_string_returns_default_when_missing(provider, mock_client):
    mock_client.get_string_details.return_value = _err("FLAG_NOT_FOUND")
    result = provider.resolve_string_details("missing", "fallback")
    assert result.value == "fallback"
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


# ---------------------------------------------------------------------------
# Integer / Float
# ---------------------------------------------------------------------------


def test_integer_returns_targeting_match(provider, mock_client):
    mock_client.get_int_details.return_value = _ok(42)
    result = provider.resolve_integer_details("my-int", 0)
    assert result.value == 42
    assert result.reason == Reason.TARGETING_MATCH


def test_integer_returns_default_when_missing(provider, mock_client):
    mock_client.get_int_details.return_value = _err("FLAG_NOT_FOUND")
    result = provider.resolve_integer_details("missing", 99)
    assert result.value == 99
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_float_returns_targeting_match(provider, mock_client):
    mock_client.get_float_details.return_value = _ok(3.14)
    result = provider.resolve_float_details("my-float", 0.0)
    assert result.value == 3.14
    assert result.reason == Reason.TARGETING_MATCH


def test_float_returns_default_when_missing(provider, mock_client):
    mock_client.get_float_details.return_value = _err("FLAG_NOT_FOUND")
    result = provider.resolve_float_details("missing", 1.0)
    assert result.value == 1.0
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


# ---------------------------------------------------------------------------
# Object — string-list-first, then JSON
# ---------------------------------------------------------------------------


def test_object_returns_list_value(provider, mock_client):
    mock_client.get_string_list_details.return_value = _ok(["a", "b", "c"])
    result = provider.resolve_object_details("my-list", [])
    assert result.value == ["a", "b", "c"]
    assert result.reason == Reason.TARGETING_MATCH


def test_object_returns_dict_value_via_json(provider, mock_client):
    # string_list comes back FLAG_NOT_FOUND (mock default), JSON fires.
    mock_client.get_json_details.return_value = _ok({"key": "value"})
    result = provider.resolve_object_details("my-json", {})
    assert result.value == {"key": "value"}
    assert result.reason == Reason.TARGETING_MATCH


def test_object_returns_default_when_missing(provider, mock_client):
    # Both string_list and json come back FLAG_NOT_FOUND.
    default = {"default": True}
    result = provider.resolve_object_details("missing", default)
    assert result.value == default
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_object_returns_type_mismatch_for_scalar_value(provider, mock_client):
    """If JSON resolves successfully but the value is a scalar (string), the
    object channel surfaces TYPE_MISMATCH."""
    mock_client.get_json_details.return_value = _ok("not-an-object")
    result = provider.resolve_object_details("scalar-flag", [])
    assert result.value == []
    assert result.error_code == ErrorCode.TYPE_MISMATCH


def test_object_returns_static_reason_for_static_list(provider, mock_client):
    """STATIC reason should pass through the object channel just like the
    typed channels."""
    mock_client.get_string_list_details.return_value = _ok(
        ["a", "b"], reason="STATIC"
    )
    result = provider.resolve_object_details("static-list", [])
    assert result.reason == Reason.STATIC
    assert result.value == ["a", "b"]


# ---------------------------------------------------------------------------
# Context wiring
# ---------------------------------------------------------------------------


def test_context_is_mapped_before_calling_native_client(provider, mock_client):
    from openfeature.evaluation_context import EvaluationContext

    mock_client.get_bool_details.return_value = _ok(True)
    ec = EvaluationContext(targeting_key="user-123", attributes={"user.plan": "pro"})
    provider.resolve_boolean_details("my-flag", False, ec)

    mock_client.get_bool_details.assert_called_once()
    _, kwargs = mock_client.get_bool_details.call_args
    assert kwargs["contexts"] == {"user": {"id": "user-123", "plan": "pro"}}


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------


def test_get_client_returns_underlying_quonfig(provider, mock_client):
    assert provider.get_client() is mock_client
