"""Live SDK audio checks against the local regression stack (skill: neo-regression).

Skipped unless E2E_API_BASE is set; tools/regression/e2e.ps1 sdk runs them on 8ka with
the stack's e2e.env. They use the real SDK over HTTP with a real API key. The model
calls go to the staging model gate through the stack's relay (a few 6 s clips); when
it is unreachable the encode/decode checks skip. There is no real text-to-speech
provider access: sdk.tts stays unit-test only.
"""

import json
import os
import secrets
import subprocess
import urllib.request
import wave
from pathlib import Path

import pytest

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import OfSpectrumError

API = os.environ.get("E2E_API_BASE", "").rstrip("/")
pytestmark = pytest.mark.skipif(not API, reason="E2E_API_BASE not set (regression stack required)")

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "audio" / "sample-broadband-10s.wav"


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


def _clip(path: Path, seconds: int) -> Path:
    """The first `seconds` of the sample as a PCM16 WAV."""
    with wave.open(str(SAMPLE), "rb") as src:
        params = src.getparams()
        frames = src.readframes(params.framerate * seconds)
    with wave.open(str(path), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)
    return path


def _remaining(user_id, service):
    return int(_sql(
        "select coalesce(sum(remaining_amount),0)::bigint from public.billing_quota_grants "
        f"where user_id = '{user_id}' and service_name = '{service}' and unit = 'second' and status = 'active' and expires_at > now();"
    ))


def _grant(user_id, service, seconds):
    _sql(
        "insert into public.billing_quota_grants (user_id, service_name, unit, original_amount, remaining_amount, status, expires_at, source_type, priority) "
        f"values ('{user_id}', '{service}', 'second', {seconds}, {seconds}, 'active', now() + interval '30 days', 'admin', 100);"
    )


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
        status, key = _http("POST", f"{API}/api/v1/api-keys", {"name": "e2e sdk audio"}, {"Authorization": f"Bearer {tok['access_token']}"})
        assert status == 200, status
        token_id = _sql("select gen_random_uuid()")
        _sql(
            "insert into public.watermark_tokens(id,user_id,name,public_key,token_val,token_type,max_private_notes) values "
            f"('{token_id}','{user_id}','e2e sdk',{100000 + secrets.randbelow(1_900_000)},"
            "lpad((1048576+floor(random()*500000000))::bigint::bit(64)::text,100,'0'),'pro',10);"
        )
        client = OfSpectrum(api_key=key["api_key"], base_url=f"{API}/api/v1")
        yield client, token_id, user_id
    finally:
        _http("DELETE", f"{sb}/auth/v1/admin/users/{user_id}", None, admin)


def test_sdk_audio_refusals(account, tmp_path):
    client, token_id, user_id = account
    clip = _clip(tmp_path / "clip.wav", 6)
    # No balance: refused before any model call; nothing is billed.
    with pytest.raises(OfSpectrumError) as exc:
        client.audio.encode(clip, token_id=token_id)
    assert exc.value.status_code == 402, exc.value.status_code
    with pytest.raises(OfSpectrumError) as exc:
        client.audio.decode(clip)
    assert exc.value.status_code == 402, exc.value.status_code
    _grant(user_id, "AudioWatermarkEncode", 30)
    # An unknown token is a clean 404, not a server error.
    with pytest.raises(OfSpectrumError) as exc:
        client.audio.encode(clip, token_id=_sql("select gen_random_uuid()"))
    assert exc.value.status_code == 404, exc.value.status_code
    # Strength outside 0.1-2.0 is rejected by the service.
    with pytest.raises(Exception):
        client.audio.encode(clip, token_id=token_id, strength=5.0)
    assert _remaining(user_id, "AudioWatermarkEncode") == 30
    # The quota API reflects the grant.
    assert client.quotas.get_encode_quota().remaining == 30
    assert client.quotas.check_encode_available(6) is True
    assert client.quotas.check_encode_available(31) is False


def test_sdk_audio_encode_decode_roundtrip(account, tmp_path):
    client, token_id, user_id = account
    clip = _clip(tmp_path / "clip.wav", 6)
    _grant(user_id, "AudioWatermarkEncode", 12)
    _grant(user_id, "AudioWatermarkDecode", 18)
    out = tmp_path / "marked.wav"
    try:
        result = client.audio.encode(clip, token_id=token_id, output_path=out, verify_and_reencode=True)
    except OfSpectrumError as exc:
        if exc.status_code in (502, 503, 504):
            pytest.skip(f"model gate unavailable: {exc.status_code}")
        raise
    assert result.success and result.token_id == token_id
    assert out.exists() and out.read_bytes()[:4] == b"RIFF"
    assert result.audio_duration == pytest.approx(6.0, abs=0.1)
    assert _remaining(user_id, "AudioWatermarkEncode") == 6

    # With an API key the owner's private token is revealed only for its public key.
    public_key = int(_sql(f"select public_key from public.watermark_tokens where id = '{token_id}'"))
    hidden = client.audio.decode(out)
    assert hidden.watermarked is False and hidden.token_id is None
    found = client.audio.decode(out, public_key=public_key)
    # API-key answers are the simplified shape (no owner/public access label).
    assert found.watermarked is True and found.token_id == token_id
    clean = client.audio.decode(clip, public_key=public_key)
    assert clean.watermarked is False and clean.token_id is None
    assert _remaining(user_id, "AudioWatermarkDecode") == 0
    # The decode quota is spent: the next decode is refused with 402.
    with pytest.raises(OfSpectrumError) as exc:
        client.audio.decode(out, public_key=public_key)
    assert exc.value.status_code == 402


def test_sdk_audio_encode_json_download(account, tmp_path):
    client, token_id, user_id = account
    clip = _clip(tmp_path / "clip.wav", 6)
    _grant(user_id, "AudioWatermarkEncode", 6)
    try:
        result = client.audio.encode(clip, token_id=token_id, response_format="json")
    except OfSpectrumError as exc:
        if exc.status_code in (502, 503, 504):
            pytest.skip(f"model gate unavailable: {exc.status_code}")
        raise
    assert result.download_url and result.expires_in == 3600
    with urllib.request.urlopen(result.download_url, timeout=60) as resp:
        body = resp.read()
    assert body[:4] == b"RIFF" and len(body) > 1000
