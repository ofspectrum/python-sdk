import io
import math
import wave

import pytest

from ofspectrum import OfSpectrum
from ofspectrum.media import (
    CANONICAL_SAMPLE_RATE,
    iter_canonical_pcm_chunks,
    probe_audio,
    rebuild_encoded_media,
)


def _sine_wav_bytes(*, seconds=2.7, sample_rate=48000, channels=1, amplitude=0.2):
    frames = int(seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        samples = bytearray()
        for index in range(frames):
            value = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / sample_rate))
            packed = value.to_bytes(2, "little", signed=True)
            samples.extend(packed * channels)
        handle.writeframes(bytes(samples))
    return buffer.getvalue()


def test_probe_and_chunk_canonical_pcm_from_wav():
    wav = _sine_wav_bytes()
    info = probe_audio(wav)
    assert info.sample_rate == 48000
    assert info.channels == 1
    assert info.extension == "wav"
    chunks = list(iter_canonical_pcm_chunks(wav, chunk_samples=24000))
    assert chunks
    total = b"".join(chunks)
    assert len(total) % 4 == 0
    seconds = len(total) / 4 / CANONICAL_SAMPLE_RATE
    assert 2.6 <= seconds <= 2.8


def test_rebuild_wav_roundtrip_keeps_rate():
    wav = _sine_wav_bytes()
    info = probe_audio(wav)
    pcm = b"".join(iter_canonical_pcm_chunks(wav))
    rebuilt = rebuild_encoded_media(pcm, info)
    rebuilt_info = probe_audio(rebuilt)
    assert rebuilt_info.sample_rate == 48000
    assert rebuilt_info.channels == 1
    assert rebuilt_info.extension == "wav"
    assert rebuilt[:4] == b"RIFF"


def test_stream_encode_uses_pcm_chunks_and_rebuilds(monkeypatch):
    wav = _sine_wav_bytes()
    client = OfSpectrum(api_key="test-key")
    captured = {}

    class _FakePool:
        def _encode_pcm(self, pcm, timeout=None):
            captured["pcm"] = pcm
            captured["timeout"] = timeout
            from ofspectrum.models.audio import StreamingEncodeResult

            return StreamingEncodeResult(
                encoded_pcm=pcm,
                token_id="token-1",
                sample_rate=48000,
                channels=1,
                events=[{"type": "flush_done"}],
                quality_warning=False,
            )

    def fake_auto_pool(**kwargs):
        captured["pool_kwargs"] = kwargs
        return _FakePool()

    client.audio._auto_stream_pool = fake_auto_pool
    try:
        result = client.audio.stream_encode(
            wav,
            "token-1",
            strength=1.0,
            smooth=True,
            interval=0.0,
            save_file=False,
            keep_original=False,
            check_watermark=False,
            response_format="stream",
        )
    finally:
        client.close()

    assert captured["pool_kwargs"]["token_id"] == "token-1"
    assert captured["pool_kwargs"]["sample_rate"] == 48000
    assert captured["pool_kwargs"]["channels"] == 1
    assert captured["pool_kwargs"]["smooth"] is True
    assert captured["pcm"]
    assert result.success is True
    assert result.audio_bytes
    assert result.content_type == "audio/wav"
    assert result.file_name.endswith(".wav")
    assert result.audio_bytes[:4] == b"RIFF"


def test_stream_encode_sends_stereo_on_one_persistent_connection(monkeypatch):
    wav = _sine_wav_bytes(channels=2)
    client = OfSpectrum(api_key="test-key")
    captured = {}

    class _FakePool:
        def _encode_pcm(self, pcm, timeout=None):
            captured["pcm"] = pcm
            from ofspectrum.models.audio import StreamingEncodeResult

            return StreamingEncodeResult(
                encoded_pcm=pcm,
                token_id="token-1",
                sample_rate=48000,
                channels=2,
                events=[{"type": "flush_done"}],
                quality_warning=False,
            )

    def fake_auto_pool(**kwargs):
        captured["pool_kwargs"] = kwargs
        return _FakePool()

    client.audio._auto_stream_pool = fake_auto_pool
    try:
        result = client.audio.stream_encode(
            wav,
            "token-1",
            save_file=False,
            keep_original=False,
            check_watermark=False,
            response_format="stream",
        )
    finally:
        client.close()

    assert captured["pool_kwargs"]["channels"] == 2
    rebuilt = probe_audio(result.audio_bytes)
    assert rebuilt.channels == 2


def test_stream_encode_rejects_storage_and_precheck_flags():
    client = OfSpectrum(api_key="test-key")
    wav = _sine_wav_bytes()
    try:
        with pytest.raises(ValueError, match="save_file"):
            client.audio.stream_encode(wav, "token-1", save_file=True)
        with pytest.raises(ValueError, match="keep_original"):
            client.audio.stream_encode(wav, "token-1", keep_original=True)
        with pytest.raises(ValueError, match="check_watermark"):
            client.audio.stream_encode(wav, "token-1", check_watermark=True)
        with pytest.raises(ValueError, match="response_format"):
            client.audio.stream_encode(wav, "token-1", response_format="json")
        with pytest.raises(ValueError, match="output_path"):
            client.audio.stream_encode(wav, "token-1", output_path="out.wav")
    finally:
        client.close()
