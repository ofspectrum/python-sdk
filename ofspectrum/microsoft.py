"""Watermark completed Azure AI Speech synthesis results."""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, Iterable, Optional, Tuple

from ._tts import TTSClientProxy, _encode_pcm
from .elevenlabs import WatermarkController

_COMPLETE_METHODS = (
    "speak_text", "speak_ssml", "speak",
    "speak_text_async", "speak_ssml_async", "speak_async",
)


class _SynthesisFuture:
    """Keep Azure's ``.get()`` interface while encoding the resolved result once."""

    def __init__(self, future: Any, transform: Any) -> None:
        self._future = future
        self._transform = transform
        self._resolved = False
        self._result = None
        self._error: Optional[BaseException] = None
        self._get_lock = threading.Lock()

    def get(self) -> Any:
        # One native future represents one encode, even with multiple readers.
        # Memoize failures too: repeating an ambiguous encode is not a read.
        with self._get_lock:
            if not self._resolved:
                try:
                    result = self._future.get()
                    self._result = self._transform(result)
                except BaseException as exc:
                    self._error = exc
                finally:
                    self._resolved = True
            if self._error is not None:
                raise self._error
            return self._result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._future, name)

    def __dir__(self) -> Any:
        return sorted(set(object.__dir__(self)) | set(dir(self._future)))


class AzureSpeechTTS(TTSClientProxy):
    """Wrap ``azure.cognitiveservices.speech.SpeechSynthesizer``.

    Completed ``speak_text``, ``speak_ssml``, and ``speak`` results keep their
    native result type. Their ``*_async`` variants keep Azure's ``.get()``
    calling pattern and encode when the future is resolved. Streaming
    ``start_speaking*`` methods are left untouched.
    """

    def __init__(
        self, speech_synthesizer: Any, *, watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None, token_id: Optional[str] = None,
        enabled: bool = True, transport: str = "pool",
        audio_methods: Optional[Iterable[str]] = None,
        output_format: Optional[str] = None, **encode_options: Any,
    ) -> None:
        if speech_synthesizer is None:
            raise ValueError("speech_synthesizer is required")
        controller = WatermarkController(
            client=watermark_client, api_key=api_key, token_id=token_id,
            enabled=enabled, transport=transport, encode_options=encode_options,
            audio_methods=_COMPLETE_METHODS if audio_methods is None else audio_methods,
        )
        super().__init__(speech_synthesizer, controller, self._transform_audio)
        object.__setattr__(self, "watermark", controller)
        object.__setattr__(self, "_output_format", output_format)

    def _configured_format(self, audio: bytes) -> str:
        configured = self._output_format
        if configured is None:
            properties = getattr(self.wrapped_client, "properties", None)
            if properties is not None:
                try:
                    from azure.cognitiveservices.speech import PropertyId
                except ImportError:
                    pass
                else:
                    configured = properties.get_property(
                        PropertyId.SpeechServiceConnection_SynthOutputFormat
                    )
        configured = str(getattr(configured, "value", configured) or "").lower()
        if configured:
            return configured
        # Azure's default output is RIFF PCM. Check the bytes when the SDK
        # reports no explicit format rather than assuming an arbitrary codec.
        if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
            return "riff-default"
        raise ValueError("Azure Speech output format is unavailable; set output_format")

    def _encode_audio(self, audio: bytes) -> bytes:
        fmt = self._configured_format(audio)
        pcm = re.fullmatch(r"raw-(\d+)(khz|hz)-16bit-mono-pcm", fmt)
        if pcm:
            return _encode_pcm(
                self.watermark, audio, filename="azure-speech-output",
                sample_rate=int(pcm.group(1)) * (1000 if pcm.group(2) == "khz" else 1),
            )
        if fmt == "riff-default" or re.fullmatch(
            r"riff-\d+(?:khz|hz)-(?:16bit-mono-pcm|8bit-mono-(?:alaw|mulaw))", fmt
        ):
            extension = "wav"
        elif re.fullmatch(r"audio-\d+khz-\d+kbitrate-mono-mp3", fmt):
            extension = "mp3"
        elif re.fullmatch(r"ogg-\d+khz-16bit-mono-opus", fmt):
            extension = "ogg"
        elif re.fullmatch(r"webm-\d+khz-16bit-(?:\d+kbps-)?mono-opus", fmt):
            extension = "webm"
        elif re.fullmatch(r"raw-\d+khz-8bit-mono-alaw", fmt):
            extension = "alaw"
        elif re.fullmatch(r"raw-\d+khz-8bit-mono-mulaw", fmt):
            extension = "ulaw"
        else:
            raise ValueError("Unsupported Azure Speech output format: " + fmt)
        return self.watermark.encode_bytes(
            audio, filename="azure-speech-output." + extension
        )

    def _transform_audio(
        self, response: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any],
    ) -> Any:
        if not hasattr(response, "audio_data") and callable(getattr(response, "get", None)):
            return _SynthesisFuture(response, lambda result: self._transform_audio(result, args, kwargs))
        audio = getattr(response, "audio_data", None)
        if not isinstance(audio, bytes) or not audio:
            return response
        encoded = self._encode_audio(audio)
        try:
            response.audio_data = encoded
        except AttributeError:
            # Azure SpeechSynthesisResult exposes a read-only audio_data
            # property backed by this attribute.
            response._audio_data = encoded
        return response


__all__ = ["AzureSpeechTTS"]
