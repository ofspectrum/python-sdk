import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from types import SimpleNamespace

import pytest

from ofspectrum import TTS, AzureSpeechTTS
from ofspectrum.elevenlabs import WatermarkController


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["file", "pool"])
async def test_async_tts_consumes_sync_audio_and_encodes_off_loop(transport):
    loop_thread = threading.get_ident()
    observations = {"invoke": [], "iterate": [], "encode": [], "closed": []}

    def chunks():
        try:
            observations["iterate"].append(threading.get_ident())
            yield b"audio"
        finally:
            observations["closed"].append(True)

    def convert(**kwargs):
        observations["invoke"].append(threading.get_ident())
        return chunks()

    def encode(source, token_id, **kwargs):
        observations["encode"].append(threading.get_ident())
        return SimpleNamespace(audio_bytes=b"marked:" + source.read())

    client = TTS(
        "elevenlabs", SimpleNamespace(text_to_speech=SimpleNamespace(convert=convert)),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode, stream_encode=encode)),
        token_id="token-1", transport=transport,
    )
    try:
        result = await client.synthesize_async("hello", voice="voice-1")
    finally:
        client.close()
    assert result.audio == b"marked:audio"
    assert observations["closed"] == [True]
    for phase in ("invoke", "iterate", "encode"):
        assert len(observations[phase]) == 1
        assert observations[phase][0] != loop_thread, phase


def test_reconfiguration_keeps_owned_encode_alive_and_uses_new_client(monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    clients = []

    class OwnedClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.closed = 0
            self.audio = SimpleNamespace(encode=self.encode)
            clients.append(self)

        def encode(self, source, token_id, **kwargs):
            raw = source.read()
            if raw == b"old":
                entered.set()
                assert resume.wait(2)
            if self.closed:
                raise RuntimeError("active client was closed")
            return SimpleNamespace(audio_bytes=raw + b":" + token_id.encode())

        def close(self):
            self.closed += 1

    monkeypatch.setattr("ofspectrum.elevenlabs.OfSpectrum", OwnedClient)
    controller = WatermarkController(api_key="old-key", token_id="old-token", transport="file")
    with ThreadPoolExecutor(max_workers=2) as executor:
        original = executor.submit(controller.encode_bytes, b"old")
        try:
            assert entered.wait(2)
            controller.config(api_key="new-key", token_id="new-token")
            assert clients[0].closed == 0
            fresh = executor.submit(controller.encode_bytes, b"new")
            assert fresh.result(2) == b"new:new-token"
            assert clients[1].api_key == "new-key"
        finally:
            resume.set()
        assert original.result(2) == b"old:old-token"
    assert clients[0].closed == 1
    controller.close()
    assert [client.closed for client in clients] == [1, 1]


def test_shared_azure_future_only_encodes_once_when_get_is_concurrent():
    entered, resume, second_started = threading.Event(), threading.Event(), threading.Event()
    counts = {"native": 0, "encode": 0}
    result = SimpleNamespace(audio_data=b"audio")

    class NativeFuture:
        def get(self):
            counts["native"] += 1
            if counts["native"] == 1:
                entered.set()
                assert resume.wait(2)
            return result

    def encode(source, token_id, **kwargs):
        counts["encode"] += 1
        return SimpleNamespace(audio_bytes=b"marked:" + source.read())

    client = AzureSpeechTTS(
        SimpleNamespace(speak_text_async=lambda text: NativeFuture()),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode)),
        token_id="token-1", transport="file",
        output_format="audio-24khz-96kbitrate-mono-mp3",
    )
    future = client.speak_text_async("hello")

    def second_get():
        second_started.set()
        return future.get()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(future.get)
        try:
            assert entered.wait(2)
            second = executor.submit(second_get)
            assert second_started.wait(2)
            with pytest.raises(FutureTimeoutError):
                second.result(0.1)
        finally:
            resume.set()
        assert first.result(2) is result
        assert second.result(2) is result
    assert future.get() is result
    assert counts == {"native": 1, "encode": 1}
    assert result.audio_data == b"marked:audio"
    client.close()


@pytest.mark.asyncio
async def test_async_tts_requests_can_complete_concurrently():
    barrier = threading.Barrier(2)
    calls = []

    def encode(source, token_id, **kwargs):
        barrier.wait(2)
        raw = source.read()
        calls.append(raw)
        return SimpleNamespace(audio_bytes=b"marked:" + raw)

    client = TTS(
        "elevenlabs", SimpleNamespace(text_to_speech=SimpleNamespace(
            convert=lambda **kwargs: iter((kwargs["text"].encode(),)),
        )),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode)),
        token_id="token-1", transport="file",
    )
    try:
        results = await asyncio.gather(*[
            client.synthesize_async(text, voice="voice-1") for text in ("one", "two")
        ])
        assert {result.audio for result in results} == {b"marked:one", b"marked:two"}
        assert sorted(calls) == [b"one", b"two"]
    finally:
        client.close()


