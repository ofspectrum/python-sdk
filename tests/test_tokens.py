import pytest

from ofspectrum.models.token import AiAuthTag, Token, TokenCreateParams, TokenUpdateParams
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


def test_token_maps_unlimited_private_notebooks_to_none():
    token = Token.from_dict(
        {
            "id": "token-1",
            "name": "Voice",
            "token_type": "pro",
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


def test_update_params_include_upgrade_and_ai_auth_configuration():
    params = TokenUpdateParams(
        token_type="pro",
        public_key=123,
        ai_auth_enabled=False,
        ai_auth_price=None,
        ai_auth_other_instructions="",
        ai_auth_tags=[],
    )

    assert params.to_dict() == {
        "token_type": "pro",
        "public_key": 123,
        "ai_auth_enabled": False,
        "ai_auth_price": None,
        "ai_auth_other_instructions": "",
        "ai_auth_tags": [],
    }


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
