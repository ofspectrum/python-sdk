import base64
import io
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ofspectrum import Gemini, GoogleCloudTTS, Ofspectrum, OpenAITTS


class WatermarkAudio:
    def __init__(self):
        self.calls = []
        self.transports = []

    def _encode(self, transport, source, token_id, **kwargs):
        audio = source.read()
        self.calls.append((audio, source.name, token_id, kwargs))
        self.transports.append(transport)
        if source.name.endswith(".wav"):
            with wave.open(io.BytesIO(audio), "rb") as input_wav:
                rate, channels = input_wav.getframerate(), input_wav.getnchannels()
                frames = input_wav.readframes(input_wav.getnframes())
            output = io.BytesIO()
            with wave.open(output, "wb") as output_wav:
                output_wav.setframerate(rate)
                output_wav.setnchannels(channels)
                output_wav.setsampwidth(2)
                output_wav.writeframes(bytes(byte ^ 1 for byte in frames))
            result = output.getvalue()
        else:
            result = b"marked:" + audio
        return SimpleNamespace(audio_bytes=result)

    def encode(self, source, token_id, **kwargs):
        return self._encode("file", source, token_id, **kwargs)

    def stream_encode(self, source, token_id, **kwargs):
        return self._encode("pool", source, token_id, **kwargs)


def watermark_client():
    return SimpleNamespace(audio=WatermarkAudio())


def test_elevenlabs_reference_still_watermarks_complete_audio():
    class TextToSpeech:
        def convert(self, **kwargs):
            return iter((b"one", b"two"))

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark, token_id="token-1",
    )
    assert list(client.text_to_speech.convert(text="hi")) == [b"marked:onetwo"]
    assert watermark.audio.calls[0][1] == "elevenlabs-output.mp3"
    assert watermark.audio.transports == ["pool"]


@pytest.mark.asyncio
async def test_elevenlabs_async_convert_watermarks_before_yielding_audio():
    closed = []

    async def chunks():
        try:
            yield b"provider-"
            yield bytearray(b"audio")
        finally:
            closed.append(True)

    class TextToSpeech:
        async def convert(self, **kwargs):
            assert kwargs["text"] == "hello"
            return chunks()

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark, token_id="token-1",
    )

    response = await client.text_to_speech.convert(text="hello")
    assert hasattr(response, "__aiter__")
    assert watermark.audio.calls == []
    assert [chunk async for chunk in response] == [b"marked:provider-audio"]
    assert closed == [True]
    assert len(watermark.audio.calls) == 1
    assert watermark.audio.transports == ["pool"]


@pytest.mark.asyncio
async def test_elevenlabs_direct_async_iterator_and_native_streaming():
    async def chunks():
        yield b"provider-audio"

    class TextToSpeech:
        def convert(self, **kwargs):
            return chunks()

        async def convert_as_stream(self, **kwargs):
            return chunks()

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark, token_id="token-1",
    )

    assert [chunk async for chunk in client.text_to_speech.convert()] == [
        b"marked:provider-audio"
    ]
    stream = await client.text_to_speech.convert_as_stream()
    assert [chunk async for chunk in stream] == [b"provider-audio"]
    assert len(watermark.audio.calls) == 1


@pytest.mark.asyncio
async def test_elevenlabs_async_complete_bytes_are_watermarked():
    class TextToSpeech:
        async def convert(self, **kwargs):
            return b"provider-audio"

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark, token_id="token-1",
    )

    assert await client.text_to_speech.convert() == b"marked:provider-audio"
    assert len(watermark.audio.calls) == 1


@pytest.mark.asyncio
async def test_elevenlabs_async_complete_audio_rejects_non_bytes_chunks():
    async def chunks():
        yield b"provider-audio"
        yield "unexpected text"

    class TextToSpeech:
        async def convert(self, **kwargs):
            return chunks()

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark, token_id="token-1",
    )

    response = await client.text_to_speech.convert()
    with pytest.raises(TypeError, match="non-bytes chunk"):
        async for _ in response:
            pytest.fail("Unencoded audio was yielded")
    assert watermark.audio.calls == []


@pytest.mark.parametrize("model", [
    "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
])
def test_gemini_generate_content_preserves_pcm_response(model):
    pcm = b"\x01\x00\x02\x00"
    blob = SimpleNamespace(data=pcm, mime_type="audio/L16;rate=24000")
    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(inline_data=blob)])
    )])

    class Models:
        def generate_content(self, **kwargs):
            assert kwargs["model"] == model
            return response

    watermark = watermark_client()
    client = Gemini(
        SimpleNamespace(models=Models()), watermark_client=watermark, token_id="token-1",
    )
    result = client.models.generate_content(model=model, contents="hello")
    assert result is response
    assert blob.data == bytes(byte ^ 1 for byte in pcm)
    source, name, token, options = watermark.audio.calls[0]
    assert name == "gemini-output.wav"
    assert source.startswith(b"RIFF")
    assert token == "token-1"
    assert options["save_file"] is False
    assert options["response_format"] == "stream"
    assert options["interval"] == 0.0
    assert options["check_watermark"] is False
    assert watermark.audio.transports == ["pool"]


