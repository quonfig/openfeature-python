"""End-to-end integration via the OpenFeature ``api`` singleton.

Exercises the full pipeline against the shared ``integration-test-data``
corpus — same fixtures the Go provider uses — so cross-SDK regressions
in flag layout get caught here too.
"""

from __future__ import annotations

import pytest
from openfeature import api
from openfeature.evaluation_context import EvaluationContext

from quonfig_openfeature import QuonfigProvider


@pytest.fixture(scope="module")
def of_client(fixtures_dir):
    provider = QuonfigProvider(
        sdk_key="test-sdk-key",
        datadir=fixtures_dir,
        environment="Production",
        collect_evaluation_summaries=False,
        context_upload_mode="none",
    )
    api.set_provider(provider, domain="integration-test")
    client = api.get_client(domain="integration-test")
    yield client
    api.shutdown()


def test_resolves_boolean_flag(of_client):
    assert of_client.get_boolean_value("always.true", False) is True


def test_resolves_string_config(of_client):
    assert of_client.get_string_value("my-test-key", "") == "my-test-value"


def test_resolves_integer_config(of_client):
    assert of_client.get_integer_value("jeffreys.test.int", 0) == 99


def test_resolves_float_config(of_client):
    assert of_client.get_float_value("my-double-key", 0.0) == 9.95


def test_resolves_string_list_as_object(of_client):
    assert of_client.get_object_value("my-string-list-key", []) == ["a", "b", "c"]


def test_resolves_json_as_object(of_client):
    assert of_client.get_object_value("test.json", {}) == {"a": 1, "b": "c"}


def test_targeting_rule_pro_user_gets_true(of_client):
    ec = EvaluationContext(attributes={"user.plan": "pro"})
    assert of_client.get_boolean_value("of.targeting", False, ec) is True


def test_targeting_rule_free_user_gets_false(of_client):
    ec = EvaluationContext(attributes={"user.plan": "free"})
    assert of_client.get_boolean_value("of.targeting", True, ec) is False


def test_returns_default_for_missing_boolean(of_client):
    assert of_client.get_boolean_value("does-not-exist", False) is False
    assert of_client.get_boolean_value("does-not-exist", True) is True


def test_returns_default_for_missing_string(of_client):
    assert of_client.get_string_value("does-not-exist", "fallback") == "fallback"
