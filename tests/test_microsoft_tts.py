import io
import wave
from types import SimpleNamespace

import httpx
import pytest

from benchmarks import tts_latency
from ofspectrum import AzureSpeechTTS, OpenAITTS


class WatermarkAudio:
    def __init__(self):
        self.calls = []

    def _encode(self, transport, source, token_id, **kwargs):
        raw = source.read()
        self.calls.append((transport, source.name, raw, token_id))
        if source.name.endswith(".wav"):
            with wave.open(io.BytesIO(raw), "rb") as input_wav:
                rate = input_wav.getframerate()
                channels = input_wav.getnchannels()
                frames = input_wav.readframes(input_wav.getnframes())
            output = io.BytesIO()
            with wave.open(output, "wb") as result:
                result.setframerate(rate)
                result.setnchannels(channels)
                result.setsampwidth(2)
                result.writeframes(bytes(byte ^ 1 for byte in frames))
            encoded = output.getvalue()
        else:
            encoded = b"marked:" + raw
        return SimpleNamespace(audio_bytes=encoded)

    def stream_encode(self, source, token_id, **kwargs):
        return self._encode("pool", source, token_id, **kwargs)

    def encode(self, source, token_id, **kwargs):
        return self._encode("file", source, token_id, **kwargs)


class Result:
    def __init__(self, audio):
        self._audio_data = audio
        self.reason = "SynthesizingAudioCompleted"

    @property
    def audio_data(self):
        return self._audio_data


class Future:
    def __init__(self, result):
        self.result = result
        self.get_calls = 0

    def get(self):
        self.get_calls += 1
        return self.result


def wrapper(synthesizer, output_format="audio-24khz-96kbitrate-mono-mp3"):
    watermark = SimpleNamespace(audio=WatermarkAudio())
    return AzureSpeechTTS(
        synthesizer, watermark_client=watermark, token_id="token-1",
        output_format=output_format,
    ), watermark.audio


@pytest.mark.parametrize("method", ["speak_text", "speak_ssml", "speak"])
def test_completed_azure_methods_keep_result_and_encode(method):
    result = Result(b"provider-audio")
    synthesizer = SimpleNamespace(**{method: lambda text: result})
    client, watermark = wrapper(synthesizer)
    assert getattr(client, method)("hello") is result
    assert result.audio_data == b"marked:provider-audio"
    assert result.reason == "SynthesizingAudioCompleted"
    assert watermark.calls == [
        ("pool", "azure-speech-output.mp3", b"provider-audio", "token-1")
    ]


@pytest.mark.parametrize("method", ["speak_text_async", "speak_ssml_async", "speak_async"])
def test_azure_future_encodes_on_get_only_once(method):
    result = Result(b"provider-audio")
    future = Future(result)
    synthesizer = SimpleNamespace(**{method: lambda text: future})
    client, watermark = wrapper(synthesizer)
    wrapped_future = getattr(client, method)("hello")
    assert result.audio_data == b"provider-audio"
    assert wrapped_future.get() is result
    assert wrapped_future.get() is result
    assert future.get_calls == 1
    assert len(watermark.calls) == 1


def test_azure_raw_pcm_keeps_original_shape_and_pool():
    raw = b"\x01\x00\x02\x00"
    result = Result(raw)
    client, watermark = wrapper(
        SimpleNamespace(speak_text=lambda text: result),
        output_format="raw-24khz-16bit-mono-pcm",
    )
    assert client.speak_text("hello").audio_data == bytes(byte ^ 1 for byte in raw)
    assert watermark.calls[0][0:2] == ("pool", "azure-speech-output.wav")
    assert watermark.calls[0][2].startswith(b"RIFF")


@pytest.mark.parametrize("format_name,filename", [
    ("ogg-24khz-16bit-mono-opus", "azure-speech-output.ogg"),
    ("webm-24khz-16bit-24kbps-mono-opus", "azure-speech-output.webm"),
    ("raw-8khz-8bit-mono-alaw", "azure-speech-output.alaw"),
])
def test_azure_container_and_raw_codec_formats(format_name, filename):
    result = Result(b"provider-audio")
    client, watermark = wrapper(
        SimpleNamespace(speak_text=lambda text: result), output_format=format_name
    )
    assert client.speak_text("hello").audio_data == b"marked:provider-audio"
    assert watermark.calls[0][1] == filename
    assert watermark.calls[0][0] == ("file" if filename.endswith(".alaw") else "pool")