def test_gemini_interactions_preserves_base64_audio_and_non_audio():
    raw = b"\x01\x00\x02\x00"
    block = SimpleNamespace(data=base64.b64encode(raw).decode(), mime_type="audio/L16;rate=24000")
    audio_response = SimpleNamespace(output_audio=block)
    text_response = SimpleNamespace(output_audio=None, output_text="hello")

    class Interactions:
        def create(self, **kwargs):
            return audio_response if kwargs["model"].endswith("tts-preview") else text_response

    watermark = watermark_client()
    client = Gemini(
        SimpleNamespace(interactions=Interactions()), watermark_client=watermark,
        token_id="token-1",
    )
    assert client.interactions.create(model="gemini-3.1-flash-tts-preview") is audio_response
    assert base64.b64decode(block.data) == bytes(byte ^ 1 for byte in raw)
    assert client.interactions.create(model="gemini-2.5-flash") is text_response
    assert len(watermark.audio.calls) == 1
    assert watermark.audio.transports == ["pool"]


@pytest.mark.parametrize("mime_type,expected_name,transport", [
    ("audio/mp3", "gemini-output.mp3", "pool"),
    ("audio/ogg_opus", "gemini-output.ogg", "pool"),
    ("audio/alaw", "gemini-output.alaw", "file"),
])
def test_gemini_supports_other_inline_audio_formats(
    mime_type, expected_name, transport,
):
    blob = SimpleNamespace(data=b"provider-audio", mime_type=mime_type)
    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(inline_data=blob)])
    )])

    class Models:
        def generate_content(self, **kwargs):
            return response

    watermark = watermark_client()
    client = Gemini(
        SimpleNamespace(models=Models()), watermark_client=watermark, token_id="token-1",
    )
    result = client.models.generate_content(model="gemini-3.1-flash-tts-preview")

    assert result is response
    assert blob.data == b"marked:provider-audio"
    assert watermark.audio.calls[0][1] == expected_name
    assert watermark.audio.transports == [transport]


