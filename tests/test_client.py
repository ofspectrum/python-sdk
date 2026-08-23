import httpx
import pytest

from ofspectrum.client import AsyncOfSpectrum, OfSpectrum, _checked_response
from ofspectrum.exceptions import (
    AuthenticationError,
    ResourceNotFoundError,
    ServiceUnavailableError,
)


def test_client_version_headers_match_release():
    client = OfSpectrum(api_key="test-key")
    try:
        assert client._default_headers()["User-Agent"] == "OfSpectrum-Python-SDK/1.3.0"
    finally:
        client.close()


@pytest.mark.asyncio
async def test_async_client_closes_persistent_stream_pools(monkeypatch):
    closed = []

    async with AsyncOfSpectrum(api_key="test-key") as client:
        monkeypatch.setattr(
            client.audio,
            "close_stream_pools",
            lambda: closed.append(True),
        )

    assert closed == [True]


def test_checked_response_maps_plain_fastapi_authentication_error():
    response = httpx.Response(401, json={"detail": "Authentication required"})

    with pytest.raises(AuthenticationError):
        _checked_response(response)


def test_checked_response_maps_plain_not_found_error():
    response = httpx.Response(404, json={"detail": "Notebook not found"})

    with pytest.raises(ResourceNotFoundError):
        _checked_response(response)


def test_checked_response_sanitizes_non_json_service_error():
    response = httpx.Response(503, content=b"<html>upstream details</html>")

    with pytest.raises(ServiceUnavailableError) as exc:
        _checked_response(response)

    assert "upstream details" not in str(exc.value)


def test_current_notebook_get_uses_authenticated_http_transport():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/v1/watermark-notes/note-1"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "id": "note-1",
                "token_id": "token-1",
                "note_name": "Current",
                "revision": 3,
                "media": [],
            },
        )

    client = OfSpectrum(api_key="test-key")
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    try:
        notebook = client.notebooks.get("note-1")
    finally:
        client.close()

    assert notebook.revision == 3
    assert notebook.media == []


def test_save_session_preserves_auth_and_idempotency_headers():
    session_id = "11111111-1111-4111-8111-111111111111"

    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/v1/watermark-notes/note-1/save-sessions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Idempotency-Key"] == "begin-key"
        return httpx.Response(
            200,
            json={
                "save_session_id": session_id,
                "notebook_id": "note-1",
                "state": "active",
                "expires_at": "2026-08-01T00:00:00Z",
                "created": True,
            },
        )

    client = OfSpectrum(api_key="test-key")
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url,
        headers=client._default_headers(),
        transport=httpx.MockTransport(handler),
    )
    try:
        session = client.notebook_commits.begin(
            "note-1", idempotency_key="begin-key"
        )
    finally:
        client.close()

    assert session.save_session_id == session_id
