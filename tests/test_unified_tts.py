import base64
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ofspectrum import TTS, TTSResult


class WatermarkAudio:
    def __init__(self):
        self.calls = []

    def _encode(self, transport, source, token_id, **kwargs):
        audio = source.read()
        self.calls.append((transport, source.name, audio, token_id, kwargs))
        return SimpleNamespace(audio_bytes=b"marked:" + audio)

    def stream_encode(self, source, token_id, **kwargs):
        return self._encode("pool", source, token_id, **kwargs)

    def encode(self, source, token_id, **kwargs):
        return self._encode("file", source, token_id, **kwargs)


def watermark_client():
    return SimpleNamespace(audio=WatermarkAudio())


class BinaryResponse:
    def __init__(self, content=b"provider-audio"):
        self.response = httpx.Response(
            200,
            content=content,
            request=httpx.Request("POST", "https://api.openai.com/v1/audio/speech"),
        )

    @property
    def content(self):
        return self.response.content


def test_unified_elevenlabs_maps_request_and_returns_common_result(tmp_path):
    calls = []

    class TextToSpeech:
        def convert(self, **kwargs):
            calls.append(kwargs)
            return iter((b"provider-", b"audio"))

    native = SimpleNamespace(text_to_speech=TextToSpeech())
    watermark = watermark_client()
    with TTS("elevenlabs", native, watermark_client=watermark, token_id="token-1") as tts:
        result = tts.synthesize("hello", voice="voice-1")

    assert isinstance(result, TTSResult)
    assert result.audio == result.content == b"marked:provider-audio"
    assert bytes(result) == result.audio
    assert result.provider == "elevenlabs"
    assert result.output_format == "mp3"
    assert result.mime_type == "audio/mpeg"
    assert result.model == "eleven_multilingual_v2"
    assert result.voice == "voice-1"
    assert calls == [
        {
            "text": "hello",
            "voice_id": "voice-1",
            "model_id": "eleven_multilingual_v2",
            "output_format": "mp3_44100_128",
        }
    ]
    assert watermark.audio.calls[0][0:2] == ("pool", "elevenlabs-output.mp3")
    assert result.save(tmp_path / "result.mp3") == Path(tmp_path / "result.mp3")
    assert (tmp_path / "result.mp3").read_bytes() == result.audio


def test_unified_gemini_selects_interactions_for_31_and_extracts_audio():
    calls = []
    block = SimpleNamespace(
        data=base64.b64encode(b"provider-audio").decode("ascii"),
        mime_type="audio/mp3",
    )
    response = SimpleNamespace(output_audio=block)

    class Interactions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    tts = TTS(
        "gemini",
        SimpleNamespace(interactions=Interactions()),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    result = tts.synthesize("hello", model="gemini-3.1-flash-tts-preview", voice="Kore")

    assert result.audio == b"marked:provider-audio"
    assert result.output_format == "mp3"
    assert calls[0]["input"] == "hello"
    assert calls[0]["generation_config"] == {"speech_config": [{"voice": "Kore"}]}


def test_unified_gemini_selects_generate_content_for_25():
    calls = []
    blob = SimpleNamespace(data=b"provider-audio", mime_type="audio/mp3")
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=blob)]))
        ]
    )

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return response

    tts = TTS(
        "google-gemini",
        SimpleNamespace(models=Models()),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    result = tts.synthesize("hello", model="gemini-2.5-flash-preview-tts")

    assert result.audio == b"marked:provider-audio"
    assert calls[0]["contents"] == "hello"
    assert calls[0]["config"]["response_modalities"] == ["AUDIO"]


def test_unified_google_cloud_builds_native_configs():
    calls = []
    response = SimpleNamespace(audio_content=b"provider-audio")

    class CloudClient:
        def synthesize_speech(self, **kwargs):
            calls.append(kwargs)
            return response

    tts = TTS(
        "google-cloud-tts",
        CloudClient(),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    result = tts.synthesize(
        "hello", voice="en-US-Standard-A", language_code="en-US", output_format="mp3"
    )

    assert result.audio == b"marked:provider-audio"
    assert result.output_format == "mp3"
    assert calls == [
        {
            "input": {"text": "hello"},
            "voice": {"language_code": "en-US", "name": "en-US-Standard-A"},
            "audio_config": {"audio_encoding": "MP3"},
        }
    ]


def test_unified_openai_maps_speech_and_advanced_options():
    calls = []

    class Speech:
        def create(self, **kwargs):
            calls.append(kwargs)
            return BinaryResponse()

    tts = TTS(
        "openai",
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    result = tts.synthesize(
        "hello",
        model="gpt-4o-mini-tts",
        voice="alloy",
        output_format="mp3",
        provider_options={"speed": 1.1},
    )

    assert result.audio == b"marked:provider-audio"
    assert calls == [
        {
            "speed": 1.1,
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            "input": "hello",
            "response_format": "mp3",
        }
    ]


def test_unified_repeated_calls_keep_default_pool_transport():
    class Speech:
        def create(self, **kwargs):
            return BinaryResponse()

    watermark = watermark_client()
    tts = TTS(
        "openai",
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark,
        token_id="token-1",
    )

    tts.synthesize("first")
    tts.synthesize("second")

    assert [call[0] for call in watermark.audio.calls] == ["pool", "pool"]


def test_unified_openai_selects_chat_audio_from_model():
    calls = []
    audio = SimpleNamespace(data=base64.b64encode(b"provider-audio").decode("ascii"))
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(audio=audio))])

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    tts = TTS(
        "openai",
        SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    result = tts.synthesize("hello", model="gpt-audio-1.5", output_format="wav")

    assert result.audio == b"marked:provider-audio"
    assert result.output_format == "wav"
    assert calls[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert calls[0]["audio"] == {"voice": "alloy", "format": "wav"}


def test_unified_azure_openai_requires_deployment_name():
    native = SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=lambda **_: None)))
    tts = TTS("azure-openai", native, watermark_client=watermark_client(), token_id="token-1")
    with pytest.raises(ValueError, match="deployment name"):
        tts.synthesize("hello")


