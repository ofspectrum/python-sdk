"""Unified completed-audio TTS interface built on the provider wrappers."""

from __future__ import annotations

import asyncio
import base64
import functools
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple, Union
from xml.sax.saxutils import escape, quoteattr

from ._tts import _audio_format, _member
from .elevenlabs import Ofspectrum
from .google import Gemini, GoogleCloudTTS
from .microsoft import AzureSpeechTTS
from .openai import OpenAITTS

_PROVIDER_ALIASES = {
    "elevenlabs": "elevenlabs",
    "eleven-labs": "elevenlabs",
    "gemini": "gemini",
    "google-gemini": "gemini",
    "google-cloud-tts": "google-cloud-tts",
    "google-cloud": "google-cloud-tts",
    "cloud-tts": "google-cloud-tts",
    "openai": "openai",
    "azure-openai": "azure-openai",
    "azure-speech": "azure-speech",
    "azure-ai-speech": "azure-speech",
    "microsoft-speech": "azure-speech",
}

_MIME_TYPES = {
    "aac": "audio/aac",
    "aiff": "audio/aiff",
    "alaw": "audio/alaw",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "pcm": "audio/L16",
    "ulaw": "audio/mulaw",
    "wav": "audio/wav",
    "webm": "audio/webm",
}

_ELEVENLABS_FORMATS = {
    "alaw": "alaw_8000",
    "mp3": "mp3_44100_128",
    "opus": "opus_48000_128",
    "pcm": "pcm_24000",
    "pcm16": "pcm_24000",
    "ulaw": "ulaw_8000",
    "wav": "wav_44100",
}

_CLOUD_FORMATS = {
    "alaw": "ALAW",
    "m4a": "M4A",
    "mp3": "MP3",
    "ogg": "OGG_OPUS",
    "opus": "OGG_OPUS",
    "pcm": "PCM",
    "pcm16": "PCM",
    "ulaw": "MULAW",
    "wav": "LINEAR16",
}


def _normalized_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field_name + " must be a non-empty string")
    return value.strip().lower().replace("_", "-")


def _optional_string(value: Optional[str], *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field_name + " must be a non-empty string or None")
    return value.strip()


def _format_name(value: Optional[str], default: Optional[str] = None) -> Optional[str]:
    resolved = value if value is not None else default
    if resolved is None:
        return None
    if not isinstance(resolved, str) or not resolved.strip():
        raise ValueError("output_format must be a non-empty string or None")
    normalized = resolved.strip().lower().lstrip(".")
    return {"linear16": "wav", "mulaw": "ulaw", "pcm16": "pcm"}.get(normalized, normalized)


def _mime_format(mime_type: Any) -> str:
    base = str(mime_type or "audio/L16").split(";", 1)[0].strip().lower()
    resolved = {
        "audio/aac": "aac",
        "audio/aiff": "aiff",
        "audio/alaw": "alaw",
        "audio/flac": "flac",
        "audio/l16": "pcm",
        "audio/m4a": "m4a",
        "audio/mp3": "mp3",
        "audio/mpeg": "mp3",
        "audio/mulaw": "ulaw",
        "audio/ogg": "ogg",
        "audio/ogg_opus": "ogg",
        "audio/opus": "opus",
        "audio/pcm": "pcm",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }.get(base)
    if resolved is not None:
        return resolved
    return base[6:] if base.startswith("audio/") else base