def test_gemini_interactions_uses_returned_pcm_rate_and_channels():
    raw = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    block = SimpleNamespace(
        data=base64.b64encode(raw).decode("ascii"),
        mime_type="audio/l16",
        sample_rate=16000,
        channels=2,
    )
    response = SimpleNamespace(output_audio=block)

    class Interactions:
        def create(self, **kwargs):
            return response

    watermark = watermark_client()
    client = Gemini(
        SimpleNamespace(interactions=Interactions()), watermark_client=watermark,
        token_id="token-1",
    )
    client.interactions.create(model="gemini-3.1-flash-tts-preview")

    source = watermark.audio.calls[0][0]
    with wave.open(io.BytesIO(source), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 2
    assert base64.b64decode(block.data) == bytes(byte ^ 1 for byte in raw)


@pytest.mark.asyncio
async def test_gemini_async_sdk_path_preserves_and_watermarks_response():
    pcm = b"\x01\x00\x02\x00"
    blob = SimpleNamespace(data=pcm, mime_type="audio/L16;rate=24000")
    response = SimpleNamespace(candidates=[SimpleNamespace(
        content=SimpleNamespace(parts=[SimpleNamespace(inline_data=blob)])
    )])

    class AsyncModels:
        async def generate_content(self, **kwargs):
            assert kwargs["model"] == "gemini-3.1-flash-tts-preview"
            return response

    watermark = watermark_client()
    client = Gemini(
        SimpleNamespace(aio=SimpleNamespace(models=AsyncModels())),
        watermark_client=watermark,
        token_id="token-1",
    )

    result = await client.aio.models.generate_content(
        model="gemini-3.1-flash-tts-preview", contents="hello"
    )

    assert result is response
    assert blob.data == bytes(byte ^ 1 for byte in pcm)
    assert watermark.audio.transports == ["pool"]


@pytest.mark.parametrize("encoding,expected_name", [(2, "google-cloud-tts-output.mp3"),
                                                    (3, "google-cloud-tts-output.ogg")])
def test_cloud_tts_preserves_response_shape(encoding, expected_name):
    response = SimpleNamespace(audio_content=b"provider-audio")

    class CloudClient:
        def synthesize_speech(self, request):
            return response

    watermark = watermark_client()
    client = GoogleCloudTTS(CloudClient(), watermark_client=watermark, token_id="token-1")
    request = SimpleNamespace(audio_config=SimpleNamespace(audio_encoding=encoding))
    assert client.synthesize_speech(request) is response
    assert response.audio_content == b"marked:provider-audio"
    assert watermark.audio.calls[0][1] == expected_name
    assert watermark.audio.transports == ["pool"]


def test_cloud_tts_headerless_pcm_round_trip():
    response = SimpleNamespace(audio_content=b"\x01\x00\x02\x00")

    class CloudClient:
        def synthesize_speech(self, **kwargs):
            return response

    watermark = watermark_client()
    client = GoogleCloudTTS(CloudClient(), watermark_client=watermark, token_id="token-1")
    config = SimpleNamespace(audio_encoding=7, sample_rate_hertz=24000)
    assert client.synthesize_speech(audio_config=config) is response
    assert response.audio_content == b"\x00\x01\x03\x01"


def test_cloud_tts_linear16_wav_is_encoded_as_a_file():
    source = io.BytesIO()
    with wave.open(source, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(b"\x01\x00\x02\x00")
    response = SimpleNamespace(audio_content=source.getvalue())

    class CloudClient:
        def synthesize_speech(self, **kwargs):
            return response

    watermark = watermark_client()
    client = GoogleCloudTTS(CloudClient(), watermark_client=watermark, token_id="token-1")
    client.synthesize_speech(audio_config=SimpleNamespace(audio_encoding=1))
    with wave.open(io.BytesIO(response.audio_content), "rb") as output:
        assert output.readframes(2) == b"\x00\x01\x03\x01"
    assert watermark.audio.calls[0][1] == "google-cloud-tts-output.wav"


class BinaryResponse:
    def __init__(self, content):
        self.response = httpx.Response(200, content=content, request=httpx.Request("POST", "https://api.openai.com/v1/audio/speech"))

    @property
    def content(self):
        return self.response.content

    def read(self):
        return self.response.read()

    def write_to_file(self, path):
        Path(path).write_bytes(self.response.content)


@pytest.mark.parametrize("model", ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"])
def test_openai_speech_retains_binary_response_interface(model, tmp_path):
    response = BinaryResponse(b"provider-audio")

    class Speech:
        def create(self, **kwargs):
            assert kwargs["model"] == model
            return response

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark, token_id="token-1",
    )
    result = client.audio.speech.create(model=model, input="hello", voice="alloy")
    assert result is response
    assert result.content == result.read() == b"marked:provider-audio"
    target = tmp_path / "output.mp3"
    result.write_to_file(target)
    assert target.read_bytes() == result.content
    assert watermark.audio.calls[0][1] == "openai-tts-output.mp3"
    assert watermark.audio.transports == ["pool"]


def test_openai_native_streaming_path_is_unchanged():
    response = object()

    class Speech:
        with_streaming_response = SimpleNamespace(create=lambda **kwargs: response)

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark, token_id="token-1",
    )
    assert client.audio.speech.with_streaming_response.create(model="tts-1") is response
    assert watermark.audio.calls == []


def test_openai_pcm_retains_raw_pcm_format():
    response = BinaryResponse(b"\x01\x00\x02\x00")

    class Speech:
        def create(self, **kwargs):
            return response

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark, token_id="token-1",
    )
    result = client.audio.speech.create(model="gpt-4o-mini-tts", response_format="pcm")
    assert result.content == b"\x00\x01\x03\x01"
    assert watermark.audio.calls[0][1] == "openai-tts-output.wav"
    assert watermark.audio.transports == ["pool"]


def test_openai_chat_completions_retains_response_and_encodes_base64_audio():
    audio = SimpleNamespace(
        id="audio-1",
        data=base64.b64encode(b"provider-audio").decode("ascii"),
        transcript="Hello",
    )
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(audio=audio, content="Hello")
    )])

    class Completions:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-audio-1.5"
            return response

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        watermark_client=watermark,
        token_id="token-1",
    )
    result = client.chat.completions.create(
        model="gpt-audio-1.5",
        messages=[{"role": "user", "content": "Hello"}],
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "mp3"},
    )

    assert result is response
    assert base64.b64decode(audio.data) == b"marked:provider-audio"
    assert audio.id == "audio-1"
    assert audio.transcript == "Hello"
    assert response.choices[0].message.content == "Hello"
    assert watermark.audio.calls[0][1] == "openai-chat-audio-output.mp3"
    assert watermark.audio.transports == ["pool"]