def test_unified_azure_speech_maps_voice_to_ssml_and_returns_audio():
    calls = []

    class Synthesizer:
        def speak_ssml(self, ssml):
            calls.append(ssml)
            return SimpleNamespace(audio_data=b"provider-audio")

    tts = TTS(
        "azure-ai-speech",
        Synthesizer(),
        watermark_client=watermark_client(),
        token_id="token-1",
        azure_output_format="audio-24khz-96kbitrate-mono-mp3",
    )
    result = tts.synthesize(
        "hello & goodbye",
        voice="en-US-AvaNeural",
        language_code="en-US",
        output_format="mp3",
    )

    assert result.audio == b"marked:provider-audio"
    assert result.output_format == "mp3"
    assert 'name="en-US-AvaNeural"' in calls[0]
    assert "hello &amp; goodbye" in calls[0]


@pytest.mark.asyncio
async def test_unified_async_openai_awaits_provider_and_watermark():
    closed = []

    class Speech:
        async def create(self, **kwargs):
            return BinaryResponse()

    class AsyncClient:
        def __init__(self):
            self.audio = SimpleNamespace(speech=Speech())

        async def close(self):
            closed.append(True)

    async with TTS(
        "openai",
        AsyncClient(),
        watermark_client=watermark_client(),
        token_id="token-1",
    ) as tts:
        result = await tts.synthesize_async("hello")

    assert result.audio == b"marked:provider-audio"
    assert closed == [True]


@pytest.mark.asyncio
async def test_unified_async_elevenlabs_collects_and_watermarks_audio():
    async def chunks():
        yield b"provider-"
        yield b"audio"

    class TextToSpeech:
        async def convert(self, **kwargs):
            return chunks()

    watermark = watermark_client()
    tts = TTS(
        "elevenlabs",
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark,
        token_id="token-1",
    )
    result = await tts.synthesize_async("hello", voice="voice-1")

    assert result.audio == b"marked:provider-audio"
    assert len(watermark.audio.calls) == 1


@pytest.mark.asyncio
async def test_unified_async_method_can_run_a_sync_azure_client_off_loop():
    native = SimpleNamespace(speak_text=lambda text: SimpleNamespace(audio_data=b"provider-audio"))
    tts = TTS(
        "azure-speech",
        native,
        watermark_client=watermark_client(),
        token_id="token-1",
        azure_output_format="audio-24khz-96kbitrate-mono-mp3",
    )

    result = await tts.synthesize_async("hello")

    assert result.audio == b"marked:provider-audio"


def test_unified_interface_rejects_unknown_provider_and_async_client():
    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        TTS("unknown", object())

    class Speech:
        async def create(self, **kwargs):
            return BinaryResponse()

    tts = TTS(
        "openai",
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark_client(),
        token_id="token-1",
    )
    with pytest.raises(TypeError, match="synthesize_async"):
        tts.synthesize("hello")