@pytest.mark.asyncio
async def test_async_tts_sync_iterator_failure_closes_without_encoding():
    closed, encoded = [], []

    def chunks():
        try:
            yield b"partial"
            raise ValueError("provider failed")
        finally:
            closed.append(True)

    client = TTS(
        "elevenlabs", SimpleNamespace(text_to_speech=SimpleNamespace(convert=lambda **kwargs: chunks())),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(
            encode=lambda *args, **kwargs: encoded.append(True),
        )), token_id="token-1", transport="file",
    )
    try:
        with pytest.raises(ValueError, match="provider failed"):
            await client.synthesize_async("hello", voice="voice-1")
        assert closed == [True]
        assert encoded == []
    finally:
        client.close()


@pytest.mark.asyncio
async def test_async_tts_cancelled_wait_does_not_retry_background_encode():
    entered, resume, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def encode(source, token_id, **kwargs):
        calls.append(source.read())
        entered.set()
        try:
            assert resume.wait(2)
            return SimpleNamespace(audio_bytes=b"marked:audio")
        finally:
            finished.set()

    client = TTS(
        "elevenlabs", SimpleNamespace(text_to_speech=SimpleNamespace(convert=lambda **kwargs: iter((b"audio",)))),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode)),
        token_id="token-1", transport="file",
    )
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(client.synthesize_async("hello", voice="voice-1"))
    try:
        assert await loop.run_in_executor(None, entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        resume.set()
        assert await loop.run_in_executor(None, finished.wait, 2)
        client.close()
    assert calls == [b"audio"]


def test_retired_client_waits_for_all_users_and_cleanup_does_not_hold_config_lock(monkeypatch):
    both_entered = threading.Event()
    resumes = {b"one": threading.Event(), b"two": threading.Event()}
    clients, entered = [], []
    entered_lock = threading.Lock()
    controller = None

    class Client:
        def __init__(self, api_key):
            self.closed = 0
            self.audio = SimpleNamespace(encode=self.encode)
            clients.append(self)

        def encode(self, source, token_id, **kwargs):
            raw = source.read()
            with entered_lock:
                entered.append(raw)
                if len(entered) == 2:
                    both_entered.set()
            assert resumes[raw].wait(2)
            assert not self.closed
            return SimpleNamespace(audio_bytes=b"marked:" + raw)

        def close(self):
            # A config reader on a different thread must not deadlock cleanup.
            with ThreadPoolExecutor(max_workers=1) as reader:
                assert reader.submit(lambda: controller.token_id).result(1) == "token-1"
            self.closed += 1

    monkeypatch.setattr("ofspectrum.elevenlabs.OfSpectrum", Client)
    controller = WatermarkController(api_key="old", token_id="token-1", transport="file")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(controller.encode_bytes, b"one")
        second = executor.submit(controller.encode_bytes, b"two")
        try:
            assert both_entered.wait(2)
            controller.config(api_key="new")
            assert clients[0].closed == 0
            resumes[b"one"].set()
            assert first.result(2) == b"marked:one"
            assert clients[0].closed == 0
        finally:
            resumes[b"one"].set()
            resumes[b"two"].set()
        assert second.result(2) == b"marked:two"
    assert clients[0].closed == 1
    assert controller._client_users == {}
    assert controller._retired_clients == {}
    controller.close()
    assert clients[0].closed == 1


@pytest.mark.parametrize("encode_fails", [False, True])
def test_retired_cleanup_failure_does_not_mask_encode_outcome(monkeypatch, caplog, encode_fails):
    entered, resume = threading.Event(), threading.Event()
    clients = []

    class Client:
        def __init__(self, api_key):
            self.closed = 0
            self.audio = SimpleNamespace(encode=self.encode)
            clients.append(self)

        def encode(self, source, token_id, **kwargs):
            entered.set()
            assert resume.wait(2)
            if encode_fails:
                raise ValueError("encode failed")
            return SimpleNamespace(audio_bytes=b"marked:audio")

        def close(self):
            self.closed += 1
            raise RuntimeError("private-upstream-placeholder")

    monkeypatch.setattr("ofspectrum.elevenlabs.OfSpectrum", Client)
    controller = WatermarkController(api_key="old", token_id="token-1", transport="file")
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(controller.encode_bytes, b"audio")
        try:
            assert entered.wait(2)
            controller.config(api_key="new")
        finally:
            resume.set()
        if encode_fails:
            with pytest.raises(ValueError, match="encode failed"):
                result.result(2)
        else:
            assert result.result(2) == b"marked:audio"
    assert clients[0].closed == 1
    assert controller._client_users == {}
    assert controller._retired_clients == {}
    assert "error_type=RuntimeError" in caplog.text
    assert "private-upstream-placeholder" not in caplog.text


def test_client_replacement_preserves_injected_ownership(monkeypatch):
    clients = []

    class Client:
        def __init__(self, api_key):
            self.closed = 0
            self.audio = SimpleNamespace(encode=lambda source, token_id, **kwargs:
                                         SimpleNamespace(audio_bytes=b"marked:" + source.read()))
            clients.append(self)

        def close(self):
            self.closed += 1

    monkeypatch.setattr("ofspectrum.elevenlabs.OfSpectrum", Client)
    controller = WatermarkController(api_key="key", token_id="token-1", transport="file")
    assert controller.encode_bytes(b"first") == b"marked:first"
    owned = clients[0]
    injected = Client("external")
    controller.config(client=injected)
    assert owned.closed == 1
    assert controller.encode_bytes(b"second") == b"marked:second"
    controller.close()
    controller.close()
    assert injected.closed == 0
    assert owned.closed == 1


def test_explicit_close_still_aborts_current_and_retired_owned_clients(monkeypatch):
    entered, resume = threading.Event(), threading.Event()
    clients = []

    class Client:
        def __init__(self, api_key):
            self.closed = 0
            self.audio = SimpleNamespace(encode=self.encode)
            clients.append(self)

        def encode(self, source, token_id, **kwargs):
            if source.read() == b"blocked":
                entered.set()
                assert resume.wait(2)
            if self.closed:
                raise RuntimeError("explicitly closed")
            return SimpleNamespace(audio_bytes=b"marked:audio")

        def close(self):
            self.closed += 1

    monkeypatch.setattr("ofspectrum.elevenlabs.OfSpectrum", Client)
    controller = WatermarkController(api_key="old", token_id="token-1", transport="file")
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(controller.encode_bytes, b"blocked")
        try:
            assert entered.wait(2)
            controller.config(api_key="new")
            assert controller.encode_bytes(b"new") == b"marked:audio"
            controller.close()
            assert [client.closed for client in clients] == [1, 1]
        finally:
            resume.set()
        with pytest.raises(RuntimeError, match="explicitly closed"):
            result.result(2)
    controller.close()
    assert [client.closed for client in clients] == [1, 1]
    assert controller._client_users == {}


@pytest.mark.parametrize("failure_stage", ["native", "encode"])
def test_shared_azure_future_caches_failure_without_retry(failure_stage):
    counts = {"native": 0, "encode": 0}
    failure = RuntimeError("terminal failure")

    class NativeFuture:
        def get(self):
            counts["native"] += 1
            if failure_stage == "native":
                raise failure
            return SimpleNamespace(audio_data=b"audio")

    def encode(*args, **kwargs):
        counts["encode"] += 1
        raise failure

    client = AzureSpeechTTS(
        SimpleNamespace(speak_text_async=lambda text: NativeFuture()),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode)),
        token_id="token-1", transport="file",
        output_format="audio-24khz-96kbitrate-mono-mp3",
    )
    future = client.speak_text_async("hello")
    for _ in range(3):
        with pytest.raises(RuntimeError) as exc:
            future.get()
        assert exc.value is failure
    assert counts == {"native": 1, "encode": int(failure_stage == "encode")}
    client.close()


def test_distinct_azure_futures_remain_concurrent():
    barrier = threading.Barrier(2)
    calls = []

    def encode(source, token_id, **kwargs):
        raw = source.read()
        barrier.wait(2)
        calls.append(raw)
        return SimpleNamespace(audio_bytes=b"marked:" + raw)

    def speak(text):
        return SimpleNamespace(get=lambda: SimpleNamespace(audio_data=text.encode()))

    client = AzureSpeechTTS(
        SimpleNamespace(speak_text_async=speak),
        watermark_client=SimpleNamespace(audio=SimpleNamespace(encode=encode)),
        token_id="token-1", transport="file",
        output_format="audio-24khz-96kbitrate-mono-mp3",
    )
    futures = [client.speak_text_async(text) for text in ("one", "two")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda future: future.get(), futures))
    assert {result.audio_data for result in results} == {b"marked:one", b"marked:two"}
    assert sorted(calls) == [b"one", b"two"]
    client.close()
