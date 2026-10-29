"""Typed-getter contract (qfg-zvyy), driven through the real provider and the
OpenFeature client against the integration-test-data ``getter.contract.*``
fixtures. No mocks: this pins what provider users inherit from ``quonfig``
(sdk-python) 3.0.0 and 3.1.0.

The rule: a flag read with the method for another type returns the caller's
default with reason ERROR and error code TYPE_MISMATCH. Strings are never
coerced (a stored "false" is not a bool, "3" is not a number). Numbers convert
only when exact: an int config reads as a float, and a double config reads as
an int only when it is whole and within +/-(2^53-1).
"""

from __future__ import annotations

import pytest
from openfeature import api
from openfeature.exception import ErrorCode
from openfeature.flag_evaluation import Reason

from quonfig_openfeature import QuonfigProvider

DOMAIN = "typed-getter-contract"


@pytest.fixture(scope="module")
def client(fixtures_dir):
    provider = QuonfigProvider(
        sdk_key="test-sdk-key",
        datadir=fixtures_dir,
        environment="Production",
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    api.set_provider_and_wait(provider, domain=DOMAIN)
    yield api.get_client(domain=DOMAIN)
    api.shutdown()


def assert_error(details, default, error_code):
    assert details.value == default
    assert type(details.value) is type(default)
    assert details.reason == Reason.ERROR
    assert details.error_code == error_code


def assert_type_mismatch(details, default):
    assert_error(details, default, ErrorCode.TYPE_MISMATCH)


# ---------------------------------------------------------------------------
# Wrong type -> default + TYPE_MISMATCH
# ---------------------------------------------------------------------------


def test_boolean_on_stored_string_false_returns_default(client):
    assert_type_mismatch(client.get_boolean_details("getter.contract.string.false", False), False)


def test_boolean_on_stored_string_true_returns_default(client):
    assert_type_mismatch(client.get_boolean_details("getter.contract.string.true", False), False)


def test_integer_on_stored_string_number_returns_default(client):
    assert_type_mismatch(client.get_integer_details("getter.contract.string.number", 7), 7)


def test_float_on_stored_string_number_returns_default(client):
    assert_type_mismatch(client.get_float_details("getter.contract.string.number", 7.5), 7.5)


def test_string_on_stored_int_returns_default_not_its_text(client):
    assert_type_mismatch(client.get_string_details("getter.contract.int", "fallback"), "fallback")


def test_string_on_duration_returns_stored_iso_text(client):
    # The one string read of a non-string config: a duration has no OpenFeature
    # type, so it reads as its stored ISO 8601 text (qfg-pwrv).
    details = client.get_string_details("getter.contract.duration", "fallback")
    assert details.reason == Reason.STATIC
    assert details.error_code is None
    assert details.value == "PT30S"


def test_string_on_stored_bool_returns_default(client):
    assert_type_mismatch(client.get_string_details("getter.contract.bool", "fallback"), "fallback")


def test_boolean_on_stored_int_returns_default(client):
    assert_type_mismatch(client.get_boolean_details("getter.contract.int", True), True)


def test_integer_on_fractional_double_returns_default_not_truncated(client):
    assert_type_mismatch(client.get_integer_details("getter.contract.double", 7), 7)


def test_integer_on_unsafe_double_returns_default(client):
    assert_type_mismatch(client.get_integer_details("getter.contract.double.unsafe", 7), 7)


def test_integer_on_huge_double_returns_default(client):
    assert_type_mismatch(client.get_integer_details("getter.contract.double.huge", 7), 7)


def test_float_on_duration_returns_default(client):
    # Durations have no OpenFeature read path: use get_client().get_duration().
    assert_type_mismatch(client.get_float_details("getter.contract.duration", 5.0), 5.0)


def test_object_on_stored_string_returns_default(client):
    assert_type_mismatch(
        client.get_object_details("getter.contract.string", {"d": True}), {"d": True}
    )


def test_object_on_stored_bool_returns_default(client):
    assert_type_mismatch(
        client.get_object_details("getter.contract.bool", {"d": True}), {"d": True}
    )


# ---------------------------------------------------------------------------
# Matching and safely convertible types resolve
# ---------------------------------------------------------------------------


def test_boolean_on_bool_config(client):
    details = client.get_boolean_details("getter.contract.bool", False)
    assert details.value is True
    assert details.reason == Reason.STATIC
    assert details.error_code is None


def test_string_on_string_config(client):
    assert client.get_string_value("getter.contract.string", "") == "fast"


def test_integer_on_int_config(client):
    assert client.get_integer_value("getter.contract.int", 0) == 30


def test_float_on_int_config_converts(client):
    value = client.get_float_value("getter.contract.int", 0.0)
    assert value == 30.0
    assert isinstance(value, float)


def test_float_on_double_config(client):
    assert client.get_float_value("getter.contract.double", 0.0) == 3.9


def test_integer_on_whole_double_converts(client):
    value = client.get_integer_value("getter.contract.double.whole", 0)
    assert value == 3
    assert isinstance(value, int)


def test_object_on_json_config(client):
    assert client.get_object_value("getter.contract.json", {}) == {"a": 1}


def test_object_on_string_list_config(client):
    assert client.get_object_value("getter.contract.string_list", []) == ["a", "b"]


# ---------------------------------------------------------------------------
# Malformed values and resolution errors return the default
#
# sdk-python 3.1 reports a malformed stored number and a malformed ENV_VAR value
# as reason ERROR with error code PARSE_ERROR, and the provider passes it
# straight through (qfg-wg1n; 3.0 reported GENERAL, 2.x TYPE_MISMATCH). An
# unset ENV_VAR stays GENERAL.
# ---------------------------------------------------------------------------


def test_float_on_malformed_double_returns_default(client):
    assert_error(
        client.get_float_details("getter.contract.double.malformed", 1.5),
        1.5,
        ErrorCode.PARSE_ERROR,
    )


def test_integer_on_malformed_int_returns_default(client):
    assert_error(
        client.get_integer_details("getter.contract.int.malformed", 12), 12, ErrorCode.PARSE_ERROR
    )


def test_boolean_on_unset_env_var_returns_default(client, monkeypatch):
    monkeypatch.delenv("QUONFIG_ITD_GETTER_UNSET_BOOL", raising=False)
    assert_error(
        client.get_boolean_details("getter.contract.provided.bool.missing", True),
        True,
        ErrorCode.GENERAL,
    )


def test_integer_on_malformed_env_var_returns_default(client, monkeypatch):
    monkeypatch.setenv("QUONFIG_ITD_GETTER_INT", "twelve")
    assert_error(
        client.get_integer_details("getter.contract.provided.int.malformed", 4),
        4,
        ErrorCode.PARSE_ERROR,
    )


def test_float_on_malformed_env_var_returns_default(client, monkeypatch):
    monkeypatch.setenv("QUONFIG_ITD_GETTER_DOUBLE", "abc")
    assert_error(
        client.get_float_details("getter.contract.provided.double.malformed", 2.5),
        2.5,
        ErrorCode.PARSE_ERROR,
    )
