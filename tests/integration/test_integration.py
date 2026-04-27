"""End-to-end integration via the OpenFeature ``api`` singleton."""

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
    assert of_client.get_boolean_value("my-flag", False) is True


def test_resolves_string_config(of_client):
    assert of_client.get_string_value("my-string", "") == "hello"


def test_resolves_integer_config(of_client):
    assert of_client.get_integer_value("my-int", 0) == 42


def test_resolves_float_config(of_client):
    assert of_client.get_float_value("my-float", 0.0) == 3.14


def test_resolves_string_list_as_object(of_client):
    assert of_client.get_object_value("my-list", []) == ["a", "b", "c"]


def test_resolves_json_as_object(of_client):
    assert of_client.get_object_value("my-json", {}) == {"foo": "bar"}


def test_targeting_rule_pro_user_gets_true(of_client):
    ec = EvaluationContext(attributes={"user.plan": "pro"})
    assert of_client.get_boolean_value("plan-flag", False, ec) is True


def test_targeting_rule_free_user_gets_false(of_client):
    ec = EvaluationContext(attributes={"user.plan": "free"})
    assert of_client.get_boolean_value("plan-flag", False, ec) is False


def test_returns_default_for_missing_boolean(of_client):
    assert of_client.get_boolean_value("does-not-exist", False) is False
    assert of_client.get_boolean_value("does-not-exist", True) is True


def test_returns_default_for_missing_string(of_client):
    assert of_client.get_string_value("does-not-exist", "fallback") == "fallback"
