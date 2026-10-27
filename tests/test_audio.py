import ast
import io
import inspect
import json
from pathlib import Path
import re
import threading
from types import SimpleNamespace

import httpx
import pytest
import websockets.sync.client

from ofspectrum import DecodeMatch, DecodeResult, OfSpectrum
from ofspectrum.exceptions import OfSpectrumError
from ofspectrum.resources.audio import AudioResource


def test_public_audio_docs_match_sdk_interval_and_verification_defaults():
    docs = (Path(__file__).parents[2] / "frontend/src/docs/sdk/audio.ts").read_text(encoding="utf-8")
    signatures = re.findall(
        r"^[ \t]*(?:def\s+|audio\.)(encode|stream_encode|stream_encode_pcm|open_stream_pool)"
        r"\s*\((.*?)\)\s*->[^\n`]+", docs, flags=re.DOTALL | re.MULTILINE,
    )
    assert len(signatures) == 8, "Check both overview and detailed signatures for every method"
    seen = {name: 0 for name in ("encode", "stream_encode", "stream_encode_pcm", "open_stream_pool")}
    for method, parameters in signatures:
        seen[method] += 1
        actual = inspect.signature(getattr(AudioResource, method)).parameters
        parsed = ast.parse(f"def documented({parameters}):\n    pass").body[0].args
        documented = {}
        positional_defaults = [None] * (len(parsed.args) - len(parsed.defaults)) + list(parsed.defaults)
        for arg, default in zip(parsed.args, positional_defaults):
            documented[arg.arg] = (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.empty if default is None else ast.literal_eval(default))
        for arg, default in zip(parsed.kwonlyargs, parsed.kw_defaults):
            documented[arg.arg] = (inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.empty if default is None else ast.literal_eval(default))
        # The canonical signature intentionally omits only the deprecated alias.
        assert set(documented) == set(actual) - {"self", "interval"}, method
        for name, (kind, default) in documented.items():
            assert kind == actual[name].kind, (method, name, "argument kind")
            assert default == actual[name].default, (method, name, default, actual[name].default)
        assert actual["interval"].default is actual["interval_seconds"].default is None
    assert all(count == 2 for count in seen.values())


def _response(*, content=b"encoded", headers=None, status_code=200):
    return httpx.Response(status_code, content=content, headers=headers or {})


def test_encode_sends_v2_parameters_and_long_audio_timeout():
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(path, **kwargs):
        captured.update(path=path, **kwargs)
        return _response(
            headers={
                "content-type": "audio/wav",
                "x-audio-duration": "180",
                "x-token-id": "token-1",
                "x-encode-quality-warning": "true",
            }
        )

    client.audio._post = fake_post
    try:
        result = client.audio.encode(
            io.BytesIO(b"RIFF0000WAVE"),
            "token-1",
            strength=1.25,
            smooth=False,
            interval=2.5,
        )
    finally:
        client.close()

    assert captured["path"] == "/audio/watermark/encode"
    assert captured["timeout"] == 900.0
    assert captured["data"]["strength"] == "1.25"
    assert captured["data"]["smooth"] == "false"
    assert captured["data"]["interval_seconds"] == "2.5"
    assert captured["data"]["save_file"] == "false"
    assert captured["data"]["keep_original"] == "true"
    assert captured["data"]["check_watermark"] == "true"
    assert captured["data"]["verify_and_reencode"] == "true"
    assert captured["data"]["response_format"] == "stream"
    assert result.audio_bytes == b"encoded"
    assert result.audio_duration == 180.0
    assert result.quality_warning is True


def test_encode_omits_interval_by_default_and_preserves_explicit_zero():
    client = OfSpectrum(api_key="test-key")
    requests = []

    def fake_post(_path, **kwargs):
        requests.append(kwargs["data"])
        return _response(
            headers={
                "content-type": "audio/wav",
                "x-audio-duration": "2",
                "x-token-id": "token-1",
            }
        )

    client.audio._post = fake_post
    try:
        client.audio.encode(io.BytesIO(b"audio"), "token-1")
        client.audio.encode(io.BytesIO(b"audio"), "token-1", interval=0.0)
    finally:
        client.close()

    assert "interval_seconds" not in requests[0]
    assert requests[1]["interval_seconds"] == "0.0"


