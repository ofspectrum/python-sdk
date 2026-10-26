from typing import get_type_hints

import pytest

from ofspectrum.models.token import (
    UNSET,
    AiAuthTag,
    Token,
    TokenCreateParams,
    TokenUpdateParams,
)
from ofspectrum.resources.tokens import TokensResource


class _Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


def test_token_parses_ai_auth_fields():
    token = Token.from_dict(
        {
            "id": "token-1",
            "name": "Voice",
            "token_type": "pro",
            "ai_auth_enabled": True,
            "ai_auth_access_type": "premium_track",
            "ai_auth_price": 10,
            "ai_auth_other_instructions": "Contact the owner",
            "ai_auth_tags": ["voice", "licensed"],
            "max_private_notes": 1,
        }
    )

    assert token.ai_auth_enabled is True
    assert token.ai_auth_access_type == "premium_track"
    assert token.ai_auth_price == 10
    assert token.ai_auth_tags == ["voice", "licensed"]
    assert token.max_private_notes == 1


def test_token_parses_notebook_settings_without_coercing_invalid_values():
    token = Token.from_dict(
        {
            "id": "token-1",
            "name": "Voice",
            "token_type": "pro",
            "version_control_override": None,
            "storage_auto_expand_override": False,
            "version_control_enabled": True,
            "storage_auto_expand_enabled": "invalid",
            "storage_entitlement_bytes": "1024",
        }
    )

    assert token.version_control_override is None
    assert token.storage_auto_expand_override is False
    assert token.version_control_enabled is True
    assert token.storage_auto_expand_enabled is False
    assert token.storage_entitlement_bytes == 1024


def test_token_exposes_pro_private_notebook_limit():
    token = Token.from_dict(
        {
            "id": "token-1",
            "name": "Voice",
            "token_type": "pro",
            "max_private_notes": 5,
        }
    )

    assert token.max_private_notes == 5


def test_token_exposes_standard_zero_new_private_notebook_limit():
    token = Token.from_dict(
        {
            "id": "token-standard",
            "name": "Standard Voice",
            "token_type": "standard",
            "max_private_notes": 0,
        }
    )

    assert token.max_private_notes == 0


def test_token_exposes_enterprise_private_notebook_limit():
    token = Token.from_dict(
        {
            "id": "token-1",
            "name": "Enterprise Voice",
            "token_type": "enterprise",
            "max_private_notes": 10,
        }
    )

    assert token.max_private_notes == 10


def test_token_preserves_legacy_unlimited_private_notebook_compatibility():
    token = Token.from_dict(
        {
            "id": "token-legacy",
            "name": "Legacy Token",
            "token_type": "enterprise",
            "max_private_notes": -1,
        }
    )

    assert token.max_private_notes is None


def test_create_params_include_ai_auth_configuration():
    params = TokenCreateParams(
        name="Voice",
        token_type="pro",
        public_key=123,
        ai_auth_enabled=True,
        ai_auth_access_type="direct_use",
        ai_auth_price=5,
        ai_auth_other_instructions="Attribution required",
        ai_auth_tags=["voice"],
    )

    assert params.to_dict() == {
        "name": "Voice",
        "token_type": "pro",
        "public_key": 123,
        "ai_auth_enabled": True,
        "ai_auth_access_type": "direct_use",
        "ai_auth_price": 5,
        "ai_auth_other_instructions": "Attribution required",
        "ai_auth_tags": ["voice"],
    }


def test_create_params_accept_quality_without_sending_an_override():
    params = TokenCreateParams(name="Voice", encoding_profile="quality")

    assert "encoding_profile" not in params.to_dict()


def test_token_resource_quality_choice_does_not_send_forbidden_backend_field(monkeypatch):
    resource = TokensResource(client=None)
    requests = []
    def post(path, json):
        requests.append((path, json))
        return _Response({"id": "token-1", "name": json["name"], "token_type": "standard"})
    monkeypatch.setattr(resource, "_post", post)
    resource.create("Voice", encoding_profile="quality")
    assert requests == [("/tokens/", {"name": "Voice", "token_type": "standard"})]


@pytest.mark.parametrize("value", ["robust", "unknown", "QUALITY", True, 1])
def test_create_params_reject_unknown_encoding_profiles(value):
    with pytest.raises(ValueError, match="encoding_profile"):
        TokenCreateParams(name="Voice", encoding_profile=value)


