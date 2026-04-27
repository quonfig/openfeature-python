from openfeature.evaluation_context import EvaluationContext

from quonfig_openfeature.context import map_context


def test_splits_dot_notation_keys_into_namespace_and_property():
    result = map_context({"user.email": "alice@co.com"})
    assert result == {"user": {"email": "alice@co.com"}}


def test_keys_without_dot_go_to_default_empty_namespace():
    result = map_context({"country": "US"})
    assert result == {"": {"country": "US"}}


def test_targeting_key_uses_default_user_id_mapping():
    result = map_context({"targetingKey": "user-123"})
    assert result == {"user": {"id": "user-123"}}


def test_targeting_key_via_custom_mapping():
    result = map_context({"targetingKey": "user-456"}, "org.userId")
    assert result == {"org": {"userId": "user-456"}}


def test_multi_dot_keys_split_on_first_dot_only():
    result = map_context({"user.ip.address": "1.2.3.4"})
    assert result == {"user": {"ip.address": "1.2.3.4"}}


def test_multiple_keys_in_different_namespaces():
    result = map_context(
        {
            "user.email": "alice@co.com",
            "org.tier": "enterprise",
            "country": "US",
        }
    )
    assert result == {
        "user": {"email": "alice@co.com"},
        "org": {"tier": "enterprise"},
        "": {"country": "US"},
    }


def test_merges_keys_into_same_namespace():
    result = map_context({"user.email": "a@b.com", "user.plan": "pro"})
    assert result == {"user": {"email": "a@b.com", "plan": "pro"}}


def test_targeting_key_with_no_dot_mapping():
    result = map_context({"targetingKey": "abc"}, "userId")
    assert result == {"": {"userId": "abc"}}


def test_skips_none_values():
    result = map_context({"user.email": None, "user.plan": "pro"})
    assert result == {"user": {"plan": "pro"}}


def test_empty_context_returns_empty_dict():
    assert map_context({}) == {}
    assert map_context(None) == {}


def test_works_with_evaluation_context_dataclass():
    ec = EvaluationContext(
        targeting_key="user-789",
        attributes={"user.plan": "pro", "country": "US"},
    )
    result = map_context(ec)
    assert result == {
        "user": {"id": "user-789", "plan": "pro"},
        "": {"country": "US"},
    }


def test_evaluation_context_with_custom_targeting_mapping():
    ec = EvaluationContext(targeting_key="acct-1", attributes={})
    result = map_context(ec, "account.id")
    assert result == {"account": {"id": "acct-1"}}
