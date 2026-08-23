import json
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import pytest
import websockets.sync.client

from ofspectrum import OfSpectrum, StreamEncodePool
from ofspectrum.exceptions import OfSpectrumError
from ofspectrum.media import AudioMediaInfo


class _PoolSocket:
    def __init__(
        self,
        responses,
        *,
        flush_barrier=None,
        admission='{"type":"admitted"}',
        ping_ok=True,
        require_receive_during_upload=False,
    ):
        self._responses = deque([admission])
        self._flush_responses = deque(responses)
        self._flush_barrier = flush_barrier
        self._ping_ok = ping_ok
        self._require_receive_during_upload = require_receive_during_upload
        self._early_output_received = threading.Event()
        self._early_output_queued = False
        self._condition = threading.Condition()
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)
        if isinstance(value, bytes) and self._require_receive_during_upload:
            if not self._early_output_queued:
                self._early_output_queued = True
                self._queue_response(b"early-output")
            return
        if isinstance(value, str):
            event_type = json.loads(value).get("type")
            if event_type == "config":
                self._queue_response('{"type":"ready"}')
            elif event_type == "flush":
                if self._flush_barrier is not None:
                    self._flush_barrier.wait(timeout=2.0)
                with self._condition:
                    self._responses.extend(self._flush_responses.popleft())
                    self._condition.notify_all()
            elif event_type == "heartbeat":
                self._queue_response('{"type":"heartbeat_ack"}')
            elif event_type == "close":
                self._queue_response('{"type":"closed"}')

    def recv(self, timeout=None):
        with self._condition:
            if not self._condition.wait_for(
                lambda: bool(self._responses) or self.closed,
                timeout=timeout,
            ):
                raise TimeoutError("receive timed out")
            if not self._responses:
                raise RuntimeError("connection closed")
            response = self._responses.popleft()
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(self)
        if response == b"early-output":
            self._early_output_received.set()
        return response

    def close(self):
        with self._condition:
            self.closed = True
            self._condition.notify_all()

    def ping(self):
        waiter = threading.Event()
        if self._ping_ok:
            waiter.set()
        return waiter

    def _queue_response(self, response):
        with self._condition:
            self._responses.append(response)
            self._condition.notify_all()


class _PoolFactory:
    def __init__(self, scenarios):
        self._scenarios = deque(scenarios)
        self.connections = []
        self.headers = []
        self.kwargs = []

    def __call__(self, _url, **kwargs):
        self.kwargs.append(kwargs)
        self.headers.append(kwargs.get("additional_headers") or kwargs.get("extra_headers"))
        socket = _PoolSocket(**self._scenarios.popleft())
        self.connections.append(socket)
        return socket


class _BlockingPoolSocket:
    def __init__(self):
        self.sent = []
        self.flush_started = threading.Event()
        self.closed = threading.Event()

    def send(self, value):
        self.sent.append(value)
        if isinstance(value, str) and json.loads(value).get("type") == "flush":
            self.flush_started.set()

    def recv(self, timeout=None):
        if not self.closed.wait(timeout=timeout):
            raise TimeoutError("receive timed out")
        raise RuntimeError("connection closed")

    def close(self):
        self.closed.set()


class _DelayedConnectFactory:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.socket = _PoolSocket(**_success_scenario())

    def __call__(self, _url, **_kwargs):
        self.started.set()
        self.release.wait(timeout=5.0)
        return self.socket


def _flush_done(socket):
    operation_id = json.loads(socket.sent[-1])["operation_id"]
    return json.dumps({"type": "flush_done", "operation_id": operation_id})


def _flush_done_reconnect(socket):
    operation_id = json.loads(socket.sent[-1])["operation_id"]
    return json.dumps(
        {
            "type": "flush_done",
            "operation_id": operation_id,
            "reconnect_required": True,
        }
    )


def _success_scenario(
    encoded=b"encoded",
    *,
    flush_barrier=None,
    operations=1,
    ping_ok=True,
    require_receive_during_upload=False,
):
    return {
        "responses": [[encoded, _flush_done] for _ in range(operations)],
        "flush_barrier": flush_barrier,
        "ping_ok": ping_ok,
        "require_receive_during_upload": require_receive_during_upload,
    }


