"""Live SDK checks for tokens and quotas against the regression stack (skill: neo-regression).

Skipped unless E2E_API_BASE is set. The SDK talks to the real API with a real API key; the
account is funded through the real checkout flow (Stripe fake + signed webhook).
"""

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import time
import urllib.request

import pytest

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import OfSpectrumError

API = os.environ.get("E2E_API_BASE", "").rstrip("/")
pytestmark = pytest.mark.skipif(not API, reason="E2E_API_BASE not set (regression stack required)")

ORIGIN = {"Origin": "http://127.0.0.1:3100"}


def _http(method, url, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if raw is None:
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


def _fund(user_id, jwt, micro):
    """Credit cash through checkout-session + a signed checkout.session.completed webhook."""
    status, sess = _http("POST", f"{API}/api/v1/billing/checkout-session",
                         {"kind": "wallet_custom_topup", "amount_micro_usd": micro}, {"Authorization": f"Bearer {jwt}"})
    assert status == 200, status
    sid = sess["sessionId"]
    order_id = _sql(f"select id from public.orders where stripe_checkout_session_id = '{sid}'")
    event = {"id": "evt_sdk_" + secrets.token_hex(5), "type": "checkout.session.completed", "livemode": False,
             "data": {"object": {"id": sid, "payment_status": "paid",
                                 "metadata": {"order_id": order_id, "user_id": user_id}}}}
    payload = json.dumps(event).encode()
    ts = str(int(time.time()))
    sig = hmac.new(os.environ["STRIPE_WEBHOOK_SECRET"].encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    status, _ = _http("POST", f"{API}/api/v1/stripe/webhook", headers={"Stripe-Signature": f"t={ts},v1={sig}"}, raw=payload)
    assert status == 200, status


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
        assert _http("POST", f"{API}/api/v1/auth/login", {"email": email, "password": password}, ORIGIN)[0] == 200
        status, tok = _http("POST", f"{sb}/auth/v1/token?grant_type=password", {"email": email, "password": password}, {"apikey": anon})
        assert status == 200, status
        jwt = tok["access_token"]
        status, key = _http("POST", f"{API}/api/v1/api-keys", {"name": "e2e sdk tokens"}, {"Authorization": f"Bearer {jwt}"})
        assert status == 200, status
        client = OfSpectrum(api_key=key["api_key"], base_url=f"{API}/api/v1")
        yield client, user_id, jwt
    finally:
        _http("DELETE", f"{sb}/auth/v1/admin/users/{user_id}", None, admin)


def _cash(user_id):
    return int(_sql(f"select coalesce(sum(cash_amount_micro_usd),0) from public.billing_transactions where user_id = '{user_id}'") or 0)


def test_sdk_create_without_funds_is_payment_required(account):
    client, user_id, _ = account
    with pytest.raises(OfSpectrumError) as exc:
        client.tokens.create(name=f"poor-{secrets.token_hex(3)}")
    assert exc.value.status_code == 402, exc.value.status_code
    assert _sql(f"select count(*) from public.watermark_tokens where user_id = '{user_id}' and not is_system_managed") == "0"


def test_sdk_token_lifecycle_charges_and_validates(account):
    client, user_id, jwt = account
    _fund(user_id, jwt, 10_000_000)
    assert _cash(user_id) == 10_000_000

    name = f"sdk-std-{secrets.token_hex(3)}"
    token = client.tokens.create(name=name)
    assert token.name == name and token.token_type == "standard" and token.public_key == 258
    assert _cash(user_id) == 9_000_000, "a standard token costs $1"

    # The same name again is a conflict for API-key callers (the SDK), and costs nothing.
    with pytest.raises(OfSpectrumError) as exc:
        client.tokens.create(name=name)
    assert exc.value.status_code == 409, exc.value.status_code
    assert _cash(user_id) == 9_000_000

    # Pro tokens need a verification key (checked by the SDK before any request) and cost $2.
    with pytest.raises(ValueError):
        client.tokens.create(name=f"sdk-pro-{secrets.token_hex(3)}", token_type="pro")
    assert _cash(user_id) == 9_000_000
    pro = client.tokens.create(name=f"sdk-pro-{secrets.token_hex(3)}", token_type="pro", public_key=424242)
    assert pro.token_type == "pro" and pro.public_key == 424242 and pro.max_private_notes == 5
    assert _cash(user_id) == 7_000_000

    # Read, list, update.
    assert client.tokens.get(token.id).id == token.id
    assert {t.id for t in client.tokens.list()} >= {token.id, pro.id}
    renamed = client.tokens.update(token.id, name=name + "-renamed", ai_auth_enabled=True, ai_auth_tags=["alpha", "beta"])
    assert renamed.name == name + "-renamed" and renamed.ai_auth_enabled is True
    assert sorted(client.tokens.get(token.id).ai_auth_tags) == ["alpha", "beta"]
    with pytest.raises(OfSpectrumError) as exc:
        client.tokens.update(token.id, public_key=5)  # standard tokens have a fixed key
    assert exc.value.status_code == 400, exc.value.status_code

    # Unknown and foreign tokens are not found.
    with pytest.raises(OfSpectrumError) as exc:
        client.tokens.get("00000000-0000-4000-8000-000000000009")
    assert exc.value.status_code == 404, exc.value.status_code

    # AI authorization tags round trip.
    tag = client.tokens.create_ai_auth_tag(f"tag-{secrets.token_hex(3)}")
    assert tag.tag in [t.tag for t in client.tokens.list_ai_auth_tags()]


def test_sdk_quotas_are_readable(account):
    client, _, _ = account
    quota = client.quotas.get_encode_quota()
    assert quota.limit >= 0 and quota.used >= 0
    assert client.quotas.get_decode_quota().limit >= 0
