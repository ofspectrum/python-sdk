"""Live SDK checks for the account surface against the regression stack.

Skipped unless E2E_API_BASE is set (tools/regression/e2e.ps1 sdk). Real API key
over HTTP; the checks hold with the notebook immutable-write cutover ON and OFF.
Covers: quotas read with an API key, authentication failures (unknown and
revoked keys), and the account-only boundary of API keys and webhooks.
"""

import json
import os
import secrets
import subprocess
import urllib.request

import pytest

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import AuthenticationError, OfSpectrumError
from ofspectrum.resources.webhooks import WebhooksResource

API = os.environ.get("E2E_API_BASE", "").rstrip("/")
pytestmark = pytest.mark.skipif(not API, reason="E2E_API_BASE not set (regression stack required)")


def _http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _sql(query):
    out = subprocess.run(
        ["docker", "exec", "-i", os.environ["E2E_DB_CONTAINER"], "psql", "-U", "postgres", "-X", "-q", "-t", "-A",
         "-v", "ON_ERROR_STOP=1"],
        input=query, capture_output=True, text=True, check=True, timeout=60,
    )
    return out.stdout.strip()


@pytest.fixture
def account():
    sb = os.environ["E2E_SUPABASE_URL"].rstrip("/")
    svc, anon = os.environ["SUPABASE_SERVICE_ROLE_KEY"], os.environ["SUPABASE_ANON_KEY"]
    email, password = f"e2e-sdk-{secrets.token_hex(5)}@example.com", f"Pw-{secrets.token_hex(8)}-aA1!"
    admin = {"apikey": svc, "Authorization": f"Bearer {svc}"}
    status, user = _http("POST", f"{sb}/auth/v1/admin/users", {"email": email, "password": password, "email_confirm": True}, admin)
    assert status // 100 == 2, status
    user_id = user["id"]
    try:
        _sql(f"insert into public.profile (id, user_type, created_at, updated_at) values ('{user_id}', 'normal', now(), now()) on conflict (id) do nothing;")
        status, _ = _http("POST", f"{API}/api/v1/auth/login", {"email": email, "password": password}, {"Origin": "http://127.0.0.1:3100"})
        assert status == 200, status
        status, tok = _http("POST", f"{sb}/auth/v1/token?grant_type=password", {"email": email, "password": password}, {"apikey": anon})
        assert status == 200, status
        jwt = {"Authorization": f"Bearer {tok['access_token']}"}
        status, key = _http("POST", f"{API}/api/v1/api-keys", {"name": "e2e sdk account"}, jwt)
        assert status == 200, status
        client = OfSpectrum(api_key=key["api_key"], base_url=f"{API}/api/v1")
        yield client, user_id, key, jwt
    finally:
        _http("DELETE", f"{sb}/auth/v1/admin/users/{user_id}", None, admin)


def _grant(user_id, service, original, remaining):
    _sql(
        "insert into public.billing_quota_grants (user_id, service_name, unit, original_amount, remaining_amount, status, expires_at, source_type, priority) "
        f"values ('{user_id}', '{service}', 'second', {original}, {remaining}, 'active', now() + interval '30 days', 'admin', 100);"
    )


def test_sdk_quota_reflects_granted_seconds(account):
    client, user_id, _, _ = account
    assert client.quotas.get_encode_quota().limit == 0
    assert client.quotas.check_encode_available(1) is False
    _grant(user_id, "AudioWatermarkEncode", 100, 40)
    quota = client.quotas.get_encode_quota()
    assert (quota.limit, quota.used, quota.remaining) == (100, 60, 40)
    assert quota.reset_at is not None
    assert client.quotas.check_encode_available(40) is True
    assert client.quotas.check_encode_available(41) is False
    # Decode quota is a separate service.
    assert client.quotas.get_decode_quota().limit == 0


def test_sdk_rejects_unknown_and_revoked_api_keys(account):
    client, _, key, jwt = account
    assert client.quotas.get_encode_quota().limit == 0  # the key works
    stranger = OfSpectrum(api_key=secrets.token_hex(32), base_url=f"{API}/api/v1")
    with pytest.raises(AuthenticationError) as exc:
        stranger.quotas.get_encode_quota()
    assert exc.value.status_code == 401
    # Revoke the key through the account session: the SDK must stop working at once.
    status, body = _http("DELETE", f"{API}/api/v1/api-keys/{key['id']}", None, jwt)
    assert status == 200, (status, body)
    with pytest.raises(AuthenticationError):
        client.quotas.get_encode_quota()


def test_sdk_webhooks_are_readable_but_configured_by_the_account_session(account):
    client, _, _, _ = account
    hooks = WebhooksResource(client)
    assert hooks.list() == []
    names = [e["name"] for e in hooks.get_supported_events()]
    assert "encode.completed" in names and len(names) == 6
    # Creating or changing webhooks (and API keys) is an account-session action, not an API-key one.
    with pytest.raises(OfSpectrumError) as exc:
        hooks.create(url="https://example.com/hook", events=["token.created"])
    assert exc.value.status_code == 404
    assert hooks.list() == []