def test_encode_uses_interval_seconds_and_rejects_conflicting_aliases():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: pytest.fail("conflicting aliases must not send")
    try:
        with pytest.raises(ValueError, match="must match"):
            client.audio.encode(
                io.BytesIO(b"audio"), "token-1", interval=0.0, interval_seconds=1.0
            )
    finally:
        client.close()


def test_encode_forwards_persistence_flags_and_response_format():
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return _response(
            headers={
                "content-type": "audio/wav",
                "x-audio-duration": "2",
                "x-token-id": "token-1",
            }
        )

    client.audio._post = fake_post
    try:
        client.audio.encode(
            io.BytesIO(b"audio"),
            "token-1",
            save_file=False,
            keep_original=False,
            check_watermark=False,
            original_filename="source.mp3",
        )
    finally:
        client.close()

    assert captured["save_file"] == "false"
    assert captured["keep_original"] == "false"
    assert captured["check_watermark"] == "false"
    assert captured["response_format"] == "stream"
    assert captured["original_filename"] == "source.mp3"


@pytest.mark.parametrize("save_file", [False, True])
@pytest.mark.parametrize("use_output_path", [False, True])
@pytest.mark.parametrize("format_options", [{}, {"response_format": None}, {"response_format": "stream"}])
def test_encode_binary_default_is_independent_of_storage_and_local_path(
    tmp_path, save_file, use_output_path, format_options,
):
    client = OfSpectrum(api_key="test-key")
    captured = {}
    output_path = tmp_path / "encoded.wav" if use_output_path else None

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return _response(headers={"content-type": "audio/wav", "x-audio-duration": "2"})

    client.audio._post = fake_post
    try:
        result = client.audio.encode(
            io.BytesIO(b"audio"), "token-1", save_file=save_file,
            output_path=output_path, **format_options,
        )
    finally:
        client.close()

    assert captured["save_file"] == str(save_file).lower()
    assert captured["keep_original"] == "true"
    assert captured["response_format"] == "stream"
    assert result.audio_bytes == b"encoded"
    assert result.download_url is None
    if output_path:
        assert output_path.read_bytes() == b"encoded"


def test_encode_output_path_alone_does_not_enable_storage(tmp_path):
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return _response(headers={"content-type": "audio/wav", "x-audio-duration": "2"})

    client.audio._post = fake_post
    output_path = tmp_path / "local.wav"
    try:
        client.audio.encode(io.BytesIO(b"audio"), output_path=output_path)
    finally:
        client.close()

    assert captured["save_file"] == "false"
    assert captured["keep_original"] == "true"
    assert captured["response_format"] == "stream"
    assert output_path.read_bytes() == b"encoded"


@pytest.mark.parametrize("use_output_path", [False, True])
def test_encode_explicit_json_without_persistence_uses_temporary_download(
    monkeypatch, tmp_path, use_output_path,
):
    client = OfSpectrum(api_key="test-key")
    captured = {}
    downloads = []
    url = "https://example.test/temporary.wav"
    output_path = tmp_path / "downloaded.wav" if use_output_path else None

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return httpx.Response(200, json={"status": "success", "data": {
            "download_url": url, "expires_in": 3600, "audio_duration": 2,
        }})

    def fake_get(_self, download_url):
        downloads.append(download_url)
        return httpx.Response(200, content=b"downloaded", request=httpx.Request("GET", download_url))

    client.audio._post = fake_post
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    try:
        result = client.audio.encode(
            io.BytesIO(b"audio"), "token-1", save_file=False,
            response_format="json", output_path=output_path,
        )
    finally:
        client.close()

    assert captured["save_file"] == "false"
    assert captured["keep_original"] == "true"
    assert captured["response_format"] == "json"
    assert result.download_url == url
    assert result.expires_in == 3600
    assert downloads == ([url] if use_output_path else [])
    if output_path:
        assert output_path.read_bytes() == b"downloaded"