def test_stream_encode_reuses_auto_pool_connections(monkeypatch):
    factory = _PoolFactory([_success_scenario(operations=3)])
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    monkeypatch.setattr(
        "ofspectrum.resources.audio.rebuild_encoded_media",
        lambda pcm, _info: b"RIFF" + pcm[:12],
    )
    client = OfSpectrum(api_key="test-key")
    wav = b"RIFF" + b"\x00" * 12
    try:

        def fake_decode(_source):
            from ofspectrum.media import AudioMediaInfo

            return b"\x00\x00\x00\x00", AudioMediaInfo(
                format_name="wav",
                codec_name="pcm_s16le",
                sample_rate=48000,
                channels=1,
                duration_seconds=2.7,
                extension="wav",
                content_type="audio/wav",
            )

        monkeypatch.setattr(
            "ofspectrum.resources.audio.decode_canonical_interleaved_pcm",
            fake_decode,
        )
        monkeypatch.setattr(
            "ofspectrum.resources.audio.read_audio_bytes",
            lambda audio: audio if isinstance(audio, bytes) else b"x",
        )
        first = client.audio.stream_encode(
            wav,
            "token-1",
            save_file=False,
            keep_original=False,
            check_watermark=False,
            response_format="stream",
        )
        second = client.audio.stream_encode(
            wav,
            "token-1",
            save_file=False,
            keep_original=False,
            check_watermark=False,
            response_format="stream",
        )
        assert first.audio_bytes.startswith(b"RIFF")
        assert second.audio_bytes.startswith(b"RIFF")
        assert len(factory.connections) == 1
        pcm_frames = sum(
            isinstance(message, bytes) for message in factory.connections[0].sent
        )
        assert pcm_frames == 2
    finally:
        client.close()


def test_stream_pool_skips_recent_health_probe(monkeypatch):
    factory = _PoolFactory([_success_scenario(operations=2, ping_ok=False)])
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        pool._encode_pcm(b"pcm!", timeout=2.0)
        pool._encode_pcm(b"pcm!", timeout=2.0)
        assert len(factory.connections) == 1
    finally:
        client.close()


def test_stream_pool_reuses_connections_and_stable_uuid_slots(monkeypatch):
    factory = _PoolFactory(
        [_success_scenario(operations=3), _success_scenario(operations=3)]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=2)
    barrier = threading.Barrier(2)

    def encode_once():
        barrier.wait(timeout=2.0)
        return pool._encode_pcm(b"pcm!", timeout=2.0)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: encode_once(), range(2)))
        assert [result.encoded_pcm for result in results] == [b"encoded", b"encoded"]

        assert len(factory.connections) == 2
        assert all(
            0 < kwargs["open_timeout"] <= StreamEncodePool._CONNECT_TIMEOUT_SECONDS
            for kwargs in factory.kwargs
        )
        slots = [headers["X-OfSpectrum-Stream-Slot"] for headers in factory.headers]
        assert len(set(slots)) == 2
        assert all(str(uuid.UUID(slot)) == slot for slot in slots)

        pool._encode_pcm(b"pcm!", timeout=2.0)
        pool._encode_pcm(b"pcm!", timeout=2.0)
        assert len(factory.connections) == 2
        assert sum(
            sum(isinstance(message, bytes) for message in socket.sent)
            for socket in factory.connections
        ) == 4
    finally:
        client.close()

    assert all(
        json.loads(socket.sent[-1]) == {"type": "close"}
        for socket in factory.connections
    )


def test_stream_pool_serializes_each_slot_but_uses_two_slots(monkeypatch):
    flush_barrier = threading.Barrier(2)
    factory = _PoolFactory(
        [
            _success_scenario(b"left", flush_barrier=flush_barrier),
            _success_scenario(b"right", flush_barrier=flush_barrier),
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=2)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: pool._encode_pcm(b"pcm!", timeout=2.0), range(2)))
        assert {result.encoded_pcm for result in results} == {b"left", b"right"}
        assert len(factory.connections) == 2
        assert all(
            sum(isinstance(message, bytes) for message in socket.sent) == 1
            for socket in factory.connections
        )
    finally:
        client.close()


