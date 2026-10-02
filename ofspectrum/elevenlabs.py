"""Transparent ElevenLabs client wrapper with OfSpectrum watermarking.

This module intentionally has no import-time dependency on ``elevenlabs``.
The wrapper uses duck typing so it can follow the generated ElevenLabs client
surface across compatible SDK releases.
"""

import asyncio
import functools
import inspect
import io
import os
import re
import threading
import wave
from collections.abc import AsyncIterable as AsyncIterableABC
from collections.abc import Iterator as IteratorABC
from typing import Any, Dict, Iterable, Iterator, Optional, Set, Tuple

from .client import OfSpectrum
from .exceptions import OfSpectrumError, WatermarkConfigurationError

_UNSET = object()


class _NamedAudio(io.BytesIO):
    def __init__(self, content: bytes, name: str):
        super().__init__(content)
        self.name = name


# These methods return one complete audio file even though the generated
# ElevenLabs Python SDK commonly exposes that file as Iterator[bytes]. Methods
# that return JSON/timestamps/detailed result objects are deliberately absent.
_DEFAULT_COMPLETE_AUDIO_METHODS = {
    "audio_isolation.convert",
    "conversational_ai.conversations.audio.get",
    "history.get_audio",
    "music.compose",
    "music.video_to_music",
    "sound_generation.text_to_sound_effects",
    "speech_to_speech.convert",
    "text_to_dialogue.convert",
    "text_to_sound_effects.convert",
    "text_to_speech.convert",
    "voices.samples.audio.get",
}

_STREAM_METHOD_NAMES = {
    "convert_as_stream",
    "stream",
    "stream_audio",
}

_ENCODE_OPTION_NAMES = {
    "check_watermark",
    "interval",
    "smooth",
    "strength",
    "timeout",
    "verify_and_reencode",
}

_ENCODE_TRANSPORTS = {"pool", "file"}
_RAW_FILE_EXTENSIONS = {".alaw", ".pcm", ".ulaw"}


def _audio_filename(call_kwargs: Dict[str, Any]) -> str:
    output_format = call_kwargs.get("output_format", "mp3_44100_128")
    output_format = getattr(output_format, "value", output_format)
    value = str(output_format or "mp3_44100_128").lower()
    codec = value.split("_", 1)[0]
    extension = {
        "alaw": "alaw",
        "auto": "mp3",
        "mp3": "mp3",
        "opus": "opus",
        "pcm": "pcm",
        "ulaw": "ulaw",
        "wav": "wav",
    }.get(codec, "mp3")
    return "elevenlabs-output." + extension


def _pcm_output_rate(call_kwargs: Dict[str, Any]) -> Optional[int]:
    output_format = call_kwargs.get("output_format")
    output_format = getattr(output_format, "value", output_format)
    match = re.fullmatch(r"pcm_(\d+)", str(output_format or "").lower())
    return int(match.group(1)) if match else None


def _encode_pcm(
    controller: "WatermarkController", audio: bytes, *, filename: str,
    sample_rate: int = 24000, channels: int = 1,
    transport: Optional[str] = None,
) -> bytes:
    """Encode signed 16-bit headerless PCM while preserving its raw shape."""
    if not audio:
        return audio
    if sample_rate <= 0 or channels <= 0 or len(audio) % (2 * channels):
        raise ValueError("PCM audio must have a valid sample rate and complete 16-bit frames")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(audio)
    encoded = controller.encode_bytes(
        buffer.getvalue(), filename=filename + ".wav", transport=transport
    )
    try:
        with wave.open(io.BytesIO(encoded), "rb") as result:
            if (result.getnchannels(), result.getsampwidth(), result.getframerate()) != (
                channels, 2, sample_rate,
            ):
                raise OfSpectrumError(
                    message="Watermark encode changed the PCM format",
                    code="InvalidWatermarkEncodeResponse",
                )
            return result.readframes(result.getnframes())
    except (wave.Error, EOFError) as exc:
        raise OfSpectrumError(
            message="Watermark encode did not return PCM-compatible WAV audio",
            code="InvalidWatermarkEncodeResponse",
        ) from exc


