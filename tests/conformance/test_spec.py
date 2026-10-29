"""OpenFeature spec conformance tests against a real provider + datadir fixture.

References:
- https://openfeature.dev/specification/sections/providers
- https://openfeature.dev/specification/sections/flag-evaluation

The provider is built once per session via the ``provider`` fixture in
``conftest.py`` against the shared ``integration-test-data`` corpus, then each
section calls into ``resolve_*_details`` directly without going through the
OpenFeature singleton.

Reasons matter here: pinning STATIC / TARGETING_MATCH / SPLIT to the right
fixtures is the regression test for the new ``*_details`` plumbing.
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
# 2.7 — Resolution reasons (the regression test for *_details plumbing)
# ---------------------------------------------------------------------------


def test_2_7_static_reason_for_always_true_flag(provider):
    """`always.true` is a feature flag with only an ALWAYS_TRUE rule and no
    targeting — it should surface as STATIC, not TARGETING_MATCH. This is
    the core regression test for the new *_details plumbing."""
    result = provider.resolve_boolean_details("always.true", False)
    assert result.value is True
    assert result.reason == Reason.STATIC
    assert result.error_code is None


def test_2_7_targeting_match_for_property_rule_match(provider):
    """`of.targeting` has a property rule on user.plan == "pro" — when the
    rule fires, the reason must be TARGETING_MATCH."""
    ec = EvaluationContext(attributes={"user.plan": "pro"})
    result = provider.resolve_boolean_details("of.targeting", False, ec)
    assert result.value is True
    assert result.reason == Reason.TARGETING_MATCH


def test_2_7_targeting_match_for_property_rule_fall_through(provider):
    """When the property rule misses, the next rule (ALWAYS_TRUE → false)
    still fires. Since the config has targeting rules above the catch-all,
    the SDK reports TARGETING_MATCH for the fall-through too."""
    ec = EvaluationContext(attributes={"user.plan": "free"})
    result = provider.resolve_boolean_details("of.targeting", True, ec)
    assert result.value is False
    assert result.reason == Reason.TARGETING_MATCH


def test_2_7_split_reason_for_weighted_values(provider):
    """`of.weighted` is a 50/50 weighted_values config hashed by user.id.
    `user-2` is empirically known to land on variant-b (a non-zero
    weighted index), which the SDK reports as SPLIT."""
    ec = EvaluationContext(targeting_key="user-2")
    result = provider.resolve_string_details("of.weighted", "fallback", ec)
    assert result.value == "variant-b"
    assert result.reason == Reason.SPLIT


def test_2_7_split_reason_for_weighted_bucket_zero(provider):
    """`user-123` lands on variant-a, the FIRST weighted value (0-based
    index 0). Bucket 0 is still a split and must report SPLIT, not STATIC
    (qfg-stbb: the SDK used to gate SPLIT on `weighted_value_index > 0`).
    Mirrors tests/openfeature/openfeature.yaml Case 5."""
    ec = EvaluationContext(targeting_key="user-123")
    result = provider.resolve_string_details("of.weighted", "fallback", ec)
    assert result.value == "variant-a"
    assert result.reason == Reason.SPLIT
    assert result.variant == "split:0"
    assert result.flag_metadata.get("weighted_value_index") == 0


def test_2_7_error_reason_for_missing_flag(provider):
    result = provider.resolve_boolean_details("does-not-exist", False)
    assert result.reason == Reason.ERROR


# ---------------------------------------------------------------------------
# 2.4 — All evaluation types resolve correctly
# ---------------------------------------------------------------------------


def test_2_4_resolves_boolean(provider):
    assert provider.resolve_boolean_details("always.true", False).value is True


def test_2_4_resolves_string(provider):
    # `my-test-key` resolves to "my-test-value" in Production via the
    # always-true rule.
    result = provider.resolve_string_details("my-test-key", "")
    assert result.value == "my-test-value"


def test_2_4_resolves_integer(provider):
    # `jeffreys.test.int` falls through to the always-true rule (99),
    # since no context matches the email targeting rule.
    assert provider.resolve_integer_details("jeffreys.test.int", 0).value == 99


def test_2_4_resolves_float(provider):
    assert provider.resolve_float_details("my-double-key", 0.0).value == 9.95


def test_2_4_resolves_string_list_as_object(provider):
    result = provider.resolve_object_details("my-string-list-key", [])
    assert result.value == ["a", "b", "c"]


def test_2_4_resolves_json_as_object(provider):
    result = provider.resolve_object_details("test.json", {})
    assert result.value == {"a": 1, "b": "c"}


# ---------------------------------------------------------------------------
# 3.2 — Evaluation context propagation
# ---------------------------------------------------------------------------


def test_3_2_dot_notation_context_routes_to_targeting_rule_pro(provider):
    ec = EvaluationContext(attributes={"user.plan": "pro"})
    result = provider.resolve_boolean_details("of.targeting", False, ec)
    assert result.value is True


def test_3_2_dot_notation_context_routes_to_targeting_rule_free(provider):
    ec = EvaluationContext(attributes={"user.plan": "free"})
    result = provider.resolve_boolean_details("of.targeting", True, ec)
    assert result.value is False


def test_3_2_targeting_key_maps_to_user_id_by_default(provider):
    ec = EvaluationContext(targeting_key="user-123", attributes={"user.plan": "pro"})
    result = provider.resolve_boolean_details("of.targeting", False, ec)
    assert result.value is True


# ---------------------------------------------------------------------------
# 2.8 — Provider metadata
# ---------------------------------------------------------------------------


def test_2_8_metadata_has_non_empty_name(provider):
    md = provider.get_metadata()
    assert md.name
    assert isinstance(md.name, str)


# ---------------------------------------------------------------------------
# PARSE_ERROR vs TYPE_MISMATCH (qfg-9xsl)
#
# Mirrors tests/openfeature/openfeature.yaml Case 6 and the malformed-duration
# case in Case 2. A value that has the requested type but cannot be parsed is
# PARSE_ERROR; reading a config with the method for another type is
# TYPE_MISMATCH. Both return the caller's default with reason ERROR.
# ---------------------------------------------------------------------------


def test_parse_error_for_malformed_stored_int(provider):
    result = provider.resolve_integer_details("getter.contract.int.malformed", 7)
    assert result.value == 7
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PARSE_ERROR


def test_parse_error_for_malformed_stored_double(provider):
    result = provider.resolve_float_details("getter.contract.double.malformed", 1.5)
    assert result.value == 1.5
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PARSE_ERROR


def test_parse_error_for_malformed_env_var_provided_int(provider, monkeypatch):
    monkeypatch.setenv("QUONFIG_ITD_GETTER_INT", "twelve")
    result = provider.resolve_integer_details("getter.contract.provided.int.malformed", 7)
    assert result.value == 7
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PARSE_ERROR


def test_type_mismatch_for_int_config_read_as_boolean(provider):
    result = provider.resolve_boolean_details("getter.contract.int", False)
    assert result.value is False
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.TYPE_MISMATCH


def test_parse_error_for_malformed_stored_duration(provider):
    result = provider.resolve_string_details("test.duration.malformed.30s", "PT0S")
    assert result.value == "PT0S"
    assert result.reason == Reason.ERROR
    assert result.error_code == ErrorCode.PARSE_ERROR


# ---------------------------------------------------------------------------
# Duration via resolve_string_details (qfg-pwrv, qfg-177f decision b)
#
# Mirrors tests/openfeature/openfeature.yaml Case 2. A duration has no
# OpenFeature type, so a string read returns its stored ISO 8601 text unchanged
# (not re-normalized) with reason STATIC.
# ---------------------------------------------------------------------------


def test_duration_via_resolve_string_returns_stored_iso_text(provider):
    result = provider.resolve_string_details("test.duration.PT90S", "PT0S")
    assert result.value == "PT90S"
    assert result.reason == Reason.STATIC
    assert result.error_code is None


def test_multi_component_duration_via_resolve_string_returns_stored_text(provider):
    result = provider.resolve_string_details("test.duration.P1DT6H2M1.5S", "PT0S")
    assert result.value == "P1DT6H2M1.5S"
    assert result.reason == Reason.STATIC
    assert result.error_code is None