@pytest.mark.parametrize("response_format", ["invalid", "", "binary"])
def test_encode_rejects_invalid_response_format_before_network(response_format):
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: pytest.fail("invalid formats must not send")
    try:
        with pytest.raises(ValueError, match="response_format"):
            client.audio.encode(io.BytesIO(b"audio"), response_format=response_format)
    finally:
        client.close()


def test_encode_persisted_output_can_omit_original():
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return _response(headers={"content-type": "audio/wav", "x-audio-duration": "2"})

    client.audio._post = fake_post
    try:
        client.audio.encode(io.BytesIO(b"audio"), save_file=True, keep_original=False)
    finally:
        client.close()

    assert captured["save_file"] == "true"
    assert captured["keep_original"] == "false"
    assert captured["response_format"] == "stream"


def test_decode_keeps_existing_storage_default():
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return httpx.Response(200, json={"status": "success", "data": {"watermarked": 0}})

    client.audio._post = fake_post
    try:
        client.audio.decode(io.BytesIO(b"audio"))
    finally:
        client.close()

    assert captured["save_file"] == "true"


def test_decode_forwards_save_file():
    client = OfSpectrum(api_key="test-key")
    captured = {}

    def fake_post(_path, **kwargs):
        captured.update(kwargs["data"])
        return httpx.Response(200, json={"status": "success", "data": {"watermarked": 0}})

    client.audio._post = fake_post
    try:
        client.audio.decode(io.BytesIO(b"audio"), save_file=False)
    finally:
        client.close()

    assert captured["save_file"] == "false"


def test_decode_preserves_primary_fields_and_authorized_results_only():
    parsed = DecodeMatch.from_dict(
        {
            "watermarked": 1,
            "token_id": "token-primary",
            "access": "owner",
            "token_type": "pro",
            "ai_auth_enabled": True,
            "ai_auth_access_type": "premium_track",
            "model": "must-not-leak",
        }
    )
    assert parsed.token_id == "token-primary"
    assert parsed.ai_auth == {
        "ai_auth_enabled": True,
        "ai_auth_access_type": "premium_track",
    }
    assert not hasattr(parsed, "model")

    result = DecodeResult.from_dict(
        {
            "watermarked": 1,
            "token_id": "token-primary",
            "access": "owner",
            "results": [
                {"watermarked": 1, "token_id": "token-primary", "access": "owner"},
                {"watermarked": 1, "token_id": "token-authorized", "access": "public"},
            ],
        }
    )

    assert result.token_id == "token-primary"
    assert [(item.token_id, item.access) for item in result.results] == [
        ("token-primary", "owner"),
        ("token-authorized", "public"),
    ]


def test_decode_preserves_authorized_results_when_primary_is_not_watermarked():
    result = DecodeResult.from_dict(
        {
            "watermarked": 0,
            "token_id": None,
            "results": [
                {
                    "watermarked": 1,
                    "token_id": "token-authorized",
                    "access": "public",
                    "ai_auth_enabled": True,
                    "ai_auth_access_type": "direct_use",
                    "ai_auth_price": 5,
                    "ai_auth_other_instructions": "Attribution required",
                    "ai_auth_tags": ["voice"],
                    "decoded_bits": "must-not-leak",
                    "model": "must-not-leak",
                }
            ],
        }
    )

    assert result.watermarked is False
    assert result.results[0].token_id == "token-authorized"
    assert result.results[0].ai_auth == {
        "ai_auth_enabled": True,
        "ai_auth_access_type": "direct_use",
        "ai_auth_price": 5,
        "ai_auth_other_instructions": "Attribution required",
        "ai_auth_tags": ["voice"],
    }
    assert not hasattr(result.results[0], "decoded_bits")
    assert not hasattr(result.results[0], "model")