def _all_byte_chunks(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(
        isinstance(chunk, (bytes, bytearray, memoryview)) for chunk in value
    )


def _is_stream_method_name(name: str) -> bool:
    return (
        name in _STREAM_METHOD_NAMES
        or name.startswith("stream_")
        or name.endswith("_stream")
        or "_stream_" in name
    )


class WatermarkController:
    """Configuration and encode operations for an :class:`Ofspectrum` wrapper.

    Configuration is read as a snapshot for every encode, making calls safe to
    use concurrently. Reconfiguring while a call is in flight affects only
    subsequent calls.
    """

    def __init__(
        self,
        *,
        client: Optional[Any] = None,
        api_key: Optional[str] = None,
        token_id: Optional[str] = None,
        enabled: bool = True,
        transport: str = "pool",
        encode_options: Optional[Dict[str, Any]] = None,
        audio_methods: Optional[Iterable[str]] = None,
    ) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        if api_key is not None and (
            not isinstance(api_key, str) or not api_key.strip()
        ):
            raise ValueError("api_key must be a non-empty string or None")
        if token_id is not None and (
            not isinstance(token_id, str) or not token_id.strip()
        ):
            raise ValueError("token_id must be a non-empty string or None")
        self._lock = threading.RLock()
        self._client = client
        self._owns_client = client is None
        self._api_key = api_key.strip() if api_key else os.getenv("OFSPECTRUM_API_KEY")
        self._token_id = token_id.strip() if token_id else os.getenv("OFSPECTRUM_TOKEN_ID")
        self._enabled = enabled
        self._transport = self._normalize_transport(transport)
        self._encode_options: Dict[str, Any] = {}
        method_source = (
            _DEFAULT_COMPLETE_AUDIO_METHODS if audio_methods is None else audio_methods
        )
        self._audio_methods: Set[str] = {
            self._normalize_method_path(path) for path in method_source
        }
        if encode_options:
            self._set_encode_options(encode_options)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def token_id(self) -> Optional[str]:
        with self._lock:
            return self._token_id

    @property
    def audio_methods(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._audio_methods))

    @property
    def transport(self) -> str:
        with self._lock:
            return self._transport

    def config(
        self,
        *,
        enabled: Any = _UNSET,
        token_id: Any = _UNSET,
        api_key: Any = _UNSET,
        client: Any = _UNSET,
        transport: Any = _UNSET,
        **encode_options: Any,
    ) -> "WatermarkController":
        """Update watermark settings and return this controller.

        Supported encode options currently mirror the safe subset of
        ``OfSpectrum.audio.encode``: ``strength``, ``smooth``, ``interval``,
        ``timeout``, ``check_watermark``, and ``verify_and_reencode``.
        ``transport`` accepts ``"pool"`` (the default) or ``"file"``. Pool
        transport reuses persistent WebSocket connections across calls.
        Persistence and response-format options are fixed so the wrapper always
        receives encoded bytes and does not create storage as a side effect.
        """
        with self._lock:
            if enabled is not _UNSET:
                if not isinstance(enabled, bool):
                    raise ValueError("enabled must be a boolean")
                self._enabled = enabled
            if token_id is not _UNSET:
                if token_id is not None and (
                    not isinstance(token_id, str) or not token_id.strip()
                ):
                    raise ValueError("token_id must be a non-empty string or None")
                self._token_id = token_id.strip() if token_id else None
            if api_key is not _UNSET:
                if api_key is not None and (
                    not isinstance(api_key, str) or not api_key.strip()
                ):
                    raise ValueError("api_key must be a non-empty string or None")
                self._replace_owned_client(None)
                self._api_key = api_key.strip() if api_key else None
                self._owns_client = True
            if client is not _UNSET:
                self._replace_owned_client(client)
                self._owns_client = client is None
            if transport is not _UNSET:
                self._transport = self._normalize_transport(transport)
            self._set_encode_options(encode_options)
        return self

    def register_audio_method(self, path: str) -> "WatermarkController":
        """Register another dotted ElevenLabs method returning a complete file."""
        normalized = self._normalize_method_path(path)
        with self._lock:
            self._audio_methods.add(normalized)
        return self

    def unregister_audio_method(self, path: str) -> "WatermarkController":
        normalized = self._normalize_method_path(path)
        with self._lock:
            self._audio_methods.discard(normalized)
        return self

    def handles(self, path: Tuple[str, ...]) -> bool:
        if not path or _is_stream_method_name(path[-1]) or "with_raw_response" in path:
            return False
        dotted = ".".join(path)
        with self._lock:
            return self._enabled and dotted in self._audio_methods

    def transform(self, response: Any, call_kwargs: Dict[str, Any]) -> Any:
        """Watermark a supported complete-audio response, preserving its shape."""
        filename = _audio_filename(call_kwargs)
        pcm_rate = _pcm_output_rate(call_kwargs)

        def encode(audio: bytes) -> bytes:
            if pcm_rate is not None:
                return _encode_pcm(
                    self, audio, filename="elevenlabs-output", sample_rate=pcm_rate
                )
            return self.encode_bytes(audio, filename=filename)

        if isinstance(response, bytes):
            return encode(response)
        if isinstance(response, bytearray):
            return bytearray(encode(bytes(response)))
        if isinstance(response, memoryview):
            return memoryview(encode(response.tobytes()))
        if _all_byte_chunks(response):
            encoded = encode(b"".join(bytes(chunk) for chunk in response))
            return type(response)([encoded])
        if isinstance(response, AsyncIterableABC):
            return self._transform_async_iterator(response, call_kwargs)
        if isinstance(response, IteratorABC):
            return self._transform_iterator(response, encode)
        # JSON, metadata models, job IDs, status objects, and unknown response
        # types retain their exact identity.
        return response

    def encode_bytes(
        self, audio: bytes, *, filename: str = "elevenlabs-output.mp3",
        transport: Optional[str] = None,
    ) -> bytes:
        """Encode already-complete audio bytes using the current configuration."""
        if not isinstance(audio, bytes):
            raise TypeError("audio must be bytes")
        if not audio:
            return audio
        client, token_id, options, configured_transport = self._encode_snapshot()
        resolved_transport = (
            configured_transport if transport is None else self._normalize_transport(transport)
        )
        source = _NamedAudio(audio, filename)
        stream_encode = getattr(client.audio, "stream_encode", None)
        interval = options.get("interval", 0.0)
        pool_compatible = (
            resolved_transport == "pool"
            and callable(stream_encode)
            and not isinstance(interval, bool)
            and interval == 0.0
            and options.get("check_watermark", False) is False
            and not any(filename.lower().endswith(suffix) for suffix in _RAW_FILE_EXTENSIONS)
        )
        if pool_compatible:
            stream_options = dict(options)
            stream_options["interval"] = 0.0
            stream_options["check_watermark"] = False
            result = stream_encode(
                source,
                token_id,
                save_file=False,
                keep_original=False,
                response_format="stream",
                **stream_options,
            )
        else:
            result = client.audio.encode(
                source,
                token_id,
                save_file=False,
                keep_original=False,
                response_format="stream",
                original_filename=filename,
                **options,
            )
        encoded = getattr(result, "audio_bytes", None)
        if not isinstance(encoded, bytes) or not encoded:
            raise OfSpectrumError(
                message="Watermark encode did not return audio bytes",
                code="InvalidWatermarkEncodeResponse",
            )
        return encoded

    def close(self) -> None:
        with self._lock:
            self._replace_owned_client(None)

    def _transform_iterator(
        self, response: Iterator, encode: Any,
    ) -> Iterator[bytes]:
        def generate() -> Iterator[bytes]:
            chunks = []
            try:
                for chunk in response:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError(
                            "ElevenLabs complete-audio response yielded a non-bytes chunk"
                        )
                    chunks.append(bytes(chunk))
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            audio = b"".join(chunks)
            if audio:
                yield encode(audio)

        return generate()

    async def _transform_async_iterator(
        self, response: Any, call_kwargs: Dict[str, Any],
    ) -> Any:
        chunks = []
        try:
            async for chunk in response:
                if not isinstance(chunk, (bytes, bytearray, memoryview)):
                    raise TypeError(
                        "ElevenLabs complete-audio response yielded a non-bytes chunk"
                    )
                chunks.append(bytes(chunk))
        finally:
            close = getattr(response, "aclose", None)
            if callable(close):
                result = close()
                if inspect.isawaitable(result):
                    await result
        audio = b"".join(chunks)
        if audio:
            loop = asyncio.get_running_loop()
            encode = functools.partial(self.transform, audio, call_kwargs)
            yield await loop.run_in_executor(None, encode)

    def _encode_snapshot(self) -> Tuple[Any, str, Dict[str, Any], str]:
        with self._lock:
            if not self._enabled:
                raise WatermarkConfigurationError("Watermarking is disabled")
            if not self._token_id:
                raise WatermarkConfigurationError(
                    "A watermark token_id is required; set OFSPECTRUM_TOKEN_ID "
                    "or call client.watermark.config(token_id=...)"
                )
            if self._client is None:
                if not self._api_key:
                    raise WatermarkConfigurationError(
                        "An OfSpectrum API key is required; set OFSPECTRUM_API_KEY "
                        "or call client.watermark.config(api_key=...)"
                    )
                self._client = OfSpectrum(api_key=self._api_key)
                self._owns_client = True
            return (
                self._client,
                self._token_id,
                dict(self._encode_options),
                self._transport,
            )

    def _replace_owned_client(self, replacement: Optional[Any]) -> None:
        previous = self._client
        if previous is not None and self._owns_client and previous is not replacement:
            close = getattr(previous, "close", None)
            if callable(close):
                close()
        self._client = replacement

    def _set_encode_options(self, options: Dict[str, Any]) -> None:
        unsupported = set(options) - _ENCODE_OPTION_NAMES
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise TypeError("Unsupported watermark encode option(s): " + names)
        self._encode_options.update(options)

    @staticmethod
    def _normalize_method_path(path: str) -> str:
        if not isinstance(path, str) or not path.strip(". "):
            raise ValueError("path must be a non-empty dotted method path")
        normalized = path.strip(". ")
        if _is_stream_method_name(normalized.split(".")[-1]):
            raise ValueError("streaming methods cannot be registered for watermarking")
        return normalized

    @staticmethod
    def _normalize_transport(transport: Any) -> str:
        if not isinstance(transport, str) or transport.strip().lower() not in _ENCODE_TRANSPORTS:
            raise ValueError("transport must be 'pool' or 'file'")
        return transport.strip().lower()