def _mapping(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("provider_options must be a mapping or None")
    return dict(value)


def _copy_mapping(value: Any, defaults: Mapping[str, Any]) -> Any:
    if value is None:
        return dict(defaults)
    if isinstance(value, Mapping):
        result = dict(value)
        for key, default in defaults.items():
            result.setdefault(key, default)
        return result
    return value


def _audio_bytes(value: Any) -> Optional[bytes]:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    return None


def _native_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _azure_format(value: str) -> str:
    normalized = str(value or "").lower()
    if "mp3" in normalized:
        return "mp3"
    if normalized.startswith("ogg-"):
        return "ogg"
    if normalized.startswith("webm-"):
        return "webm"
    if normalized.endswith("-alaw"):
        return "alaw"
    if normalized.endswith("-mulaw"):
        return "ulaw"
    if normalized.startswith("raw-") and normalized.endswith("-pcm"):
        return "pcm"
    if normalized == "riff-default" or normalized.startswith("riff-"):
        return "wav"
    raise ValueError("Unsupported Azure Speech output format: " + normalized)


@dataclass(frozen=True)
class TTSResult:
    """A provider-neutral completed TTS result containing watermarked audio."""

    audio: bytes
    provider: str
    output_format: str
    model: Optional[str] = None
    voice: Optional[str] = None
    provider_response: Any = field(default=None, repr=False, compare=False)

    @property
    def content(self) -> bytes:
        """Alias for ``audio`` for callers used to binary HTTP responses."""
        return self.audio

    @property
    def mime_type(self) -> str:
        return _MIME_TYPES.get(self.output_format, "application/octet-stream")

    def save(self, path: Union[str, Path]) -> Path:
        target = Path(path)
        target.write_bytes(self.audio)
        return target

    def __bytes__(self) -> bytes:
        return self.audio


class TTS:
    """Normalize complete-file TTS calls while reusing provider watermark wrappers.

    ``client`` is the provider's native client or synthesizer. ``api_key`` and
    ``token_id`` configure OfSpectrum watermarking; provider authentication
    remains configured on the native client.
    """

    def __init__(
        self,
        provider: str,
        client: Any,
        *,
        watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None,
        token_id: Optional[str] = None,
        enabled: bool = True,
        transport: str = "pool",
        azure_output_format: Optional[str] = None,
        **encode_options: Any,
    ) -> None:
        normalized = _normalized_name(provider, field_name="provider")
        try:
            canonical = _PROVIDER_ALIASES[normalized]
        except KeyError as exc:
            supported = ", ".join(sorted(set(_PROVIDER_ALIASES.values())))
            raise ValueError("Unsupported TTS provider. Choose one of: " + supported) from exc
        if client is None:
            raise ValueError("client is required")

        common = {
            "watermark_client": watermark_client,
            "api_key": api_key,
            "token_id": token_id,
            "enabled": enabled,
            "transport": transport,
            **encode_options,
        }
        if canonical == "elevenlabs":
            wrapped = Ofspectrum(client, **common)
        elif canonical == "gemini":
            wrapped = Gemini(client, **common)
        elif canonical == "google-cloud-tts":
            wrapped = GoogleCloudTTS(client, **common)
        elif canonical in {"openai", "azure-openai"}:
            wrapped = OpenAITTS(client, **common)
        else:
            wrapped = AzureSpeechTTS(client, output_format=azure_output_format, **common)

        self.provider = canonical
        self.client = wrapped
        self._closed = False

    @property
    def native_client(self) -> Any:
        return self.client.wrapped_client

    @property
    def watermark(self) -> Any:
        return self.client.watermark

    def synthesize(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        output_format: Optional[str] = None,
        language_code: Optional[str] = None,
        endpoint: Optional[str] = None,
        provider_options: Optional[Mapping[str, Any]] = None,
    ) -> TTSResult:
        """Generate and watermark one complete audio result synchronously."""
        response, details = self._invoke(
            text=text,
            model=model,
            voice=voice,
            output_format=output_format,
            language_code=language_code,
            endpoint=endpoint,
            provider_options=provider_options,
            asynchronous=False,
        )
        if inspect.isawaitable(response):
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise TypeError("The provider returned an awaitable; use 'await synthesize_async(...)'")
        return self._complete(response, details)

    async def synthesize_async(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        voice: Optional[str] = None,
        output_format: Optional[str] = None,
        language_code: Optional[str] = None,
        endpoint: Optional[str] = None,
        provider_options: Optional[Mapping[str, Any]] = None,
    ) -> TTSResult:
        """Generate and watermark audio without blocking the caller's event loop."""
        call = functools.partial(
            self._invoke,
            text=text,
            model=model,
            voice=voice,
            output_format=output_format,
            language_code=language_code,
            endpoint=endpoint,
            provider_options=provider_options,
            asynchronous=True,
        )
        loop = asyncio.get_running_loop()
        response, details = await loop.run_in_executor(None, call)
        if inspect.isawaitable(response):
            response = await response
        if self.provider == "elevenlabs" and hasattr(response, "__aiter__"):
            chunks = []
            async for chunk in response:
                raw = _audio_bytes(chunk)
                if raw is None:
                    raise TypeError("ElevenLabs completed audio yielded a non-bytes chunk")
                chunks.append(raw)
            response = b"".join(chunks)
        complete = functools.partial(self._complete, response, details)
        return await loop.run_in_executor(None, complete)

    def _invoke(
        self,
        *,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        language_code: Optional[str],
        endpoint: Optional[str],
        provider_options: Optional[Mapping[str, Any]],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        if self._closed:
            raise RuntimeError("TTS client is closed")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        model = _optional_string(model, field_name="model")
        voice = _optional_string(voice, field_name="voice")
        language_code = _optional_string(language_code, field_name="language_code")
        endpoint = _optional_string(endpoint, field_name="endpoint")
        options = _mapping(provider_options)

        if self.provider == "elevenlabs":
            return self._invoke_elevenlabs(
                text, model, voice, output_format, endpoint, options, asynchronous
            )
        if self.provider == "gemini":
            return self._invoke_gemini(
                text, model, voice, output_format, endpoint, options, asynchronous
            )
        if self.provider == "google-cloud-tts":
            return self._invoke_google_cloud(
                text,
                model,
                voice,
                output_format,
                language_code,
                endpoint,
                options,
                asynchronous,
            )
        if self.provider in {"openai", "azure-openai"}:
            return self._invoke_openai(
                text, model, voice, output_format, endpoint, options, asynchronous
            )
        return self._invoke_azure_speech(
            text,
            model,
            voice,
            output_format,
            language_code,
            endpoint,
            options,
            asynchronous,
        )

    def _invoke_elevenlabs(
        self,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        endpoint: Optional[str],
        options: Dict[str, Any],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        if endpoint not in {None, "speech", "text-to-speech"}:
            raise ValueError("ElevenLabs unified TTS supports endpoint='speech'")
        resolved_voice = options.get("voice_id", voice)
        if not isinstance(resolved_voice, str) or not resolved_voice.strip():
            raise ValueError("voice is required for ElevenLabs")
        resolved_model = options.get("model_id", model or "eleven_multilingual_v2")
        requested_format = _format_name(output_format, "mp3")
        native_format = options.get("output_format")
        if native_format is None:
            native_format = _ELEVENLABS_FORMATS.get(requested_format, requested_format)
        options.setdefault("text", text)
        options.setdefault("voice_id", resolved_voice)
        options.setdefault("model_id", resolved_model)
        options.setdefault("output_format", native_format)
        native_method = self.native_client.text_to_speech.convert
        self._reject_async_method(native_method, asynchronous)
        response = self.client.text_to_speech.convert(**options)
        actual_format = str(_native_value(native_format)).lower().split("_", 1)[0]
        return response, {
            "model": str(resolved_model),
            "voice": str(resolved_voice),
            "output_format": actual_format,
            "call_options": options,
        }

    def _invoke_gemini(
        self,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        endpoint: Optional[str],
        options: Dict[str, Any],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        resolved_model = options.get("model", model or "gemini-3.1-flash-tts-preview")
        resolved_voice = voice or "Kore"
        selected = (
            (endpoint or ("interactions" if "3.1" in str(resolved_model) else "generate-content"))
            .strip()
            .lower()
            .replace("_", "-")
        )
        root = self.client
        native_root = self.native_client
        if asynchronous and hasattr(root, "aio"):
            root = root.aio
            native_root = native_root.aio

        if selected in {"interactions", "interaction"}:
            options.setdefault("model", resolved_model)
            options.setdefault("input", text)
            options.setdefault("response_format", {"type": "audio"})
            options.setdefault("generation_config", {"speech_config": [{"voice": resolved_voice}]})
            self._reject_async_method(native_root.interactions.create, asynchronous)
            response = root.interactions.create(**options)
        elif selected in {"generate-content", "models.generate-content"}:
            options.setdefault("model", resolved_model)
            options.setdefault("contents", text)
            options.setdefault(
                "config",
                {
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {"prebuilt_voice_config": {"voice_name": resolved_voice}}
                    },
                },
            )
            self._reject_async_method(native_root.models.generate_content, asynchronous)
            response = root.models.generate_content(**options)
        else:
            raise ValueError("Gemini endpoint must be 'interactions' or 'generate-content'")
        return response, {
            "model": str(resolved_model),
            "voice": resolved_voice,
            "output_format": _format_name(output_format),
            "call_options": options,
        }

    def _invoke_google_cloud(
        self,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        language_code: Optional[str],
        endpoint: Optional[str],
        options: Dict[str, Any],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        if model is not None:
            raise ValueError("Google Cloud TTS does not use the unified model parameter")
        if endpoint not in {None, "speech", "synthesize-speech"}:
            raise ValueError("Google Cloud TTS supports endpoint='synthesize-speech'")
        requested_format = _format_name(output_format, "mp3")
        try:
            default_encoding = _CLOUD_FORMATS[requested_format]
        except KeyError as exc:
            raise ValueError(
                "Unsupported Google Cloud TTS output format: " + requested_format
            ) from exc

        input_config = _copy_mapping(options.pop("input", None), {"text": text})
        voice_defaults: Dict[str, Any] = {"language_code": language_code or "en-US"}
        if voice is not None:
            voice_defaults["name"] = voice
        voice_config = _copy_mapping(options.pop("voice", None), voice_defaults)
        audio_defaults: Dict[str, Any] = {"audio_encoding": default_encoding}
        if requested_format == "pcm":
            audio_defaults["sample_rate_hertz"] = 24000
        audio_config = _copy_mapping(options.pop("audio_config", None), audio_defaults)
        self._reject_async_method(self.native_client.synthesize_speech, asynchronous)
        response = self.client.synthesize_speech(
            input=input_config, voice=voice_config, audio_config=audio_config, **options
        )
        actual_encoding = _audio_format(_member(audio_config, "audio_encoding"))
        actual_format = {
            "ALAW": "alaw",
            "LINEAR16": "wav",
            "M4A": "m4a",
            "MP3": "mp3",
            "MULAW": "ulaw",
            "OGG_OPUS": "ogg",
            "PCM": "pcm",
        }.get(actual_encoding, requested_format)
        actual_voice = _member(voice_config, "name") or voice
        return response, {
            "model": None,
            "voice": actual_voice,
            "output_format": actual_format,
            "call_options": options,
        }

    def _invoke_openai(
        self,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        endpoint: Optional[str],
        options: Dict[str, Any],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        if self.provider == "azure-openai" and not (model or options.get("model")):
            raise ValueError("model must be the Azure OpenAI TTS deployment name")
        resolved_model = options.get("model", model or "gpt-4o-mini-tts")
        resolved_voice = options.get("voice", voice or "alloy")
        selected = (
            (
                endpoint
                or ("chat" if str(resolved_model).lower().startswith("gpt-audio") else "speech")
            )
            .strip()
            .lower()
            .replace("_", "-")
        )
        requested_format = _format_name(output_format, "mp3")

        if selected in {"speech", "audio.speech"}:
            options.setdefault("model", resolved_model)
            options.setdefault("voice", resolved_voice)
            options.setdefault("input", text)
            options.setdefault("response_format", requested_format)
            self._reject_async_method(self.native_client.audio.speech.create, asynchronous)
            response = self.client.audio.speech.create(**options)
            actual_format = (
                _format_name(str(_native_value(options["response_format"]))) or requested_format
            )
        elif selected in {"chat", "chat-completions", "chat.completions"}:
            if self.provider == "azure-openai":
                raise ValueError(
                    "The Azure OpenAI unified adapter currently supports only the speech endpoint"
                )
            chat_format = "pcm16" if requested_format == "pcm" else requested_format
            options.setdefault("model", resolved_model)
            options.setdefault("messages", [{"role": "user", "content": text}])
            options.setdefault("modalities", ["text", "audio"])
            options.setdefault("audio", {"voice": resolved_voice, "format": chat_format})
            resolved_voice = _member(options["audio"], "voice") or resolved_voice
            self._reject_async_method(self.native_client.chat.completions.create, asynchronous)
            response = self.client.chat.completions.create(**options)
            actual_format = (
                _format_name(str(_native_value(_member(options["audio"], "format"))))
                or requested_format
            )
        else:
            raise ValueError("OpenAI endpoint must be 'speech' or 'chat'")
        return response, {
            "model": str(resolved_model),
            "voice": resolved_voice,
            "output_format": actual_format,
            "call_options": options,
        }

    def _invoke_azure_speech(
        self,
        text: str,
        model: Optional[str],
        voice: Optional[str],
        output_format: Optional[str],
        language_code: Optional[str],
        endpoint: Optional[str],
        options: Dict[str, Any],
        asynchronous: bool,
    ) -> Tuple[Any, Dict[str, Any]]:
        if model is not None:
            raise ValueError("Azure AI Speech does not use the unified model parameter")
        selected = (endpoint or "text").strip().lower().replace("_", "-")
        if selected not in {"text", "speech", "ssml"}:
            raise ValueError("Azure AI Speech endpoint must be 'text' or 'ssml'")
        custom_ssml = options.pop("ssml", None)
        if options:
            names = ", ".join(sorted(options))
            raise TypeError("Unsupported Azure AI Speech provider option(s): " + names)

        requested_format = _format_name(output_format)
        configured_format = None
        try:
            configured_format = _azure_format(self.client._configured_format(b""))
        except ValueError:
            pass
        if requested_format is not None:
            if configured_format is None:
                raise ValueError(
                    "output_format cannot configure an existing Azure Speech synthesizer; "
                    "set it on SpeechConfig and pass azure_output_format to TTS"
                )
            if requested_format != configured_format:
                raise ValueError(
                    "output_format does not match the Azure Speech synthesizer configuration"
                )

        use_ssml = custom_ssml is not None or selected == "ssml" or voice is not None
        if custom_ssml is not None:
            payload = custom_ssml
        elif use_ssml:
            if voice is None:
                raise ValueError("voice or provider_options['ssml'] is required for SSML")
            language = language_code or "en-US"
            payload = (
                '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
                "xml:lang="
                + quoteattr(language)
                + "><voice name="
                + quoteattr(voice)
                + ">"
                + escape(text)
                + "</voice></speak>"
            )
        else:
            payload = text

        method_name = "speak_ssml" if use_ssml else "speak_text"
        async_name = method_name + "_async"
        if asynchronous and hasattr(self.native_client, async_name):
            method = getattr(self.client, async_name)
        else:
            method = getattr(self.client, method_name)
        response = method(payload)
        if asynchronous and callable(getattr(response, "get", None)):
            response = response.get()
        return response, {
            "model": None,
            "voice": voice,
            "output_format": configured_format,
            "call_options": {"ssml": custom_ssml} if custom_ssml is not None else {},
        }

    def _complete(self, response: Any, details: Dict[str, Any]) -> TTSResult:
        audio: Optional[bytes] = None
        actual_format = details.get("output_format")

        if self.provider == "elevenlabs":
            direct = _audio_bytes(response)
            if direct is not None:
                audio = direct
            else:
                try:
                    audio = b"".join(bytes(chunk) for chunk in response)
                except TypeError as exc:
                    raise TypeError("ElevenLabs did not return completed audio bytes") from exc
        elif self.provider == "gemini":
            candidates = _member(response, "candidates")
            if candidates is not None:
                for candidate in candidates or ():
                    content = _member(candidate, "content")
                    for part in _member(content, "parts", ()) or ():
                        blob = _member(part, "inline_data")
                        data = _audio_bytes(_member(blob, "data"))
                        mime = _member(blob, "mime_type")
                        if data is not None and (
                            str(mime).lower().startswith("audio/") or mime is None
                        ):
                            audio = data
                            actual_format = _mime_format(mime)
                            break
                    if audio is not None:
                        break
            else:
                block = _member(response, "output_audio")
                data = _member(block, "data")
                if isinstance(data, str) and data:
                    audio = base64.b64decode(data, validate=True)
                    actual_format = _mime_format(_member(block, "mime_type"))
        elif self.provider == "google-cloud-tts":
            audio = _audio_bytes(_member(response, "audio_content"))
        elif self.provider in {"openai", "azure-openai"}:
            choices = _member(response, "choices")
            if choices is not None:
                for choice in choices or ():
                    data = _member(_member(_member(choice, "message"), "audio"), "data")
                    if isinstance(data, str) and data:
                        audio = base64.b64decode(data, validate=True)
                        break
            else:
                audio = _audio_bytes(response) or _audio_bytes(getattr(response, "content", None))
        else:
            audio = _audio_bytes(getattr(response, "audio_data", None))
            if audio is not None:
                actual_format = _azure_format(self.client._configured_format(audio))

        if not isinstance(audio, bytes) or not audio:
            raise TypeError(self.provider + " did not return completed audio bytes")
        if not actual_format:
            raise ValueError("The provider audio format could not be determined")
        return TTSResult(
            audio=audio,
            provider=self.provider,
            output_format=str(actual_format),
            model=details.get("model"),
            voice=details.get("voice"),
            provider_response=response,
        )

    @staticmethod
    def _reject_async_method(method: Any, asynchronous: bool) -> None:
        if not asynchronous and inspect.iscoroutinefunction(method):
            raise TypeError(
                "The provider client is asynchronous; use 'await synthesize_async(...)'"
            )

    def close(self) -> None:
        if self._closed:
            return
        native_close = getattr(self.native_client, "close", None)
        if inspect.iscoroutinefunction(native_close):
            raise TypeError("The provider has an async close method; use 'await close_async()'")
        result = self.client.close()
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            self.watermark.close()
            raise TypeError("The provider has an async close method; use 'await close_async()'")
        self._closed = True

    async def close_async(self) -> None:
        if self._closed:
            return
        result = self.client.close()
        if inspect.isawaitable(result):
            await result
        self._closed = True

    def __enter__(self) -> "TTS":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    async def __aenter__(self) -> "TTS":
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.close_async()


__all__ = ["TTS", "TTSResult"]
