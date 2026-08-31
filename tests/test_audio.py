import io
import json
import threading
import time

import httpx
import pytest
import websockets.sync.client

from ofspectrum import OfSpectrum
from ofspectrum.exceptions import OfSpectrumError


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
    assert captured["data"]["interval"] == "2.5"
    assert captured["data"]["save_file"] == "true"
    assert captured["data"]["keep_original"] == "true"
    assert captured["data"]["check_watermark"] == "true"
    assert captured["data"]["verify_and_reencode"] == "true"
    assert captured["data"]["response_format"] == "stream"
    assert result.audio_bytes == b"encoded"
    assert result.audio_duration == 180
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

    assert "interval" not in requests[0]
    assert requests[1]["interval"] == "0.0"


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
            return self.final_messages.pop(0)
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
            client.audio.stream_encode_pcm([b"pcm"], "token-1", strength=strength)
    finally:
        client.close()


def test_stream_encode_requires_done_event(monkeypatch):
    fake = _FakeWebSocket([b"partial"])
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    try:
        with pytest.raises(OfSpectrumError, match="closed before completion"):
            client.audio.stream_encode_pcm([b"pcm"], "token-1")
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
        result = client.audio.stream_encode_pcm([b"pcm"], "token-1", strength=1.25)
    finally:
        client.close()

    config = json.loads(fake.sent[0])
    assert config["config"]["verify_and_reencode"] is True
    assert result.encoded_pcm == b"encoded"
    assert result.events[-1]["type"] == "done"
    assert result.quality_warning is True
    assert result.token_id == "token-1"


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
        result = client.audio.stream_encode_pcm([b"pcm"])
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
        client.audio.stream_encode_pcm([b"pcm"], "token-1")
    finally:
        client.close()

    assert observed["ping_timeout"] is None


def test_stream_encode_timeout_interrupts_blocked_upload(monkeypatch):
    class BlockingWebSocket:
        def __init__(self):
            self.closed = threading.Event()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()
            return False

        def send(self, value):
            if isinstance(value, bytes):
                self.closed.wait()

        def recv(self, timeout=None):
            if not self.closed.wait(timeout=timeout):
                raise TimeoutError
            raise RuntimeError("closed")

        def close(self):
            self.closed.set()

    fake = BlockingWebSocket()
    monkeypatch.setattr(websockets.sync.client, "connect", lambda *_args, **_kwargs: fake)
    client = OfSpectrum(api_key="test-key")
    started = time.perf_counter()
    try:
        with pytest.raises(OfSpectrumError, match="timed out"):
            client.audio.stream_encode_pcm([b"pcm"], "token-1", timeout=0.05)
    finally:
        client.close()

    assert time.perf_counter() - started < 1.0
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
            client.audio.stream_encode_pcm([b"pcm"], "token-1", timeout=timeout)
    finally:
        client.close()
