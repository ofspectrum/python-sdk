"""Shared helpers for complete-file TTS provider wrappers."""

from __future__ import annotations

import asyncio
import functools
import inspect
import re
from typing import Any, Callable, Dict, Optional, Tuple

from .elevenlabs import WatermarkController
from .elevenlabs import _encode_pcm as _encode_pcm


def _member(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _audio_format(value: Any) -> str:
    if hasattr(value, "name"):
        return str(value.name).upper()
    # Cloud TTS proto enums can arrive as integers rather than enum members.
    if isinstance(value, int):
        return {1: "LINEAR16", 2: "MP3", 3: "OGG_OPUS", 5: "MULAW",
                6: "ALAW", 7: "PCM", 8: "M4A"}.get(value, str(value))
    return str(value or "").upper()


def _pcm_spec(mime_type: Optional[str], *, default_rate: int = 24000) -> Tuple[int, int]:
    mime = mime_type or ""
    rate = re.search(r"(?:^|;)\s*rate\s*=\s*(\d+)", mime, re.I)
    channels = re.search(r"(?:^|;)\s*channels\s*=\s*(\d+)", mime, re.I)
    return (int(rate.group(1)) if rate else default_rate,
            int(channels.group(1)) if channels else 1)


class TTSClientProxy:
    """Forward a provider client while replacing selected complete-audio results."""

    def __init__(
        self, target: Any, controller: WatermarkController,
        transform: Callable[[Any, Tuple[Any, ...], Dict[str, Any]], Any],
        path: Tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_controller", controller)
        object.__setattr__(self, "_transform", transform)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_children", {})

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._target, name)
        path = self._path + (name,)
        if callable(value):
            @functools.wraps(value)
            def call(*args: Any, **kwargs: Any) -> Any:
                response = value(*args, **kwargs)
                if self._controller.handles(path):
                    if inspect.isawaitable(response):
                        async def transform_after_await() -> Any:
                            completed = await response
                            loop = asyncio.get_running_loop()
                            transform = functools.partial(
                                self._transform, completed, args, kwargs
                            )
                            return await loop.run_in_executor(None, transform)

                        return transform_after_await()
                    return self._transform(response, args, kwargs)
                return response
            return call
        dotted = ".".join(path) + "."
        if self._is_resource(value) and any(
            method.startswith(dotted) for method in self._controller.audio_methods
        ):
            cached = self._children.get(name)
            if cached is None or cached._target is not value:
                cached = TTSClientProxy(value, self._controller, self._transform, path)
                self._children[name] = cached
            return cached
        return value

    def __dir__(self) -> Any:
        return sorted(set(object.__dir__(self)) | set(dir(self._target)))

    @staticmethod
    def _is_resource(value: Any) -> bool:
        if value is None or isinstance(value, (str, bytes, bytearray, memoryview,
                                               bool, int, float, list, tuple, dict, set)):
            return False
        return not isinstance(value, type)

    @property
    def wrapped_client(self) -> Any:
        return self._target

    def close(self) -> Any:
        close = getattr(self._target, "close", None)
        try:
            result = close() if callable(close) else None
        except BaseException:
            self._controller.close()
            raise
        if inspect.isawaitable(result):
            async def close_after_await() -> Any:
                try:
                    return await result
                finally:
                    self._controller.close()

            return close_after_await()
        self._controller.close()
        return result

    def __enter__(self) -> TTSClientProxy:
        enter = getattr(self._target, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            exit_method = getattr(self._target, "__exit__", None)
            if callable(exit_method):
                return exit_method(exc_type, exc_value, traceback)
            return None
        finally:
            self._controller.close()

    async def __aenter__(self) -> TTSClientProxy:
        enter = getattr(self._target, "__aenter__", None)
        if callable(enter):
            result = enter()
            if inspect.isawaitable(result):
                await result
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Any:
        try:
            exit_method = getattr(self._target, "__aexit__", None)
            if callable(exit_method):
                result = exit_method(exc_type, exc_value, traceback)
                if inspect.isawaitable(result):
                    return await result
                return result
            return None
        finally:
            self._controller.close()