def test_token_defaults_missing_encoding_profile_to_quality():
    token = Token.from_dict({"id": "token-1", "name": "Voice", "token_type": "standard"})

    assert token.encoding_profile == "quality"


def test_token_resource_rejects_unavailable_profile_before_request(monkeypatch):
    resource = TokensResource(client=None)
    monkeypatch.setattr(resource, "_post", lambda *_args, **_kwargs: pytest.fail("must not send"))

    with pytest.raises(ValueError, match="not available"):
        resource.create("Voice", encoding_profile="robust")


def test_token_update_does_not_accept_encoding_profile():
    resource = TokensResource(client=None)

    with pytest.raises(TypeError, match="encoding_profile"):
        resource.update("token-1", encoding_profile="robust")


def test_update_params_include_ai_auth_configuration():
    params = TokenUpdateParams(
        public_key=123,
        ai_auth_enabled=False,
        ai_auth_price=None,
        ai_auth_other_instructions="",
        ai_auth_tags=[],
    )

    assert params.to_dict() == {
        "public_key": 123,
        "ai_auth_enabled": False,
        "ai_auth_price": None,
        "ai_auth_other_instructions": "",
        "ai_auth_tags": [],
    }


@pytest.mark.parametrize("token_type", ["standard", "pro", "enterprise"])
def test_token_updates_reject_token_type_before_network(token_type):
    resource = TokensResource(client=None)
    with pytest.raises(TypeError, match="token_type"):
        resource.update("token-1", token_type=token_type)
    with pytest.raises(TypeError, match="token_type"):
        TokenUpdateParams(token_type=token_type)


@pytest.mark.parametrize("token_type", ["standard", "pro", "enterprise"])
@pytest.mark.parametrize("trailing_flags", [(), (True, False)])
def test_token_update_rejects_old_positional_type_before_network(
    monkeypatch, token_type, trailing_flags,
):
    resource = TokensResource(client=None)
    monkeypatch.setattr(
        resource, "_patch",
        lambda *_args, **_kwargs: pytest.fail("old positional type must not be sent"),
    )
    with pytest.raises(TypeError):
        resource.update("token-1", "Renamed", 123, token_type, *trailing_flags)


@pytest.mark.parametrize("token_type", ["standard", "pro", "enterprise"])
def test_token_update_params_reject_old_positional_type(token_type):
    with pytest.raises(ValueError, match="enterprise_verification"):
        TokenUpdateParams("Renamed", 123, token_type)


@pytest.mark.parametrize("field_name", ["enterprise_verification", "ai_auth_enabled"])
@pytest.mark.parametrize("value", ["pro", "false", 0, 1, 1.0, {}, UNSET])
def test_token_update_rejects_non_boolean_flags_before_network(monkeypatch, field_name, value):
    resource = TokensResource(client=None)
    monkeypatch.setattr(
        resource, "_patch",
        lambda *_args, **_kwargs: pytest.fail("invalid boolean flag must not be sent"),
    )
    with pytest.raises(ValueError, match=field_name):
        TokenUpdateParams(**{field_name: value})
    with pytest.raises(ValueError, match=field_name):
        resource.update("token-1", **{field_name: value})


@pytest.mark.parametrize("field_name", ["enterprise_verification", "ai_auth_enabled"])
@pytest.mark.parametrize("value", [None, False, True])
def test_token_update_params_preserve_boolean_flags(field_name, value):
    data = TokenUpdateParams(**{field_name: value}).to_dict()
    if value is None:
        assert field_name not in data
    else:
        assert data[field_name] is value


def test_token_update_preserves_rename_and_settings():
    resource = TokensResource(client=None)
    requests = []

    def patch(path, *, json):
        requests.append((path, json))
        return _Response({"id": "token-1", "token_type": "pro", **json})

    resource._patch = patch
    token = resource.update(
        "token-1", "Renamed", 123, enterprise_verification=False, ai_auth_enabled=True,
        version_control_override=None, storage_auto_expand_override=False,
    )
    assert token.name == "Renamed"
    assert token.token_type == "pro"
    assert requests == [("/tokens/token-1", {
        "name": "Renamed", "public_key": 123,
        "enterprise_verification": False, "ai_auth_enabled": True,
        "version_control_override": None, "storage_auto_expand_override": False,
    })]