def test_openai_chat_completions_pcm16_retains_raw_format():
    audio = {"data": base64.b64encode(b"\x01\x00\x02\x00").decode("ascii")}
    response = {"choices": [{"message": {"audio": audio}}]}

    class Completions:
        def create(self, **kwargs):
            return response

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        watermark_client=watermark,
        token_id="token-1",
    )
    result = client.chat.completions.create(
        model="gpt-audio-1.5", audio={"voice": "alloy", "format": "pcm16"}
    )

    assert result is response
    assert base64.b64decode(audio["data"]) == b"\x00\x01\x03\x01"
    assert watermark.audio.calls[0][1] == "openai-chat-audio-output.wav"


def test_openai_chat_text_and_streaming_responses_are_unchanged():
    text_response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(audio=None, content="Hello")
    )])
    stream_response = object()

    class Completions:
        def create(self, **kwargs):
            return stream_response if kwargs.get("stream") else text_response

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(chat=SimpleNamespace(completions=Completions())),
        watermark_client=watermark,
        token_id="token-1",
    )

    assert client.chat.completions.create(model="gpt-audio-1.5") is text_response
    assert client.chat.completions.create(model="gpt-audio-1.5", stream=True) is stream_response
    assert watermark.audio.calls == []


@pytest.mark.asyncio
async def test_openai_async_client_audio_is_awaited_and_watermarked():
    audio = SimpleNamespace(data=base64.b64encode(b"provider-audio").decode("ascii"))
    response = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(audio=audio)
    )])
    closed = []

    class AsyncClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=self.Completions())

        class Completions:
            async def create(self, **kwargs):
                return response

        async def close(self):
            closed.append(True)

    watermark = watermark_client()
    client = OpenAITTS(
        AsyncClient(), watermark_client=watermark, token_id="token-1"
    )
    result = await client.chat.completions.create(
        model="gpt-audio-1.5", audio={"voice": "alloy", "format": "mp3"}
    )
    await client.close()

    assert result is response
    assert base64.b64decode(audio.data) == b"marked:provider-audio"
    assert closed == [True]
    assert watermark.audio.transports == ["pool"]


def test_repeated_provider_calls_keep_using_pool_transport():
    class Speech:
        def create(self, **kwargs):
            return b"provider-audio"

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark,
        token_id="token-1",
    )

    assert client.audio.speech.create(model="gpt-4o-mini-tts") == b"marked:provider-audio"
    assert client.audio.speech.create(model="gpt-4o-mini-tts") == b"marked:provider-audio"
    assert watermark.audio.transports == ["pool", "pool"]


def test_file_transport_can_be_selected_at_construction_or_runtime():
    class Speech:
        def create(self, **kwargs):
            return b"provider-audio"

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark,
        token_id="token-1",
        transport="file",
    )
    assert client.watermark.transport == "file"
    client.audio.speech.create(model="gpt-4o-mini-tts")
    client.watermark.config(transport="pool")
    client.audio.speech.create(model="gpt-4o-mini-tts")
    client.watermark.encode_bytes(
        b"provider-audio", filename="standalone.mp3", transport="file"
    )

    assert client.watermark.transport == "pool"
    assert watermark.audio.transports == ["file", "pool", "file"]
    with pytest.raises(ValueError, match="transport"):
        client.watermark.config(transport="invalid")


@pytest.mark.parametrize("options", [{"interval": 2.0}, {"check_watermark": True}])
def test_pool_incompatible_options_preserve_file_encode_behavior(options):
    class Speech:
        def create(self, **kwargs):
            return b"provider-audio"

    watermark = watermark_client()
    client = OpenAITTS(
        SimpleNamespace(audio=SimpleNamespace(speech=Speech())),
        watermark_client=watermark,
        token_id="token-1",
        **options,
    )
    client.audio.speech.create(model="gpt-4o-mini-tts")

    assert watermark.audio.transports == ["file"]


def test_elevenlabs_pcm_uses_pool_and_preserves_headerless_pcm():
    source = b"\x01\x00\x02\x00"

    class TextToSpeech:
        def convert(self, **kwargs):
            return iter((source,))

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark,
        token_id="token-1",
    )
    result = b"".join(client.text_to_speech.convert(output_format="pcm_24000"))

    assert result == bytes(byte ^ 1 for byte in source)
    assert watermark.audio.calls[0][1] == "elevenlabs-output.wav"
    assert watermark.audio.transports == ["pool"]


def test_elevenlabs_raw_telephony_audio_uses_file_transport():
    class TextToSpeech:
        def convert(self, **kwargs):
            return iter((b"raw-ulaw",))

    watermark = watermark_client()
    client = Ofspectrum(
        SimpleNamespace(text_to_speech=TextToSpeech()),
        watermark_client=watermark,
        token_id="token-1",
    )
    assert list(client.text_to_speech.convert(output_format="ulaw_8000")) == [
        b"marked:raw-ulaw"
    ]
    assert watermark.audio.transports == ["file"]