def test_stream_pool_reconnects_stale_socket_before_sending_next_operation(monkeypatch):
    factory = _PoolFactory(
        [
            _success_scenario(b"first", ping_ok=False),
            _success_scenario(b"recovered"),
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        first = pool._encode_pcm(b"pcm!", timeout=2.0)
        pool._slots[0].last_ok_monotonic = 0.0
        result = pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert first.encoded_pcm == b"first"
    assert result.encoded_pcm == b"recovered"
    assert len(factory.connections) == 2
    assert [
        sum(isinstance(message, bytes) for message in socket.sent)
        for socket in factory.connections
    ] == [1, 1]
    assert factory.connections[0].closed is True


def test_stream_pool_heartbeat_keeps_every_slot_alive(monkeypatch):
    factory = _PoolFactory([_success_scenario(), _success_scenario()])
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=2)
    try:
        assert pool.heartbeat(timeout=2.0) is True
        assert len(factory.connections) == 2
        for socket in factory.connections:
            types = [
                json.loads(message).get("type")
                for message in socket.sent
                if isinstance(message, str)
            ]
            assert "heartbeat" in types
            assert "config" in types
    finally:
        client.close()


def test_stream_pool_heartbeat_reconnects_dead_socket_without_raising(monkeypatch):
    factory = _PoolFactory([_success_scenario(), _success_scenario()])
    original = factory.__call__

    def connect_with_dead_first(_url, **kwargs):
        socket = original(_url, **kwargs)
        if len(factory.connections) == 1:
            inner_send = socket.send

            def send(value):
                if isinstance(value, str) and json.loads(value).get("type") == "heartbeat":
                    raise RuntimeError("socket dead")
                return inner_send(value)

            socket.send = send
        return socket

    monkeypatch.setattr(websockets.sync.client, "connect", connect_with_dead_first)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        assert pool.heartbeat(timeout=2.0) is True
        assert len(factory.connections) == 2
        assert any(
            isinstance(message, str) and json.loads(message).get("type") == "heartbeat"
            for message in factory.connections[1].sent
        )
    finally:
        client.close()


def test_stream_pool_keepalive_thread_heartbeats_all_slots(monkeypatch):
    factory = _PoolFactory([_success_scenario(), _success_scenario()])
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool(
        "token-1",
        connections=2,
        keepalive_interval_seconds=0.05,
    )
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if len(factory.connections) == 2 and all(
                any(
                    isinstance(message, str)
                    and json.loads(message).get("type") == "heartbeat"
                    for message in socket.sent
                )
                for socket in factory.connections
            ):
                break
            time.sleep(0.02)
        assert len(factory.connections) == 2
        assert all(
            any(
                isinstance(message, str)
                and json.loads(message).get("type") == "heartbeat"
                for message in socket.sent
            )
            for socket in factory.connections
        )
    finally:
        client.close()


def test_stream_pool_does_not_replay_after_operation_input_starts(monkeypatch):
    factory = _PoolFactory(
        [{"responses": [[RuntimeError("connection closed before output")]]}]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        with pytest.raises(OfSpectrumError) as raised:
            pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert raised.value.code == "StreamingPoolUnavailable"
    assert len(factory.connections) == 1
    assert sum(
        isinstance(message, bytes) for message in factory.connections[0].sent
    ) == 1


def test_stream_pool_receives_output_while_upload_is_still_in_progress(monkeypatch):
    factory = _PoolFactory(
        [
            _success_scenario(
                b"tail-output",
                require_receive_during_upload=True,
            )
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        result = pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert result.encoded_pcm == b"early-outputtail-output"


def test_stream_pool_waits_for_a_previous_slot_lease(monkeypatch):
    factory = _PoolFactory(
        [
            {
                "responses": [],
                "admission": json.dumps(
                    {
                        "type": "error",
                        "code": "AudioStreamConnectionTakeoverPending",
                        "retry_after_ms": 1000,
                    }
                ),
            },
            _success_scenario(b"reconnected"),
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    monkeypatch.setattr("ofspectrum.resources.audio.time.sleep", lambda _seconds: None)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        result = pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert result.encoded_pcm == b"reconnected"
    assert len(factory.connections) == 2
    assert factory.connections[0].closed is True


def test_stream_pool_rotates_after_server_requests_reconnect(monkeypatch):
    factory = _PoolFactory(
        [
            {"responses": [[b"first", _flush_done_reconnect]]},
            _success_scenario(b"second"),
        ]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        first = pool._encode_pcm(b"pcm!", timeout=2.0)
        second = pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert first.encoded_pcm == b"first"
    assert second.encoded_pcm == b"second"
    assert len(factory.connections) == 2
    assert factory.connections[0].closed is True


def test_stream_pool_does_not_retry_after_partial_output(monkeypatch):
    factory = _PoolFactory(
        [{"responses": [[b"partial", RuntimeError("connection closed after output")]]}]
    )
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    try:
        with pytest.raises(OfSpectrumError) as exc:
            pool._encode_pcm(b"pcm!", timeout=2.0)
    finally:
        client.close()

    assert exc.value.code == "StreamingPoolIncomplete"
    assert "connection closed after output" not in str(exc.value)
    assert len(factory.connections) == 1
    assert factory.connections[0].closed is True


def test_stream_pool_encode_rebuilds_file_result_and_client_close(monkeypatch):
    factory = _PoolFactory([_success_scenario(b"encoded-pcm")])
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    monkeypatch.setattr("ofspectrum.resources.audio.read_audio_bytes", lambda _audio: b"source")
    info = AudioMediaInfo(
        format_name="wav",
        codec_name="pcm_s16le",
        sample_rate=48000,
        channels=1,
        duration_seconds=1.0,
        extension="wav",
        content_type="audio/wav",
    )
    monkeypatch.setattr(
        "ofspectrum.resources.audio.decode_canonical_interleaved_pcm",
        lambda _source: (b"pcm!", info),
    )
    monkeypatch.setattr(
        "ofspectrum.resources.audio.rebuild_encoded_media",
        lambda encoded, _info: b"rebuilt:" + encoded,
    )
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1")

    result = pool.encode(b"file-bytes", timeout=2.0)
    pool.close()
    client.close()

    assert result.audio_bytes == b"rebuilt:encoded-pcm"
    assert result.token_id == "token-1"
    assert result.file_name == "watermarked.wav"
    assert json.loads(factory.connections[0].sent[-1]) == {"type": "close"}
    assert factory.connections[0].closed is True
    with pytest.raises(OfSpectrumError, match="pool is closed"):
        pool._encode_pcm(b"pcm!", timeout=2.0)


def test_client_close_aborts_an_active_pool_operation_without_deadlock():
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)
    socket = _BlockingPoolSocket()
    pool._slots[0].websocket = socket

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool._encode_pcm, b"pcm!", timeout=None)
        assert socket.flush_started.wait(timeout=1.0)
        client.close()
        with pytest.raises(OfSpectrumError) as raised:
            future.result(timeout=3.0)

    assert raised.value.code == "StreamingPoolClosed"


def test_pool_close_prevents_a_late_connect_from_leaking(monkeypatch):
    factory = _DelayedConnectFactory()
    monkeypatch.setattr(websockets.sync.client, "connect", factory)
    client = OfSpectrum(api_key="test-key")
    pool = client.audio.open_stream_pool("token-1", connections=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(pool._encode_pcm, b"pcm!", timeout=None)
        assert factory.started.wait(timeout=1.0)
        pool.close()
        factory.release.set()
        with pytest.raises(OfSpectrumError) as raised:
            future.result(timeout=3.0)

    client.close()
    assert raised.value.code == "StreamingPoolClosed"
    assert factory.socket.closed is True