class _ElevenLabsProxy:
    def __init__(
        self,
        target: Any,
        controller: WatermarkController,
        path: Tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_controller", controller)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_children", {})

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        value = getattr(target, name)
        path = object.__getattribute__(self, "_path") + (name,)
        controller = object.__getattribute__(self, "_controller")

        if callable(value):
            @functools.wraps(value)
            def call(*args: Any, **kwargs: Any) -> Any:
                response = value(*args, **kwargs)
                if controller.handles(path):
                    if inspect.isawaitable(response):
                        async def transform_after_await() -> Any:
                            completed = await response
                            loop = asyncio.get_running_loop()
                            transform = functools.partial(
                                controller.transform, completed, kwargs
                            )
                            return await loop.run_in_executor(None, transform)

                        return transform_after_await()
                    return controller.transform(response, kwargs)
                return response

            return call

        if self._is_resource(value):
            children = object.__getattribute__(self, "_children")
            cached = children.get(name)
            if cached is None or object.__getattribute__(cached, "_target") is not value:
                cached = _ElevenLabsProxy(value, controller, path)
                children[name] = cached
            return cached
        return value

    def __dir__(self) -> Any:
        return sorted(set(object.__dir__(self)) | set(dir(self._target)))

    @staticmethod
    def _is_resource(value: Any) -> bool:
        if value is None or isinstance(
            value, (str, bytes, bytearray, memoryview, bool, int, float, list, tuple, dict, set)
        ):
            return False
        module = type(value).__module__
        if module == "elevenlabs" or module.startswith("elevenlabs."):
            return True
        try:
            return any(
                not name.startswith("_") and callable(getattr(value, name, None))
                for name in dir(value)
            )
        except Exception:
            return False


