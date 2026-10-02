import argparse
import base64
import io
import sys
import wave
from types import SimpleNamespace

from benchmarks import tts_latency


def test_openai_chat_benchmark_uses_audio_completion_endpoint(monkeypatch):
    seen = []
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(audio=SimpleNamespace(
            data=base64.b64encode(b"provider-audio").decode("ascii")
        ))
    )])

    class Completions:
        def create(self, **kwargs):
            seen.append(kwargs)
            return response

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "openai-key"
            self.chat = SimpleNamespace(completions=Completions())

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(
        tts_latency,
        "_required",
        lambda name: {
            "OFSPECTRUM_API_KEY": "watermark-key",
            "OFSPECTRUM_TOKEN_ID": "token-1",
            "OPENAI_API_KEY": "openai-key",
        }[name],
    )
    args = argparse.Namespace(
        provider="openai", openai_endpoint="chat", model=None, voice=None,
        text="Hello",
    )

    wrapped, call, extract, _, endpoint, request = tts_latency._build(args)
    result = call(wrapped.wrapped_client)
    wrapped.close()

    assert endpoint == "chat.completions.create"
    assert request == {"model": "gpt-audio-1.5", "voice": "alloy", "output_format": "mp3"}
    assert extract(result) == b"provider-audio"
    assert seen == [{
        "model": "gpt-audio-1.5",
        "messages": [{"role": "user", "content": "Hello"}],
        "modalities": ["text", "audio"],
        "audio": {"voice": "alloy", "format": "mp3"},
    }]


def test_benchmark_pairs_encode_with_the_same_native_audio(monkeypatch):
    native = object()
    calls = []
    encodes = []
    wrapper = SimpleNamespace(wrapped_client=native, close=lambda: calls.append("close"))

    def call(client):
        calls.append("native" if client is native else "wrapped")
        return b"native-audio" if client is native else b"wrapped-audio"

    def encode(audio):
        encodes.append(audio)
        return b"encoded"

    monkeypatch.setattr(
        tts_latency, "_build",
        lambda args: (wrapper, call, lambda result: result, encode, "speech.create",
                      {"model": "test-model", "voice": "test-voice"}),
    )
    ticks = iter(index * 0.1 for index in range(100))
    monkeypatch.setattr(tts_latency.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args: None))
    args = argparse.Namespace(provider="openai", iterations=3, warmups=1)

    report = tts_latency.run(args)

    assert calls.count("native") == calls.count("wrapped") == 4
    assert calls[-1] == "close"
    assert encodes == [b"native-audio"] * 4
    assert report["request"]["model"] == "test-model"
    assert report["native_tts"]["average_ms"] == 100.0
    assert report["watermark_encode_only"]["average_ms"] == 100.0
    assert report["paired_native_plus_encode"]["average_ms"] == 200.0


def test_duration_tiers_use_three_paired_native_runs_per_tier(monkeypatch):
    native = object()
    seen_texts = []
    encoded_inputs = []
    closed = []
    wrapper = SimpleNamespace(wrapped_client=native, close=lambda: closed.append(True))
    args = argparse.Namespace(
        provider="gemini", text="original", duration_tiers=True,
        iterations=None, warmups=None,
    )

    def call(client):
        assert client is native
        seen_texts.append(args.text)
        return args.text.encode()

    def encode(audio):
        encoded_inputs.append(audio)
        return b"encoded"

    monkeypatch.setattr(
        tts_latency, "_build",
        lambda args: (wrapper, call, lambda result: result, encode, "models.generate_content",
                      {"model": "test-model"}),
    )
    monkeypatch.setattr(tts_latency, "_duration_seconds", lambda provider, audio: 10.0)
    ticks = iter(index * 0.1 for index in range(100))
    monkeypatch.setattr(tts_latency.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args: None))

    report = tts_latency.run(args)

    assert [tier["target_seconds"] for tier in report["tiers"]] == [5, 10, 30]
    assert seen_texts == [text for text in tts_latency.TIER_TEXTS.values() for _ in range(3)]
    assert encoded_inputs == [text.encode() for text in seen_texts]
    assert args.text == "original"
    assert closed == [True]
    assert report["iterations_per_tier"] == 3
    for tier in report["tiers"]:
        assert len(tier["runs"]) == 3
        assert tier["encode_disabled"]["average_ms"] == 100.0
        assert tier["added_by_encode"]["average_ms"] == 100.0
        assert tier["encode_enabled"]["average_ms"] == 200.0


def test_gemini_duration_uses_raw_pcm_sample_count():
    assert tts_latency._duration_seconds("gemini", b"\x00\x00" * 24000) == 1.0


def test_gemini_pool_input_wraps_pcm_as_24khz_mono_wav():
    source = b"\x01\x00\x02\x00"
    result = tts_latency._pool_input("gemini", source)
    with wave.open(io.BytesIO(result), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == source


def test_compare_pool_encodes_identical_audio_with_both_transports(monkeypatch):
    native = object()
    file_inputs = []
    pool_inputs = []
    closes = []
    wrapper = SimpleNamespace(wrapped_client=native, close=lambda: closes.append("wrapper"))

    class Pool:
        def heartbeat(self, timeout):
            assert timeout == 30.0
            return True

        def encode(self, audio, timeout):
            assert timeout == 900.0
            pool_inputs.append(audio)
            return SimpleNamespace(audio_bytes=b"pool-encoded")

    class Audio:
        def open_stream_pool(self, token_id, **kwargs):
            assert token_id == "token-1"
            assert kwargs["connections"] == 1
            return Pool()

    class FakeOfSpectrum:
        def __init__(self, api_key):
            assert api_key == "key-1"
            self.audio = Audio()

        def close(self):
            closes.append("pool")

    def call(client):
        assert client is native
        return b"same-native-audio"

    def file_encode(audio):
        file_inputs.append(audio)
        return b"file-encoded"

    monkeypatch.setattr(
        tts_latency, "_build",
        lambda args: (wrapper, call, lambda result: result, file_encode, "audio.speech.create",
                      {"model": "test-model"}),
    )
    monkeypatch.setattr(tts_latency, "OfSpectrum", FakeOfSpectrum)
    monkeypatch.setattr(tts_latency, "_required",
                        lambda name: {"OFSPECTRUM_API_KEY": "key-1",
                                      "OFSPECTRUM_TOKEN_ID": "token-1"}[name])
    monkeypatch.setattr(tts_latency, "_duration_seconds", lambda provider, audio: 5.0)
    ticks = iter(index * 0.1 for index in range(100))
    monkeypatch.setattr(tts_latency.time, "perf_counter", lambda: next(ticks))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda *args: None))
    args = argparse.Namespace(
        provider="openai", text="original", duration_tiers=False, compare_pool=True,
        iterations=1, warmups=0,
    )

    report = tts_latency.run(args)

    assert file_inputs == pool_inputs == [b"same-native-audio"] * 3
    assert [tier["target_seconds"] for tier in report["tiers"]] == [5, 10, 30]
    assert all(tier["file_encode"]["average_ms"] == 100.0 for tier in report["tiers"])
    assert all(tier["pooled_encode"]["average_ms"] == 100.0 for tier in report["tiers"])
    assert report["pool"]["warmup_ms_excluded_from_encode"] == 100.0
    assert closes == ["pool", "wrapper"]
