"""Transparent wrapper for OpenAI's completed audio responses."""

from __future__ import annotations

import base64
from typing import Any, Dict, Iterable, Optional, Tuple

from ._tts import TTSClientProxy, _encode_pcm, _member
from .elevenlabs import WatermarkController


class OpenAITTS(TTSClientProxy):
    """Wrap an OpenAI client and watermark completed generated audio.

    ``audio.speech.create`` covers ``gpt-4o-mini-tts``, its dated snapshots,
    ``tts-1``, and ``tts-1-hd``. ``chat.completions.create`` covers audio
    output from models such as ``gpt-audio-1.5``. Synchronous and asynchronous
    clients are supported, and completed responses retain their normal types.
    """

    def __init__(
        self, openai_client: Any, *, watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None, token_id: Optional[str] = None,
        enabled: bool = True, transport: str = "pool",
        audio_methods: Optional[Iterable[str]] = None,
        **encode_options: Any,
    ) -> None:
        if openai_client is None:
            raise ValueError("openai_client is required")
        controller = WatermarkController(
            client=watermark_client, api_key=api_key, token_id=token_id,
            enabled=enabled, transport=transport, encode_options=encode_options,
            audio_methods=("audio.speech.create", "chat.completions.create")
            if audio_methods is None else audio_methods,
        )
        super().__init__(openai_client, controller, self._transform_audio)
        object.__setattr__(self, "watermark", controller)

    def _transform_audio(
        self, response: Any, args: Tuple[Any, ...], kwargs: Dict[str, Any],
    ) -> Any:
        if _member(response, "choices") is not None:
            return self._transform_chat_audio(response, kwargs)
        if kwargs.get("stream_format") == "sse":
            raise ValueError("OpenAI SSE speech responses require streaming watermark encoding")
        fmt_value = kwargs.get("response_format", "mp3") or "mp3"
        fmt = str(getattr(fmt_value, "value", fmt_value)).lower()
        raw = response if isinstance(response, bytes) else getattr(response, "content", None)
        if not isinstance(raw, bytes) or not raw:
            return response
        encoded = self._encode_audio(raw, fmt, filename="openai-tts-output")
        if isinstance(response, bytes):
            return encoded
        original = getattr(response, "response", None)
        if original is None or not all(
            hasattr(original, name) for name in ("status_code", "headers", "request", "extensions")
        ):
            raise TypeError("OpenAI speech response is not an HTTP binary response")
        headers = dict(original.headers)
        for name in ("content-length", "content-encoding", "transfer-encoding"):
            headers.pop(name, None)
        response.response = type(original)(
            original.status_code, headers=headers, content=encoded,
            request=original.request, extensions=dict(original.extensions),
        )
        return response

    def _transform_chat_audio(self, response: Any, kwargs: Dict[str, Any]) -> Any:
        if kwargs.get("stream"):
            return response
        audio_config = kwargs.get("audio")
        fmt_value = _member(audio_config, "format")
        fmt = str(getattr(fmt_value, "value", fmt_value) or "").lower()
        for choice in _member(response, "choices", ()) or ():
            message = _member(choice, "message")
            audio = _member(message, "audio")
            data = _member(audio, "data")
            if not isinstance(data, str) or not data:
                continue
            if not fmt:
                raise ValueError(
                    "OpenAI Chat Completions audio requires the request audio.format"
                )
            raw = base64.b64decode(data, validate=True)
            encoded = self._encode_audio(
                raw, fmt, filename="openai-chat-audio-output"
            )
            encoded_data = base64.b64encode(encoded).decode("ascii")
            if isinstance(audio, dict):
                audio["data"] = encoded_data
            else:
                audio.data = encoded_data
        return response

    def _encode_audio(self, raw: bytes, fmt: str, *, filename: str) -> bytes:
        if fmt in {"pcm", "pcm16"}:
            return _encode_pcm(
                self.watermark, raw, filename=filename, sample_rate=24000,
            )
        if fmt not in {"mp3", "opus", "aac", "flac", "wav"}:
            raise ValueError("Unsupported OpenAI audio format: " + fmt)
        return self.watermark.encode_bytes(raw, filename=filename + "." + fmt)


__all__ = ["OpenAITTS"]