@pytest.mark.parametrize("value", [None, False, True])
@pytest.mark.parametrize("params_type", [TokenCreateParams, TokenUpdateParams])
def test_token_params_preserve_explicit_override_states(params_type, value):
    params = params_type(
        name="Voice",
        version_control_override=value,
        storage_auto_expand_override=value,
    )

    assert params.to_dict()["version_control_override"] is value
    assert params.to_dict()["storage_auto_expand_override"] is value


@pytest.mark.parametrize("params_type", [TokenCreateParams, TokenUpdateParams])
def test_token_params_omit_unset_overrides(params_type):
    params = params_type(name="Voice")

    assert params.version_control_override is UNSET
    assert params.storage_auto_expand_override is UNSET
    assert "version_control_override" not in params.to_dict()
    assert "storage_auto_expand_override" not in params.to_dict()


@pytest.mark.parametrize("params_type", [TokenCreateParams, TokenUpdateParams])
def test_token_params_reject_non_boolean_overrides(params_type):
    with pytest.raises(ValueError, match="version_control_override"):
        params_type(name="Voice", version_control_override="true")


def test_token_override_annotations_are_not_any():
    create_hints = get_type_hints(TokenCreateParams)
    update_hints = get_type_hints(TokenUpdateParams)

    assert create_hints["version_control_override"] is not object
    assert update_hints["storage_auto_expand_override"] is not object


def test_pro_creation_requires_an_explicit_integer_public_key():
    with pytest.raises(ValueError, match="public_key is required"):
        TokenCreateParams(name="Pro", token_type="pro")

    with pytest.raises(ValueError, match="public_key must be an integer"):
        TokenCreateParams(name="Pro", token_type="pro", public_key=True)


def test_token_resource_sends_both_explicit_overrides(monkeypatch):
    resource = TokensResource(client=None)
    request = {}

    def fake_post(path, json):
        request.update(path=path, json=json)
        return _Response(
            {
                "id": "token-1",
                "name": "Pro",
                "token_type": "pro",
                "public_key": json["public_key"],
            }
        )

    monkeypatch.setattr(resource, "_post", fake_post)

    token = resource.create(
        "Pro",
        "pro",
        123,
        version_control_override=None,
        storage_auto_expand_override=True,
    )

    assert token.public_key == 123
    assert request == {
        "path": "/tokens/",
        "json": {
            "name": "Pro",
            "token_type": "pro",
            "public_key": 123,
            "version_control_override": None,
            "storage_auto_expand_override": True,
        },
    }


def test_token_resource_rejects_pro_without_request(monkeypatch):
    resource = TokensResource(client=None)
    monkeypatch.setattr(
        resource,
        "_post",
        lambda *_args, **_kwargs: pytest.fail("invalid Pro token must not be sent"),
    )

    with pytest.raises(ValueError, match="public_key is required"):
        resource.create("Pro", "pro")


def test_list_ai_auth_tags_returns_models(monkeypatch):
    resource = TokensResource(client=None)
    monkeypatch.setattr(
        resource,
        "_get",
        lambda path: _Response(
            [{"id": "tag-1", "tag": "voice", "created_at": "2026-01-01"}]
        ),
    )

    tags = resource.list_ai_auth_tags()

    assert tags == [AiAuthTag(id="tag-1", tag="voice", created_at="2026-01-01")]


def test_create_ai_auth_tag_posts_normalized_name(monkeypatch):
    resource = TokensResource(client=None)
    request = {}

    def fake_post(path, json):
        request.update(path=path, json=json)
        return _Response({"id": "tag-1", "tag": json["tag"]})

    monkeypatch.setattr(resource, "_post", fake_post)

    tag = resource.create_ai_auth_tag("  Voice Clone  ")

    assert request == {
        "path": "/tokens/ai-auth-tags",
        "json": {"tag": "Voice Clone"},
    }
    assert tag == AiAuthTag(id="tag-1", tag="Voice Clone")


def test_create_ai_auth_tag_rejects_empty_name():
    resource = TokensResource(client=None)

    with pytest.raises(ValueError, match="tag must not be empty"):
        resource.create_ai_auth_tag("   ")