@pytest.mark.parametrize("interval", [-1.0, float("nan"), float("inf"), True])
def test_encode_rejects_invalid_interval_before_network(interval):
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(ValueError, match="interval"):
            client.audio.encode(io.BytesIO(b"audio"), "token-1", interval=interval)
    finally:
        client.close()


def test_encode_rejects_empty_stream_response():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: _response(
        content=b"",
        headers={
            "content-type": "audio/wav",
            "x-audio-duration": "10",
            "x-token-id": "token-1",
        },
    )
    try:
        with pytest.raises(OfSpectrumError, match="empty audio"):
            client.audio.encode(io.BytesIO(b"audio"), "token-1")
    finally:
        client.close()


def test_encode_rejects_missing_json_result():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: httpx.Response(
        200,
        json={"status": "success"},
        headers={"content-type": "application/json"},
    )
    try:
        with pytest.raises(OfSpectrumError, match="invalid JSON"):
            client.audio.encode(
                io.BytesIO(b"audio"),
                "token-1",
                output_path="unused.wav",
            )
    finally:
        client.close()


def test_encode_rejects_mismatched_response_token():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: _response(
        headers={
            "content-type": "audio/wav",
            "x-audio-duration": "10",
            "x-token-id": "another-token",
        },
    )
    try:
        with pytest.raises(OfSpectrumError, match="did not match"):
            client.audio.encode(io.BytesIO(b"audio"), "token-1")
    finally:
        client.close()


class _FakeWebSocket:
    def __init__(self, final_messages):
        self.final_messages = list(final_messages)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def send(self, value):
        self.sent.append(value)

    def recv(self, timeout=None):
        if self.final_messages:
            message = self.final_messages.pop(0)
            if isinstance(message, BaseException):
                raise message
            return message
        if timeout is not None and timeout < 0.05:
            raise TimeoutError
        raise RuntimeError("connection closed")


@pytest.mark.parametrize("strength", [0.0, 2.1, float("nan"), float("inf"), True])
def test_stream_encode_rejects_invalid_strength_before_connect(monkeypatch, strength):
    monkeypatch.setattr(
        websockets.sync.client,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("websocket must not be opened"),
    )
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(ValueError, match="strength"):
            client.audio.stream_encode_pcm([b"pcm!"], "token-1", strength=strength)
    finally:
        client.close()


def test_stream_encode_requires_done_event(monkeypatch):
    fake = _FakeWebSocket([b"partial"])
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(OfSpectrumError, match="closed before completion"):
            client.audio.stream_encode_pcm([b"pcm!"], "token-1")
    finally:
        client.close()


