"""OpenFeature spec conformance tests against a real provider + datadir fixture.

References:
- https://openfeature.dev/specification/sections/providers
- https://openfeature.dev/specification/sections/flag-evaluation

The provider is built once per session via the ``provider`` fixture in
``conftest.py``, then each section calls into ``resolve_*_details`` directly
without going through the OpenFeature singleton.
"""

from __future__ import annotations

from openfeature.evaluation_context import EvaluationContext
from openfeature.flag_evaluation import ErrorCode, Reason

from quonfig_openfeature import QuonfigProvider

# ---------------------------------------------------------------------------
# 2.3 — Provider lifecycle
# ---------------------------------------------------------------------------


def test_2_3_initialize_resolves_for_valid_datadir(fixtures_dir):
    p = QuonfigProvider(
        sdk_key="test",
        datadir=fixtures_dir,
        environment="Production",
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    p.initialize(None)
    p.shutdown()


def test_2_3_initialize_raises_for_invalid_datadir():
    p = QuonfigProvider(
        sdk_key="test",
        datadir="/does/not/exist",
        environment="Production",
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    raised = False
    try:
        p.initialize(None)
    except Exception:
        raised = True
    finally:
        p.shutdown()
    assert raised, "initialize() should raise for an invalid datadir path"


# ---------------------------------------------------------------------------
# 2.2 — Error codes (FLAG_NOT_FOUND on missing)
# ---------------------------------------------------------------------------


def test_2_2_2_flag_not_found_for_missing_boolean(provider):
    result = provider.resolve_boolean_details("does-not-exist", False)
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_2_2_2_flag_not_found_for_missing_string(provider):
    result = provider.resolve_string_details("does-not-exist", "fallback")
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_2_2_2_flag_not_found_for_missing_integer(provider):
    result = provider.resolve_integer_details("does-not-exist", 0)
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_2_2_2_flag_not_found_for_missing_float(provider):
    result = provider.resolve_float_details("does-not-exist", 0.0)
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


def test_2_2_2_flag_not_found_for_missing_object(provider):
    result = provider.resolve_object_details("does-not-exist", {})
    assert result.error_code == ErrorCode.FLAG_NOT_FOUND


# ---------------------------------------------------------------------------
# 2.1 — Default value returned on error
# ---------------------------------------------------------------------------


def test_2_1_returns_boolean_default_for_missing_flag(provider):
    assert provider.resolve_boolean_details("does-not-exist", True).value is True
    assert provider.resolve_boolean_details("does-not-exist", False).value is False


def test_2_1_returns_string_default_for_missing_flag(provider):
    assert provider.resolve_string_details("does-not-exist", "sentinel").value == "sentinel"


def test_2_1_returns_integer_default_for_missing_flag(provider):
    assert provider.resolve_integer_details("does-not-exist", 42).value == 42


def test_2_1_returns_float_default_for_missing_flag(provider):
    assert provider.resolve_float_details("does-not-exist", 1.5).value == 1.5


def test_2_1_returns_object_default_for_missing_flag(provider):
    default = {"key": "val"}
    assert provider.resolve_object_details("does-not-exist", default).value == default


# ---------------------------------------------------------------------------
# 2.7 — Resolution reasons
# ---------------------------------------------------------------------------


def test_2_7_targeting_match_for_found_boolean(provider):
    result = provider.resolve_boolean_details("my-flag", False)
    assert result.reason == Reason.TARGETING_MATCH


def test_2_7_targeting_match_for_found_string(provider):
    result = provider.resolve_string_details("my-string", "")
    assert result.reason == Reason.TARGETING_MATCH


def test_2_7_error_reason_for_missing_flag(provider):
    result = provider.resolve_boolean_details("does-not-exist", False)
    assert result.reason == Reason.ERROR


# ---------------------------------------------------------------------------
# 2.4 — All evaluation types resolve correctly
# ---------------------------------------------------------------------------


def test_2_4_resolves_boolean(provider):
    assert provider.resolve_boolean_details("my-flag", False).value is True


def test_2_4_resolves_string(provider):
    assert provider.resolve_string_details("my-string", "").value == "hello"


def test_2_4_resolves_integer(provider):
    assert provider.resolve_integer_details("my-int", 0).value == 42


def test_2_4_resolves_float(provider):
    assert provider.resolve_float_details("my-float", 0.0).value == 3.14


def test_2_4_resolves_string_list_as_object(provider):
    result = provider.resolve_object_details("my-list", [])
    assert result.value == ["a", "b", "c"]


def test_2_4_resolves_json_as_object(provider):
    result = provider.resolve_object_details("my-json", {})
    assert result.value == {"foo": "bar"}


# ---------------------------------------------------------------------------
# 3.2 — Evaluation context propagation
# ---------------------------------------------------------------------------


def test_3_2_dot_notation_context_routes_to_targeting_rule_pro(provider):
    ec = EvaluationContext(attributes={"user.plan": "pro"})
    result = provider.resolve_boolean_details("plan-flag", False, ec)
    assert result.value is True


def test_3_2_dot_notation_context_routes_to_targeting_rule_free(provider):
    ec = EvaluationContext(attributes={"user.plan": "free"})
    result = provider.resolve_boolean_details("plan-flag", False, ec)
    assert result.value is False


def test_3_2_targeting_key_maps_to_user_id_by_default(provider):
    ec = EvaluationContext(targeting_key="user-123", attributes={"user.plan": "pro"})
    result = provider.resolve_boolean_details("plan-flag", False, ec)
    assert result.value is True


# ---------------------------------------------------------------------------
# 2.8 — Provider metadata
# ---------------------------------------------------------------------------


def test_2_8_metadata_has_non_empty_name(provider):
    md = provider.get_metadata()
    assert md.name
    assert isinstance(md.name, str)