def test_azure_raw_22050_hz_pcm_rate():
    result = Result(b"\x01\x00\x02\x00")
    client, watermark = wrapper(
        SimpleNamespace(speak_text=lambda text: result),
        output_format="raw-22050hz-16bit-mono-pcm",
    )
    client.speak_text("hello")
    with wave.open(io.BytesIO(watermark.calls[0][2]), "rb") as wav:
        assert wav.getframerate() == 22050


def test_azure_native_streaming_method_is_unchanged():
    result = Result(b"provider-audio")
    synth = SimpleNamespace(start_speaking_text_async=lambda text: Future(result))
    client, watermark = wrapper(synth)
    assert client.start_speaking_text_async("hello").get() is result
    assert result.audio_data == b"provider-audio"
    assert watermark.calls == []


def test_azure_unrecognized_format_fails_before_returning_unmarked_audio():
    result = Result(b"provider-audio")
    client, watermark = wrapper(
        SimpleNamespace(speak_text=lambda text: result), output_format="unsupported-codec"
    )
    with pytest.raises(ValueError, match="Unsupported Azure Speech output format"):
        client.speak_text("hello")
    assert watermark.calls == []


def test_azure_sdk_result_and_format_property_integration():
    speechsdk = pytest.importorskip("azure.cognitiveservices.speech")
    config = speechsdk.SpeechConfig(subscription="placeholder", region="eastus")
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
    )
    synth = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    result = object.__new__(speechsdk.SpeechSynthesisResult)
    result._audio_data = b"provider-audio"
    client, watermark = wrapper(synth, output_format=None)
    assert client._configured_format(result.audio_data) == "audio-24khz-96kbitrate-mono-mp3"
    assert client._transform_audio(result, (), {}) is result
    assert result.audio_data == b"marked:provider-audio"
    assert watermark.calls[0][1] == "azure-speech-output.mp3"


def test_azure_openai_speech_uses_existing_openai_wrapper():
    openai = pytest.importorskip("openai")
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(
            200, content=b"provider-audio", headers={"content-type": "audio/mpeg"},
            request=request,
        )

    native = openai.AzureOpenAI(
        api_key="placeholder", azure_endpoint="https://example.openai.azure.com/",
        api_version="2025-04-01-preview",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
    )
    watermark = SimpleNamespace(audio=WatermarkAudio())
    with OpenAITTS(native, watermark_client=watermark, token_id="token-1") as client:
        result = client.audio.speech.create(
            model="tts-deployment", voice="alloy", input="hello"
        )
        assert result.content == b"marked:provider-audio"
    assert len(seen) == 1
    assert watermark.audio.calls[0][1] == "openai-tts-output.mp3"


@pytest.mark.parametrize("provider", ["azure-speech", "azure-openai"])
def test_azure_benchmark_uses_same_duration_runner(monkeypatch, provider):
    for key in (
        "OFSPECTRUM_API_KEY", "OFSPECTRUM_TOKEN_ID", "AZURE_SPEECH_KEY",
        "AZURE_SPEECH_REGION", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION", "AZURE_OPENAI_TTS_DEPLOYMENT",
    ):
        monkeypatch.setenv(key, "https://example.openai.azure.com/" if key.endswith("ENDPOINT") else "placeholder")
    args = SimpleNamespace(
        provider=provider, voice=None, model=None, text="hello", openai_endpoint="speech"
    )
    wrapped, call, extract, encode, endpoint, request = tts_latency._build(args)
    try:
        assert callable(call) and callable(extract) and callable(encode)
        assert endpoint == ("speak_text" if provider == "azure-speech" else "audio.speech.create")
        assert request["output_format"] == "mp3"
    finally:
        wrapped.close()


def test_azure_speech_benchmark_accepts_resource_endpoint(monkeypatch):
    pytest.importorskip("azure.cognitiveservices.speech")
    monkeypatch.setenv("OFSPECTRUM_API_KEY", "placeholder")
    monkeypatch.setenv("OFSPECTRUM_TOKEN_ID", "placeholder")
    monkeypatch.setenv("AZURE_SPEECH_KEY", "placeholder")
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    monkeypatch.setenv(
        "AZURE_SPEECH_ENDPOINT", "https://example.cognitiveservices.azure.com/"
    )
    args = SimpleNamespace(provider="azure-speech", voice=None, model=None, text="hello")
    wrapped, _, _, _, endpoint, _ = tts_latency._build(args)
    try:
        assert endpoint == "speak_text"
    finally:
        wrapped.close()