def test_stream_encode_returns_only_after_done(monkeypatch):
    fake = _FakeWebSocket(
        [
            b"encoded",
            '{"type":"quality_warning","code":"encode_quality_warning"}',
            '{"type":"done","quality_warning":true}',
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        result = client.audio.stream_encode_pcm([b"pcm!"], "token-1", strength=1.25)
    finally:
        client.close()

    config = json.loads(fake.sent[0])
    assert config["config"]["verify_and_reencode"] is False
    assert result.encoded_pcm == b"encoded"
    assert result.events[-1]["type"] == "done"
    assert result.quality_warning is True
    assert result.token_id == "token-1"


def test_encode_preserves_fractional_audio_duration():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: _response(
        headers={
            "content-type": "audio/wav",
            "x-audio-duration": "0.5",
            "x-token-id": "token-1",
        },
    )
    try:
        result = client.audio.encode(io.BytesIO(b"audio"), "token-1")
    finally:
        client.close()

    assert result.audio_duration == 0.5


def test_encode_json_response_preserves_fractional_audio_duration():
    client = OfSpectrum(api_key="test-key")
    client.audio._post = lambda *_args, **_kwargs: httpx.Response(
        200,
        json={
            "status": "success",
            "data": {"download_url": "https://example.test/output.wav", "audio_duration": "0.5"},
        },
        headers={"content-type": "application/json"},
    )
    try:
        result = client.audio.encode(
            io.BytesIO(b"audio"),
            "token-1",
            output_path=None,
            response_format="json",
        )
    finally:
        client.close()

    assert result.audio_duration == 0.5


def test_stream_encode_accepts_a_single_pcm_frame_and_sends_end(monkeypatch):
    fake = _FakeWebSocket([TimeoutError(), b"\x00\x00\x00\x00", '{"type":"done"}'])
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        result = client.audio.stream_encode_pcm([b"\x00\x00\x00\x00"], "token-1")
    finally:
        client.close()

    assert result.encoded_pcm == b"\x00\x00\x00\x00"
    assert json.loads(fake.sent[-1]) == {"type": "end"}


@pytest.mark.parametrize("chunks", [[], [b""], [b"\x00"]])
def test_stream_encode_rejects_empty_or_partial_pcm_frames(monkeypatch, chunks):
    fake = _FakeWebSocket([])
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises((OfSpectrumError, ValueError), match="empty|whole float32 frames"):
            client.audio.stream_encode_pcm(chunks, "token-1")
    finally:
        client.close()


def test_stream_encode_omitted_token_uses_done_event_token_id(monkeypatch):
    fake = _FakeWebSocket(
        [
            b"encoded",
            '{"type":"done","token_id":"default-token"}',
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        result = client.audio.stream_encode_pcm([b"pcm!"])
    finally:
        client.close()

    config = json.loads(fake.sent[0])
    assert "token_id" not in config["config"]
    assert result.token_id == "default-token"


def test_stream_encode_disables_keepalive_heartbeat_timeout(monkeypatch):
    fake = _FakeWebSocket([b"encoded", '{"type":"done"}'])
    observed = {}

    def connect(_url, **kwargs):
        observed.update(kwargs)
        return fake

    monkeypatch.setattr(websockets.sync.client, "connect", connect)
    client = OfSpectrum(api_key="test-key")
    try:
        client.audio.stream_encode_pcm([b"pcm!"], "token-1")
    finally:
        client.close()

    assert observed["ping_timeout"] is None


def test_stream_encode_timeout_interrupts_blocked_upload(monkeypatch):
    class BlockingWebSocket:
        def __init__(self):
            self.closed = threading.Event()
            self.upload_started = threading.Event()
            self.upload_interrupted = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def send(self, value):
            if isinstance(value, bytes):
                self.upload_started.set()
                assert self.closed.wait(timeout=5.0), "watchdog did not interrupt upload"
                self.upload_interrupted.set()

        def recv(self, timeout=None):
            if not self.closed.wait(timeout=timeout):
                raise TimeoutError
            raise RuntimeError("closed")

        def close(self):
            self.closed.set()

    fake = BlockingWebSocket()
    caller_thread = threading.current_thread()

    def logical_time():
        if threading.current_thread() is not caller_thread:
            assert fake.upload_started.wait(timeout=5.0), "upload did not start"
        return 1.0 if fake.closed.is_set() else 0.0

    # Keep the real watchdog and blocking send, but separate deadline ordering
    # from OS timer granularity and CPU scheduling. A zero-latency fake close
    # must not turn an early timer wakeup into a simulated peer disconnect.
    monkeypatch.setattr(
        "ofspectrum.resources.audio.time", SimpleNamespace(monotonic=logical_time),
    )
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(OfSpectrumError, match="timed out"):
            client.audio.stream_encode_pcm([b"pcm!"], "token-1", timeout=0.05)
    finally:
        client.close()

    assert fake.upload_started.is_set()
    assert fake.upload_interrupted.is_set()
    assert fake.closed.is_set()


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf"), True])
def test_stream_encode_rejects_invalid_timeout_before_connect(monkeypatch, timeout):
    monkeypatch.setattr(
        websockets.sync.client,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("connect must not be called"),
    )
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(ValueError, match="timeout"):
            client.audio.stream_encode_pcm([b"pcm!"], "token-1", timeout=timeout)
    finally:
        client.close()
