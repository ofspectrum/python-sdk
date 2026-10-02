"""Transparent wrappers for Google Gemini and Cloud Text-to-Speech clients.

Provider packages are optional. Pass their native client instances; the
wrappers only change completed audio results.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Iterable, Optional, Tuple

from ._tts import TTSClientProxy, _audio_format, _encode_pcm, _member, _pcm_spec
from .elevenlabs import WatermarkController

_GEMINI_AUDIO_EXTENSIONS = {
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/alaw": "alaw",
    "audio/flac": "flac",
    "audio/m4a": "m4a",
    "audio/mp3": "mp3",
    "audio/mpeg": "mp3",
    "audio/mulaw": "ulaw",
    "audio/ogg": "ogg",
    "audio/ogg_opus": "ogg",
    "audio/opus": "opus",
    "audio/wav": "wav",
    "audio/webm": "webm",
}


def _positive_int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _encode_gemini_audio(
    controller: WatermarkController, raw: bytes, block: Any, *, filename: str,
    fallback_format: Any = None,
) -> bytes:
    mime = str(
        _member(block, "mime_type") or _member(fallback_format, "mime_type") or ""
    )
    base_mime = mime.split(";", 1)[0].strip().lower()
    if base_mime in {"", "audio/l16", "audio/pcm"}:
        mime_rate, mime_channels = _pcm_spec(mime)
        rate = _positive_int(
            _member(block, "sample_rate") or _member(fallback_format, "sample_rate"),
            mime_rate,
        )
        channels = _positive_int(_member(block, "channels"), mime_channels)
        return _encode_pcm(
            controller, raw, filename=filename, sample_rate=rate, channels=channels,
        )
    extension = _GEMINI_AUDIO_EXTENSIONS.get(base_mime)
    if extension is None:
        raise ValueError("Unsupported Gemini audio MIME type: " + mime)
    return controller.encode_bytes(raw, filename=filename + "." + extension)


def _controller(
    watermark_client: Optional[Any], api_key: Optional[str], token_id: Optional[str],
    enabled: bool, transport: str, audio_methods: Optional[Iterable[str]], defaults: Iterable[str],
    encode_options: Dict[str, Any],
) -> WatermarkController:
    return WatermarkController(
        client=watermark_client, api_key=api_key, token_id=token_id,
        enabled=enabled, transport=transport,
        audio_methods=defaults if audio_methods is None else audio_methods,
        encode_options=encode_options,
    )


class Gemini(TTSClientProxy):
    """Wrap ``google.genai.Client`` for completed Gemini audio generations.

    Supports synchronous and asynchronous ``interactions.create`` audio
    responses, plus ``models.generate_content`` for Gemini 3.1 Flash TTS,
    Gemini 2.5 Flash/Pro TTS, and other models returning inline audio. Native
    streaming remains unchanged.
    """

    def __init__(
        self, gemini_client: Any, *, watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None, token_id: Optional[str] = None,
        enabled: bool = True, transport: str = "pool",
        audio_methods: Optional[Iterable[str]] = None,
        **encode_options: Any,
    ) -> None:
        if gemini_client is None:
            raise ValueError("gemini_client is required")
        controller = _controller(
            watermark_client, api_key, token_id, enabled, transport, audio_methods,
            (
                "models.generate_content", "interactions.create",
                "aio.models.generate_content", "aio.interactions.create",
            ),
            encode_options,
        )
        super().__init__(gemini_client, controller, self._transform_audio)
        object.__setattr__(self, "watermark", controller)

    def _transform_audio(
        self, response: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any],
    ) -> Any:
        if kwargs.get("stream"):
            return response
        if _member(response, "candidates") is not None:
            model = str(kwargs.get("model", "")).lower()
            for candidate in _member(response, "candidates", ()) or ():
                content = _member(candidate, "content")
                for part in _member(content, "parts", ()) or ():
                    blob = _member(part, "inline_data")
                    if blob is None:
                        continue
                    mime = str(_member(blob, "mime_type", "") or "")
                    if not mime.lower().startswith("audio/") and "tts" not in model:
                        continue
                    data = _member(blob, "data")
                    if not isinstance(data, bytes) or not data:
                        continue
                    encoded = _encode_gemini_audio(
                        self.watermark, data, blob, filename="gemini-output"
                    )
                    if isinstance(blob, dict):
                        blob["data"] = encoded
                    else:
                        blob.data = encoded
            return response

        audio = _member(response, "output_audio")
        if audio is None:
            return response
        data = _member(audio, "data")
        if not isinstance(data, str) or not data:
            return response
        raw = base64.b64decode(data, validate=True)
        encoded = _encode_gemini_audio(
            self.watermark, raw, audio, filename="gemini-output",
            fallback_format=kwargs.get("response_format"),
        )
        if isinstance(audio, dict):
            audio["data"] = base64.b64encode(encoded).decode("ascii")
        else:
            audio.data = base64.b64encode(encoded).decode("ascii")
        return response


class GoogleCloudTTS(TTSClientProxy):
    """Wrap ``google.cloud.texttospeech.TextToSpeechClient.synthesize_speech``."""

    def __init__(
        self, cloud_tts_client: Any, *, watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None, token_id: Optional[str] = None,
        enabled: bool = True, transport: str = "pool",
        audio_methods: Optional[Iterable[str]] = None,
        **encode_options: Any,
    ) -> None:
        if cloud_tts_client is None:
            raise ValueError("cloud_tts_client is required")
        controller = _controller(
            watermark_client, api_key, token_id, enabled, transport, audio_methods,
            ("synthesize_speech",), encode_options,
        )
        super().__init__(cloud_tts_client, controller, self._transform_audio)
        object.__setattr__(self, "watermark", controller)

    def _transform_audio(
        self, response: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any],
    ) -> Any:
        audio = _member(response, "audio_content")
        if not isinstance(audio, bytes) or not audio:
            return response
        request = kwargs.get("request", args[0] if args else None)
        config = kwargs.get("audio_config") or _member(request, "audio_config")
        encoding = _audio_format(_member(config, "audio_encoding"))
        extension = {"LINEAR16": "wav", "MP3": "mp3", "OGG_OPUS": "ogg",
                     "MULAW": "wav", "ALAW": "wav", "M4A": "m4a"}.get(encoding)
        if encoding == "PCM":
            rate = _member(config, "sample_rate_hertz")
            if not isinstance(rate, int) or rate <= 0:
                raise ValueError("Cloud TTS PCM requires audio_config.sample_rate_hertz")
            encoded = _encode_pcm(
                self.watermark, audio, filename="google-cloud-tts-output",
                sample_rate=rate,
            )
        elif extension is not None:
            encoded = self.watermark.encode_bytes(
                audio, filename="google-cloud-tts-output." + extension
            )
        else:
            raise ValueError("Unsupported Cloud TTS audio encoding: " + encoding)
        if isinstance(response, dict):
            response["audio_content"] = encoded
        else:
            response.audio_content = encoded
        return response


__all__ = ["Gemini", "GoogleCloudTTS"]
