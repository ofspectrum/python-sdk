"""Live SDK checks against the local regression stack (skill: neo-regression).

Skipped unless E2E_API_BASE is set; tools/regression/e2e.ps1 sdk runs them on 8ka
with the stack's e2e.env. They use the real SDK over HTTP with a real API key and
must pass with the notebook immutable-write cutover ON and OFF.
"""

import json
import os
import secrets
import subprocess
import urllib.request

import pytest

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import OfSpectrumError

API = os.environ.get("E2E_API_BASE", "").rstrip("/")
pytestmark = pytest.mark.skipif(not API, reason="E2E_API_BASE not set (regression stack required)")

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63f8cfc0f01f0005000101ff89993d1d"
    "0000000049454e44ae426082"
)


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


def _immutable():
    return _sql("select enabled from public.watermark_notebook_immutable_write_cutover_state where control_key='global'") == "t"


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
        status, key = _http("POST", f"{API}/api/v1/api-keys", {"name": "e2e sdk"}, {"Authorization": f"Bearer {tok['access_token']}"})
        assert status == 200, status
        token_id = _sql("select gen_random_uuid()")
        _sql(
            "insert into public.watermark_tokens(id,user_id,name,public_key,token_val,token_type,max_private_notes) values "
            f"('{token_id}','{user_id}','e2e sdk',{100000 + secrets.randbelow(1_900_000)},"
            "lpad((1048576+floor(random()*500000000))::bigint::bit(64)::text,100,'0'),'pro',10);"
        )
        client = OfSpectrum(api_key=key["api_key"], base_url=f"{API}/api/v1")
        yield client, token_id
    finally:
        _http("DELETE", f"{sb}/auth/v1/admin/users/{user_id}", None, admin)


def test_sdk_create_notebook_with_text(account):
    client, token_id = account
    text = f"created by the SDK {secrets.token_hex(4)}"
    note = client.notebooks.create(token_id=token_id, note_name=f"sdk-{secrets.token_hex(3)}", text_content=text, is_public=False, credential_val=f"c-{secrets.token_hex(4)}")
    assert note.text_content == text
    assert client.notebooks.get(note.id).text_content == text
    # the same three times in a row (the report: "every time 409")
    for i in range(3):
        n = client.notebooks.create(token_id=token_id, note_name=f"sdk-{secrets.token_hex(3)}", text_content=f"again {i}", is_public=False, credential_val=f"c-{secrets.token_hex(4)}")
        assert client.notebooks.get(n.id).text_content == f"again {i}"


def test_sdk_deleted_media_download_is_not_found(account, tmp_path):
    client, token_id = account
    note = client.notebooks.create(token_id=token_id, note_name=f"sdk-media-{secrets.token_hex(3)}", text_content="media", is_public=False, credential_val=f"c-{secrets.token_hex(4)}")
    keep_file, gone_file = tmp_path / "keep.png", tmp_path / "gone.png"
    keep_file.write_bytes(PNG + secrets.token_bytes(8))
    gone_file.write_bytes(PNG + secrets.token_bytes(8))
    keep = client.notebooks.upload_media(note.id, keep_file)
    gone = client.notebooks.upload_media(note.id, gone_file)
    assert client.notebooks.download_media(gone["id"]) == gone_file.read_bytes()
    assert client.notebooks.delete_media(gone["id"], note_id=note.id) is True
    for _ in range(3):
        with pytest.raises(OfSpectrumError) as exc:
            client.notebooks.download_media(gone["id"])
        assert exc.value.status_code == 404, (exc.value.status_code, _immutable())
    assert client.notebooks.download_media(keep["id"]) == keep_file.read_bytes()
    assert [m["id"] for m in client.notebooks.list_media(note.id)] == [keep["id"]]


def test_sdk_update_and_delete_notebook(account):
    client, token_id = account
    note = client.notebooks.create(token_id=token_id, note_name=f"sdk-upd-{secrets.token_hex(3)}", is_public=False, credential_val=f"c-{secrets.token_hex(4)}")
    updated = client.notebooks.update(note.id, text_content="updated text")
    assert updated.text_content == "updated text"
    assert client.notebooks.get(note.id).text_content == "updated text"
    assert client.notebooks.delete(note.id) is True
    with pytest.raises(OfSpectrumError):
        client.notebooks.get(note.id)