class Ofspectrum(_ElevenLabsProxy):
    """Wrap a synchronous or asynchronous ElevenLabs client and watermark audio.

    The original client remains accessible through ``wrapped_client``. The
    wrapper is intentionally named ``Ofspectrum`` to support the integration
    syntax without changing the existing ``OfSpectrum`` API client.
    """

    def __init__(
        self,
        elevenlabs_client: Any,
        *,
        watermark_client: Optional[Any] = None,
        api_key: Optional[str] = None,
        token_id: Optional[str] = None,
        enabled: bool = True,
        transport: str = "pool",
        audio_methods: Optional[Iterable[str]] = None,
        **encode_options: Any,
    ) -> None:
        if elevenlabs_client is None:
            raise ValueError("elevenlabs_client is required")
        controller = WatermarkController(
            client=watermark_client,
            api_key=api_key,
            token_id=token_id,
            enabled=enabled,
            transport=transport,
            encode_options=encode_options,
            audio_methods=audio_methods,
        )
        super().__init__(elevenlabs_client, controller)
        object.__setattr__(self, "watermark", controller)

    @property
    def wrapped_client(self) -> Any:
        return object.__getattribute__(self, "_target")

    def close(self) -> None:
        try:
            close = getattr(self.wrapped_client, "close", None)
            if callable(close):
                close()
        finally:
            self.watermark.close()

    def __enter__(self) -> "Ofspectrum":
        enter = getattr(self.wrapped_client, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            exit_method = getattr(self.wrapped_client, "__exit__", None)
            if callable(exit_method):
                return exit_method(exc_type, exc_value, traceback)
            return None
        finally:
            self.watermark.close()


__all__ = [
    "Ofspectrum",
    "WatermarkConfigurationError",
    "WatermarkController",
]
