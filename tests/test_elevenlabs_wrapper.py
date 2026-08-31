from types import SimpleNamespace

import pytest

from ofspectrum import Ofspectrum, WatermarkConfigurationError


class _FakeWatermarkAudio:
    def __init__(self):
        self.calls = []

    def encode(self, audio, token_id, **kwargs):
        source = audio.read()
        self.calls.append((source, token_id, kwargs, audio.name))
        return SimpleNamespace(audio_bytes=b"watermarked:" + source)


class _FakeWatermarkClient:
    def __init__(self):
        self.audio = _FakeWatermarkAudio()
        self.closed = False

    def close(self):
        self.closed = True


class _TextToSpeech:
    def __init__(self):
        self.calls = []
        self.stream_result = iter([b"live-1", b"live-2"])

    def convert(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return iter([b"original-", b"audio"])

    def stream(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.stream_result

    def convert_with_timestamps(self, **kwargs):
        return {"audio_base_64": "not-direct-audio", "alignment": []}


class _Models:
    def __init__(self):
        self.result = [{"id": "eleven-v3"}]

    def list(self):
        return self.result


class _FakeElevenLabs:
    def __init__(self):
        self.text_to_speech = _TextToSpeech()
        self.models = _Models()
        self.closed = False

    def close(self):
        self.closed = True


def _wrapper(**kwargs):
    elevenlabs = _FakeElevenLabs()
    watermark = _FakeWatermarkClient()
    return Ofspectrum(
        elevenlabs,
        watermark_client=watermark,
        token_id="token-1",
        **kwargs,
    ), elevenlabs, watermark


def test_convert_preserves_call_and_returns_watermarked_iterator():
    client, elevenlabs, watermark = _wrapper()

    result = client.text_to_speech.convert(
        "positional", text="hello", output_format="wav_44100"
    )

    assert elevenlabs.text_to_speech.calls == [
        (("positional",), {"text": "hello", "output_format": "wav_44100"})
    ]
    assert watermark.audio.calls == []
    assert list(result) == [b"watermarked:original-audio"]
    source, token_id, options, name = watermark.audio.calls[0]
    assert source == b"original-audio"
    assert token_id == "token-1"
    assert name == "elevenlabs-output.wav"
    assert options["save_file"] is False
    assert options["keep_original"] is False
    assert options["response_format"] == "stream"
    assert options["original_filename"] == "elevenlabs-output.wav"


def test_stream_is_returned_without_consuming_or_replacing_it():
    client, elevenlabs, watermark = _wrapper()

    result = client.text_to_speech.stream(text="hello")

    assert result is elevenlabs.text_to_speech.stream_result
    assert list(result) == [b"live-1", b"live-2"]
    assert watermark.audio.calls == []


def test_json_and_metadata_results_keep_exact_identity():
    client, elevenlabs, watermark = _wrapper()

    models = client.models.list()
    timestamped = client.text_to_speech.convert_with_timestamps(text="hello")

    assert models is elevenlabs.models.result
    assert timestamped == {"audio_base_64": "not-direct-audio", "alignment": []}
    assert watermark.audio.calls == []


@pytest.mark.parametrize(
    "path",
    [
        "audio_isolation.convert",
        "conversational_ai.conversations.audio.get",
        "history.get_audio",
        "music.compose",
        "music.video_to_music",
        "sound_generation.text_to_sound_effects",
        "speech_to_speech.convert",
        "text_to_dialogue.convert",
        "text_to_sound_effects.convert",
        "voices.samples.audio.get",
    ],
)
def test_first_phase_complete_audio_endpoints_are_intercepted(path):
    class Resource:
        def convert(self, **kwargs):
            return b"audio"

        def compose(self, **kwargs):
            return b"audio"

        def text_to_sound_effects(self, **kwargs):
            return b"audio"

        def get(self, **kwargs):
            return b"audio"

        def get_audio(self, **kwargs):
            return b"audio"

        def video_to_music(self, **kwargs):
            return b"audio"

    elevenlabs = SimpleNamespace()
    current = elevenlabs
    parts = path.split(".")
    for part in parts[:-1]:
        resource = Resource()
        setattr(current, part, resource)
        current = resource
    watermark = _FakeWatermarkClient()
    client = Ofspectrum(
        elevenlabs, watermark_client=watermark, token_id="token-1"
    )

    callable_object = client
    for part in parts:
        callable_object = getattr(callable_object, part)

    assert callable_object() == b"watermarked:audio"
    assert len(watermark.audio.calls) == 1


def test_unknown_bytes_method_is_not_guessed_to_be_audio():
    class Files:
        def download(self):
            return b"zip-or-other-binary"

    elevenlabs = SimpleNamespace(files=Files())
    watermark = _FakeWatermarkClient()
    client = Ofspectrum(
        elevenlabs, watermark_client=watermark, token_id="token-1"
    )

    assert client.files.download() == b"zip-or-other-binary"
    assert watermark.audio.calls == []


def test_empty_audio_method_registry_disables_default_interception():
    elevenlabs = _FakeElevenLabs()
    watermark = _FakeWatermarkClient()
    client = Ofspectrum(
        elevenlabs,
        watermark_client=watermark,
        token_id="token-1",
        audio_methods=[],
    )

    assert list(client.text_to_speech.convert()) == [b"original-", b"audio"]
    assert watermark.audio.calls == []


def test_custom_complete_audio_method_can_be_registered():
    class FutureAudio:
        def render(self):
            return [b"future-", b"audio"]

    watermark = _FakeWatermarkClient()
    client = Ofspectrum(
        SimpleNamespace(future_audio=FutureAudio()),
        watermark_client=watermark,
        token_id="token-1",
    )
    client.watermark.register_audio_method("future_audio.render")

    assert client.future_audio.render() == [b"watermarked:future-audio"]


def test_disable_returns_native_result_without_requiring_configuration():
    elevenlabs = _FakeElevenLabs()
    client = Ofspectrum(elevenlabs, enabled=False)

    result = client.text_to_speech.convert(text="hello")

    assert list(result) == [b"original-", b"audio"]


def test_missing_token_fails_only_when_intercepted_audio_is_consumed():
    elevenlabs = _FakeElevenLabs()
    client = Ofspectrum(elevenlabs, watermark_client=_FakeWatermarkClient())

    assert client.models.list() is elevenlabs.models.result
    result = client.text_to_speech.convert(text="hello")
    with pytest.raises(WatermarkConfigurationError, match="token_id"):
        list(result)


def test_elevenlabs_exceptions_are_not_wrapped():
    expected = RuntimeError("elevenlabs failure")

    class Broken:
        def convert(self):
            raise expected

    client = Ofspectrum(
        SimpleNamespace(text_to_speech=Broken()),
        watermark_client=_FakeWatermarkClient(),
        token_id="token-1",
    )

    with pytest.raises(RuntimeError) as raised:
        client.text_to_speech.convert()
    assert raised.value is expected


def test_config_updates_options_and_can_toggle_watermarking():
    client, _, watermark = _wrapper()
    client.watermark.config(enabled=False, strength=1.25)
    assert list(client.text_to_speech.convert()) == [b"original-", b"audio"]

    client.watermark.config(enabled=True, token_id="token-2")
    assert list(client.text_to_speech.convert()) == [b"watermarked:original-audio"]
    _, token_id, options, _ = watermark.audio.calls[0]
    assert token_id == "token-2"
    assert options["strength"] == 1.25


def test_close_closes_elevenlabs_but_not_injected_watermark_client():
    client, elevenlabs, watermark = _wrapper()

    client.close()

    assert elevenlabs.closed is True
    assert watermark.closed is False


def test_config_rejects_stream_registration_and_output_side_effect_options():
    client, _, _ = _wrapper()

    with pytest.raises(ValueError, match="streaming"):
        client.watermark.register_audio_method("future_audio.stream")
    with pytest.raises(ValueError, match="streaming"):
        client.watermark.register_audio_method("future_audio.compose_detailed_stream")
    with pytest.raises(TypeError, match="save_file"):
        client.watermark.config(save_file=True)
