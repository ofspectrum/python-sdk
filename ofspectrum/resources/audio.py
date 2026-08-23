"""
Audio resource for watermark encoding and decoding
"""

import json
import math
import socket
import threading
import time
import uuid
import weakref
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import deque
from typing import Any, BinaryIO, Iterable, Optional, Union
from urllib.parse import urlsplit, urlunsplit

from ..exceptions import OfSpectrumError, raise_for_error
from ..media import (
    CANONICAL_SAMPLE_RATE,
    decode_canonical_interleaved_pcm,
    interleave_pcm_f32le,
    read_audio_bytes,
    rebuild_encoded_media,
    split_interleaved_pcm_f32le,
    suggested_filename,
)
from ..models.audio import DecodeResult, EncodeResult, StreamingEncodeResult
from .base import BaseResource


def _start_deadline_watchdog(
    websocket: Any,
    deadline: Optional[float],
) -> threading.Event:
    stop = threading.Event()
    if deadline is None:
        return stop

    def _watch() -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0 or not stop.wait(timeout=remaining):
            _abort_websocket_transport(websocket)

    threading.Thread(
        target=_watch,
        name="ofspectrum-stream-deadline",
        daemon=True,
    ).start()
    return stop


def _abort_websocket_transport(websocket: Any) -> None:
    transport_socket = getattr(websocket, "socket", None)
    if transport_socket is not None:
        try:
            transport_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            transport_socket.close()
        except Exception:
            pass
        return
    close = getattr(websocket, "close", None)
    if close is not None:
        try:
            close()
        except Exception:
            pass


class _StreamPoolSlot:
    """One exclusive persistent WebSocket connection in a stream pool."""

    def __init__(self) -> None:
        self.slot_id = str(uuid.uuid4())
        self.websocket: Any = None
        self.lock = threading.Lock()
        self.last_ok_monotonic = 0.0


class StreamEncodePool:
    """Thread-safe pool of persistent stream-encode WebSocket connections."""

    _PCM_CHUNK_FRAMES = 96_000
    _CONNECT_TIMEOUT_SECONDS = 3.0
    _PROBE_GRACE_SECONDS = 5.0

    def __init__(
        self,
        resource: "AudioResource",
        *,
        token_id: str,
        connections: int,
        sample_rate: int,
        channels: int,
        strength: float,
        smooth: bool,
        verify_and_reencode: bool,
        timeout: Optional[float],
    ) -> None:
        self._resource = resource
        self._token_id = token_id
        self._sample_rate = sample_rate
        self._channels = channels
        self._strength = strength
        self._smooth = smooth
        self._verify_and_reencode = verify_and_reencode
        self._timeout = timeout
        self._slots = [_StreamPoolSlot() for _ in range(connections)]
        self._idle = deque(self._slots)
        self._idle_lock = threading.Lock()
        self._idle_ready = threading.Condition(self._idle_lock)
        self._state_lock = threading.Lock()
        self._closed = False

    def __enter__(self) -> "StreamEncodePool":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        with self._state_lock:
            return self._closed

    def close(self) -> None:
        """Close every created connection and prevent future operations."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        with self._idle_ready:
            self._idle_ready.notify_all()

        for slot in self._slots:
            acquired = slot.lock.acquire(timeout=0.1)
            if not acquired:
                if slot.websocket is not None:
                    _abort_websocket_transport(slot.websocket)
                acquired = slot.lock.acquire(timeout=self._CONNECT_TIMEOUT_SECONDS + 0.5)
            if not acquired:
                continue
            try:
                if slot.websocket is None:
                    continue
                graceful = False
                try:
                    slot.websocket.send(json.dumps({"type": "close"}))
                    response = slot.websocket.recv(timeout=2.0)
                    if isinstance(response, str):
                        event = json.loads(response)
                        graceful = isinstance(event, dict) and event.get("type") == "closed"
                except Exception:
                    pass
                if graceful:
                    try:
                        slot.websocket.close()
                    except Exception:
                        _abort_websocket_transport(slot.websocket)
                else:
                    _abort_websocket_transport(slot.websocket)
                slot.websocket = None
            finally:
                slot.lock.release()

    def encode(
        self,
        audio: Union[str, Path, BinaryIO, bytes],
        *,
        timeout: Optional[float] = None,
    ) -> EncodeResult:
        """Encode a file or bytes using a reusable stream connection."""
        if self._sample_rate != CANONICAL_SAMPLE_RATE:
            raise ValueError("stream pool file encode requires sample_rate=48000")
        source = read_audio_bytes(audio)
        pcm, info = decode_canonical_interleaved_pcm(source)
        channel_count = max(1, int(info.channels))
        if channel_count != self._channels:
            raise ValueError(
                "audio channels must match the stream pool channels "
                f"({self._channels})"
            )

        streamed = self._encode_pcm(pcm, timeout=timeout)
        rebuilt = rebuild_encoded_media(streamed.encoded_pcm, info)
        duration = int(round(streamed.audio_duration))
        if duration <= 0 and info.duration_seconds > 0:
            duration = max(1, int(round(info.duration_seconds)))
        return EncodeResult.from_bytes(
            audio_bytes=rebuilt,
            audio_duration=duration,
            token_id=self._token_id,
            file_name=suggested_filename(info),
            content_type=info.content_type,
            quality_warning=streamed.quality_warning,
        )

    def _encode_pcm(
        self,
        pcm: bytes,
        *,
        timeout: Optional[float],
    ) -> StreamingEncodeResult:
        if not pcm or len(pcm) % (4 * self._channels):
            raise OfSpectrumError(message="encoded PCM is invalid")
        operation_timeout = self._timeout if timeout is None else timeout
        if operation_timeout is not None and (
            isinstance(operation_timeout, bool)
            or not math.isfinite(operation_timeout)
            or operation_timeout <= 0.0
        ):
            raise ValueError("timeout must be a finite positive number or None")
        deadline = None if operation_timeout is None else time.monotonic() + operation_timeout
        slot = self._borrow(deadline)
        try:
            with slot.lock:
                if self.closed:
                    raise OfSpectrumError(
                        message="Streaming pool is closed",
                        code="StreamingPoolClosed",
                    )
                return self._run_operation(slot, pcm, deadline)
        finally:
            self._release(slot)

    def _borrow(self, deadline: Optional[float]) -> _StreamPoolSlot:
        if self.closed:
            raise OfSpectrumError(message="Streaming pool is closed", code="StreamingPoolClosed")
        while True:
            with self._idle_ready:
                if self.closed:
                    raise OfSpectrumError(
                        message="Streaming pool is closed",
                        code="StreamingPoolClosed",
                    )
                slot = self._pop_idle_slot()
                if slot is not None:
                    return slot
                if deadline is None:
                    self._idle_ready.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise OfSpectrumError(
                        message="Streaming pool timed out waiting for a connection",
                        code="StreamingPoolTimeout",
                    )
                if not self._idle_ready.wait(timeout=remaining):
                    raise OfSpectrumError(
                        message="Streaming pool timed out waiting for a connection",
                        code="StreamingPoolTimeout",
                    )

    def _pop_idle_slot(self) -> Optional[_StreamPoolSlot]:
        for index, slot in enumerate(self._idle):
            if slot.websocket is not None:
                del self._idle[index]
                return slot
        if self._idle:
            return self._idle.popleft()
        return None

    def _release(self, slot: _StreamPoolSlot) -> None:
        with self._idle_ready:
            if slot.websocket is not None:
                self._idle.appendleft(slot)
            else:
                self._idle.append(slot)
            self._idle_ready.notify()

    def _run_operation(
        self,
        slot: _StreamPoolSlot,
        pcm: bytes,
        deadline: Optional[float],
    ) -> StreamingEncodeResult:
        if self.closed:
            raise OfSpectrumError(
                message="Streaming pool is closed",
                code="StreamingPoolClosed",
            )
        encoded_chunks = []
        events = []
        try:
            self._ensure_connection(slot, deadline)
            operation_id = str(uuid.uuid4())
            reconnect_required = self._exchange_operation(
                slot.websocket,
                pcm,
                operation_id,
                deadline,
                encoded_chunks,
                events,
            )
            if not encoded_chunks:
                raise OfSpectrumError(
                    message="Streaming encode returned no audio",
                    code="StreamingEncodeEmpty",
                )
            result = StreamingEncodeResult(
                encoded_pcm=b"".join(encoded_chunks),
                token_id=self._token_id,
                sample_rate=self._sample_rate,
                channels=self._channels,
                events=events,
                quality_warning=any(
                    event.get("type") == "quality_warning"
                    or bool(event.get("quality_warning"))
                    for event in events
                    if isinstance(event, dict)
                ),
            )
            if reconnect_required:
                self._discard_connection(slot)
            else:
                slot.last_ok_monotonic = time.monotonic()
            return result
        except Exception as exc:
            self._discard_connection(slot)
            if self.closed:
                raise OfSpectrumError(
                    message="Streaming pool is closed",
                    code="StreamingPoolClosed",
                ) from exc
            if encoded_chunks:
                raise OfSpectrumError(
                    message="Streaming pool connection closed after partial output",
                    code="StreamingPoolIncomplete",
                ) from exc
            if isinstance(exc, OfSpectrumError):
                raise
            raise OfSpectrumError(
                message="Streaming pool connection closed before output",
                code="StreamingPoolUnavailable",
            ) from exc

    def _exchange_operation(
        self,
        websocket: Any,
        pcm: bytes,
        operation_id: str,
        deadline: Optional[float],
        encoded_chunks: list,
        events: list,
    ) -> bool:
        # websockets.sync is not thread-safe. Send and drain on one thread so
        # live first-window output cannot race the upload.
        stop_watchdog = _start_deadline_watchdog(websocket, deadline)
        try:
            chunk_bytes = self._PCM_CHUNK_FRAMES * self._channels * 4
            for offset in range(0, len(pcm), chunk_bytes):
                if self.closed:
                    raise OfSpectrumError(
                        message="Streaming pool is closed",
                        code="StreamingPoolClosed",
                    )
                websocket.send(pcm[offset : offset + chunk_bytes])
                if self._drain_pool_output(
                    websocket,
                    operation_id,
                    deadline,
                    encoded_chunks,
                    events,
                    block=False,
                ):
                    return False
            websocket.send(json.dumps({"type": "flush", "operation_id": operation_id}))
            return self._receive_flush(
                websocket,
                operation_id,
                deadline,
                encoded_chunks,
                events,
            )
        finally:
            stop_watchdog.set()

    def _ensure_connection(self, slot: _StreamPoolSlot, deadline: Optional[float]) -> None:
        if slot.websocket is not None:
            age = time.monotonic() - slot.last_ok_monotonic
            if age < self._PROBE_GRACE_SECONDS:
                return
            try:
                self._probe_connection(slot.websocket, deadline)
                return
            except Exception:
                self._discard_connection(slot)
        try:
            from websockets.sync.client import connect
        except Exception as exc:
            raise OfSpectrumError(
                message="Streaming encode requires the 'websockets' package",
                code="MissingDependency",
            ) from exc

        headers = {
            "Authorization": f"Bearer {self._resource._client._api_key}",
            "X-OfSpectrum-Stream-Slot": slot.slot_id,
        }
        url = self._resource._websocket_url("/audio/watermark/ws/encode")
        while True:
            websocket = None
            try:
                open_timeout = min(
                    float(self._resource._client._timeout),
                    self._CONNECT_TIMEOUT_SECONDS,
                )
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise OfSpectrumError(
                            message="Streaming pool operation timed out",
                            code="StreamingPoolTimeout",
                        )
                    open_timeout = min(open_timeout, remaining)
                try:
                    websocket = connect(
                        url,
                        additional_headers=headers,
                        open_timeout=open_timeout,
                        ping_interval=20.0,
                        ping_timeout=20.0,
                        close_timeout=2.0,
                    )
                except TypeError:
                    websocket = connect(
                        url,
                        extra_headers=headers,
                        open_timeout=open_timeout,
                        ping_interval=20.0,
                        ping_timeout=20.0,
                        close_timeout=2.0,
                    )

                slot.websocket = websocket
                if self.closed:
                    raise OfSpectrumError(
                        message="Streaming pool is closed",
                        code="StreamingPoolClosed",
                    )

                admission_timeout = 0.2
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise OfSpectrumError(
                            message="Streaming pool operation timed out",
                            code="StreamingPoolTimeout",
                        )
                    admission_timeout = min(admission_timeout, remaining)
                try:
                    admission_message = websocket.recv(timeout=admission_timeout)
                except TimeoutError:
                    admission_message = None
                if admission_message is not None:
                    admission = self._control_event(admission_message)
                    if admission.get("type") == "error":
                        if admission.get("code") == "AudioStreamConnectionTakeoverPending":
                            self._discard_socket(websocket)
                            websocket = None
                            self._wait_for_takeover(admission, deadline)
                            continue
                        raise OfSpectrumError(
                            message="Streaming pool connection is not available",
                            code=str(admission.get("code") or "StreamingPoolUnavailable"),
                        )
                    if admission.get("type") != "admitted":
                        raise OfSpectrumError(
                            message="Streaming pool received an invalid admission response",
                            code="StreamingPoolProtocol",
                        )

                websocket.send(
                    json.dumps(
                        {
                            "type": "config",
                            "config": {
                                "token_id": self._token_id,
                                "sample_rate": self._sample_rate,
                                "channels": self._channels,
                                "strength": self._strength,
                                "smooth": self._smooth,
                                "verify_and_reencode": self._verify_and_reencode,
                            },
                        }
                    )
                )
                ready = self._control_event(self._recv(websocket, deadline))
                if ready.get("type") == "error":
                    if ready.get("code") == "AudioStreamConnectionTakeoverPending":
                        self._discard_socket(websocket)
                        websocket = None
                        self._wait_for_takeover(ready, deadline)
                        continue
                    raise OfSpectrumError(
                        message="Streaming pool connection is not available",
                        code=str(ready.get("code") or "StreamingPoolUnavailable"),
                    )
                if ready.get("type") != "ready":
                    raise OfSpectrumError(
                        message="Streaming pool did not receive a ready event",
                        code="StreamingPoolProtocol",
                    )
                return
            except Exception:
                if websocket is not None:
                    self._discard_socket(websocket)
                if slot.websocket is websocket:
                    slot.websocket = None
                raise

    @staticmethod
    def _probe_connection(websocket: Any, deadline: Optional[float]) -> None:
        ping = getattr(websocket, "ping", None)
        if ping is None:
            return
        waiter = ping()
        wait = getattr(waiter, "wait", None)
        if wait is None:
            return
        timeout = 1.0
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise TimeoutError("stream operation deadline expired")
            timeout = min(timeout, remaining)
        if wait(timeout=timeout) is False:
            raise TimeoutError("stream connection health check timed out")

    @staticmethod
    def _control_event(message: Any) -> dict:
        if not isinstance(message, str):
            raise OfSpectrumError(
                message="Streaming pool received an invalid control response",
                code="StreamingPoolProtocol",
            )
        try:
            event = json.loads(message)
        except (TypeError, ValueError) as exc:
            raise OfSpectrumError(
                message="Streaming pool received an invalid control response",
                code="StreamingPoolProtocol",
            ) from exc
        if not isinstance(event, dict):
            raise OfSpectrumError(
                message="Streaming pool received an invalid control response",
                code="StreamingPoolProtocol",
            )
        return event

    @staticmethod
    def _discard_socket(websocket: Any) -> None:
        _abort_websocket_transport(websocket)

    @staticmethod
    def _wait_for_takeover(event: dict, deadline: Optional[float]) -> None:
        retry_seconds = max(
            0.25,
            min(float(event.get("retry_after_ms") or 1000) / 1000.0, 2.0),
        )
        if deadline is not None and time.monotonic() + retry_seconds > deadline:
            raise OfSpectrumError(
                message="Streaming pool timed out waiting for the previous connection",
                code="StreamingPoolTimeout",
            )
        time.sleep(retry_seconds)

    @staticmethod
    def _recv(websocket: Any, deadline: Optional[float]) -> Any:
        if deadline is None:
            return websocket.recv()
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            raise OfSpectrumError(
                message="Streaming pool operation timed out",
                code="StreamingPoolTimeout",
            )
        try:
            return websocket.recv(timeout=remaining)
        except TimeoutError as exc:
            raise OfSpectrumError(
                message="Streaming pool operation timed out",
                code="StreamingPoolTimeout",
            ) from exc

    def _poll_recv(self, websocket: Any, deadline: Optional[float]) -> Any:
        if deadline is not None and time.monotonic() >= deadline:
            raise OfSpectrumError(
                message="Streaming pool operation timed out",
                code="StreamingPoolTimeout",
            )
        timeout = 0.02
        if deadline is not None:
            timeout = min(timeout, max(0.0, deadline - time.monotonic()))
        try:
            return websocket.recv(timeout=timeout)
        except TimeoutError:
            return None

    def _apply_pool_message(
        self,
        message: Any,
        operation_id: str,
        encoded_chunks: list,
        events: list,
    ) -> Optional[bool]:
        if isinstance(message, bytes):
            encoded_chunks.append(message)
            return None
        if not isinstance(message, str):
            return None
        try:
            event = json.loads(message)
        except (TypeError, ValueError):
            event = {"type": "message"}
        if not isinstance(event, dict):
            return None
        events.append(event)
        event_type = event.get("type")
        if event_type in {"error", "quota_exceeded"}:
            raise OfSpectrumError(
                message="Streaming pool encode failed",
                code="StreamingPoolEncodeError",
            )
        if event_type != "flush_done":
            return None
        completed_id = event.get("operation_id")
        if completed_id is not None and completed_id != operation_id:
            raise OfSpectrumError(
                message="Streaming pool received an invalid flush response",
                code="StreamingPoolProtocol",
            )
        return bool(event.get("reconnect_required"))

    def _drain_pool_output(
        self,
        websocket: Any,
        operation_id: str,
        deadline: Optional[float],
        encoded_chunks: list,
        events: list,
        *,
        block: bool,
    ) -> Optional[bool]:
        while True:
            message = (
                self._recv(websocket, deadline)
                if block
                else self._poll_recv(websocket, deadline)
            )
            if message is None:
                return None
            finished = self._apply_pool_message(
                message,
                operation_id,
                encoded_chunks,
                events,
            )
            if finished is not None:
                return finished

    def _receive_flush(
        self,
        websocket: Any,
        operation_id: str,
        deadline: Optional[float],
        encoded_chunks: list,
        events: list,
    ) -> bool:
        finished = self._drain_pool_output(
            websocket,
            operation_id,
            deadline,
            encoded_chunks,
            events,
            block=True,
        )
        if finished is None:
            raise OfSpectrumError(
                message="Streaming pool operation timed out",
                code="StreamingPoolTimeout",
            )
        return finished

    @staticmethod
    def _discard_connection(slot: _StreamPoolSlot) -> None:
        if slot.websocket is not None:
            _abort_websocket_transport(slot.websocket)
            slot.websocket = None
        slot.last_ok_monotonic = 0.0


class AudioResource(BaseResource):
    """Resource for audio watermark operations"""

    MAX_UPLOAD_BYTES = 100 * 1024 * 1024

    _AUTO_STREAM_POOL_CONNECTIONS = 4

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self._stream_pools = weakref.WeakSet()
        self._auto_stream_pools: dict[tuple[Any, ...], StreamEncodePool] = {}
        self._stream_pools_lock = threading.Lock()

    def _auto_stream_pool(
        self,
        *,
        token_id: str,
        sample_rate: int,
        channels: int,
        strength: float,
        smooth: bool,
        verify_and_reencode: bool,
        timeout: Optional[float],
    ) -> StreamEncodePool:
        key = (
            token_id,
            sample_rate,
            channels,
            strength,
            smooth,
            verify_and_reencode,
        )
        with self._stream_pools_lock:
            pool = self._auto_stream_pools.get(key)
            if pool is None or pool.closed:
                pool = StreamEncodePool(
                    self,
                    token_id=token_id,
                    connections=self._AUTO_STREAM_POOL_CONNECTIONS,
                    sample_rate=sample_rate,
                    channels=channels,
                    strength=strength,
                    smooth=smooth,
                    verify_and_reencode=verify_and_reencode,
                    timeout=timeout,
                )
                self._auto_stream_pools[key] = pool
                self._stream_pools.add(pool)
            return pool

    def open_stream_pool(
        self,
        token_id: str,
        *,
        connections: int = 2,
        sample_rate: int = CANONICAL_SAMPLE_RATE,
        channels: int = 1,
        strength: float = 1.0,
        smooth: bool = True,
        verify_and_reencode: bool = True,
        timeout: Optional[float] = None,
    ) -> StreamEncodePool:
        """Create a thread-safe persistent pool for repeated stream encodes.

        Each connection has a stable opaque slot identifier. The pool config is
        fixed at creation time; ``encode()`` accepts file paths, file objects,
        or bytes with the same number of audio channels as the pool.
        """
        if not token_id:
            raise ValueError("token_id is required")
        if (
            isinstance(connections, bool)
            or not isinstance(connections, int)
            or not 1 <= connections <= 32
        ):
            raise ValueError("connections must be between 1 and 32")
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")
        if isinstance(channels, bool) or not isinstance(channels, int) or not 1 <= channels <= 8:
            raise ValueError("channels must be between 1 and 8")
        if isinstance(strength, bool) or not math.isfinite(strength) or not 0.1 <= strength <= 2.0:
            raise ValueError("strength must be a finite number between 0.1 and 2.0")
        if not isinstance(smooth, bool):
            raise ValueError("smooth must be a boolean")
        if not isinstance(verify_and_reencode, bool):
            raise ValueError("verify_and_reencode must be a boolean")
        if timeout is not None and (
            isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0.0
        ):
            raise ValueError("timeout must be a finite positive number or None")

        pool = StreamEncodePool(
            self,
            token_id=token_id,
            connections=connections,
            sample_rate=sample_rate,
            channels=channels,
            strength=strength,
            smooth=smooth,
            verify_and_reencode=verify_and_reencode,
            timeout=timeout,
        )
        with self._stream_pools_lock:
            self._stream_pools.add(pool)
        return pool

    def close_stream_pools(self) -> None:
        """Close every stream pool created by this resource."""
        with self._stream_pools_lock:
            pools = list(self._stream_pools)
            self._auto_stream_pools.clear()
        for pool in pools:
            pool.close()

    @classmethod
    def _validate_encode_input(
        cls,
        audio: Union[str, Path, BinaryIO],
        *,
        token_id: str,
        strength: float,
        interval: Optional[float],
        timeout: float,
    ) -> None:
        if not token_id:
            raise ValueError("token_id is required")
        if isinstance(strength, bool) or not math.isfinite(strength) or not 0.1 <= strength <= 2.0:
            raise ValueError("strength must be between 0.1 and 2.0")
        if interval is not None and (
            isinstance(interval, bool) or not math.isfinite(interval) or interval < 0.0
        ):
            raise ValueError("interval must be a finite non-negative number")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("timeout must be a finite positive number")
        if isinstance(audio, (str, Path)) and Path(audio).stat().st_size > cls.MAX_UPLOAD_BYTES:
            raise ValueError("audio exceeds the 100 MiB upload limit")

    @staticmethod
    def _form_bool(value: object, name: str) -> str:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        return "true" if value else "false"

    @staticmethod
    def _resolve_response_format(
        response_format: Optional[str],
        *,
        output_path: Optional[Union[str, Path]],
        save_file: bool,
    ) -> str:
        if response_format is None:
            return "json" if output_path and save_file else "stream"
        resolved = str(response_format).strip().lower()
        if resolved not in {"stream", "json"}:
            raise ValueError("response_format must be 'stream' or 'json'")
        return resolved

    def _websocket_url(self, path: str) -> str:
        base = self._client._base_url.rstrip("/")
        split = urlsplit(base)
        scheme = "wss" if split.scheme == "https" else "ws"
        ws_path = f"{split.path.rstrip('/')}/{path.lstrip('/')}"
        return urlunsplit((scheme, split.netloc, ws_path, "", ""))

    def encode(
        self,
        audio: Union[str, Path, BinaryIO],
        token_id: str,
        *,
        strength: float = 1.0,
        smooth: bool = True,
        interval: Optional[float] = None,
        timeout: float = 900.0,
        output_path: Optional[Union[str, Path]] = None,
        save_file: bool = True,
        keep_original: bool = True,
        check_watermark: bool = True,
        verify_and_reencode: bool = True,
        response_format: Optional[str] = None,
        original_filename: Optional[str] = None,
    ) -> EncodeResult:
        """
        Encode a watermark into an audio file.

        Args:
            audio: Audio file path or file-like object
            token_id: Watermark token ID to use
            strength: Watermark strength (0.1-2.0, default 1.0)
            smooth: Smoothness control (default True). Same meaning on file encode and streaming encode.
            interval: Optional interval between watermarks. Omit it to use the service default; 0 is explicit.
            timeout: Request timeout in seconds (default 900 for long audio)
            output_path: Optional path to save the watermarked audio
            save_file: Persist the encoded file in OfSpectrum storage (default True)
            keep_original: Persist the uploaded source when save_file is True (default True)
            check_watermark: Reject audio that already contains a watermark (default True)
            verify_and_reencode: Verify the encoded result and re-encode on mismatch (default True)
            response_format: Optional "stream" (binary file) or "json" (download URL).
                When omitted, json is used only if output_path is set and save_file is True.
            original_filename: Optional original filename when `audio` is a file-like object

        Returns:
            EncodeResult with audio data or download URL

        Example:
            result = client.audio.encode(
                audio="input.mp3",
                token_id="uuid-here",
                output_path="watermarked.mp3"
            )
            print(f"Encoded {result.audio_duration}s of audio")
        """
        self._validate_encode_input(
            audio,
            token_id=token_id,
            strength=strength,
            interval=interval,
            timeout=timeout,
        )
        if original_filename is not None and (
            not isinstance(original_filename, str) or not original_filename.strip()
        ):
            raise ValueError("original_filename must be a non-empty string")

        # Prepare form data for the product API.
        form_data = {
            "token_id": token_id,
            "strength": str(strength),
            "smooth": self._form_bool(smooth, "smooth"),
            "save_file": self._form_bool(save_file, "save_file"),
            "keep_original": self._form_bool(keep_original, "keep_original"),
            "check_watermark": self._form_bool(check_watermark, "check_watermark"),
            "verify_and_reencode": self._form_bool(
                verify_and_reencode, "verify_and_reencode"
            ),
            "response_format": self._resolve_response_format(
                response_format,
                output_path=output_path,
                save_file=save_file,
            ),
        }
        if interval is not None:
            form_data["interval"] = str(interval)
        if original_filename:
            form_data["original_filename"] = original_filename.strip()

        # Open file if path provided
        if isinstance(audio, (str, Path)):
            path = Path(audio)
            with open(path, "rb") as f:
                files = {"audio": (path.name, f)}
                response = self._post(
                    "/audio/watermark/encode",
                    data=form_data,
                    files=files,
                    timeout=timeout,
                )
        else:
            # File-like object
            filename = getattr(audio, "name", "audio.wav")
            if hasattr(audio, "seek"):
                audio.seek(0)
            files = {"audio": (filename, audio)}
            response = self._post(
                "/audio/watermark/encode",
                data=form_data,
                files=files,
                timeout=timeout,
            )

        # Handle JSON response mode
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            data = response.json()
            raise_for_error(data, response.status_code)

            result_data = data.get("data")
            if not isinstance(result_data, dict) or not result_data:
                raise OfSpectrumError(message="Encoding returned an invalid JSON response")
            result = EncodeResult.from_dict(result_data)
            if output_path and not result.download_url:
                raise OfSpectrumError(message="Encoding response did not include a download URL")

            # Download and save if output_path provided
            if output_path and result.download_url:
                result.save(str(output_path))

            return result

        # Handle stream response mode
        if response.status_code != 200:
            # Try to parse as JSON error
            try:
                data = response.json()
                raise_for_error(data, response.status_code)
            except Exception:
                raise OfSpectrumError(
                    message=f"Encoding failed with status {response.status_code}",
                    status_code=response.status_code,
                )

        audio_bytes = response.content
        if not audio_bytes:
            raise OfSpectrumError(message="Encoding returned an empty audio response")
        if not (
            content_type.startswith("audio/")
            or content_type.startswith("video/")
            or content_type.startswith("application/octet-stream")
        ):
            raise OfSpectrumError(message="Encoding returned an invalid content type")
        try:
            duration = int(float(response.headers.get("X-Audio-Duration", 0)))
        except (TypeError, ValueError) as exc:
            raise OfSpectrumError(message="Encoding returned an invalid audio duration") from exc
        if duration <= 0:
            raise OfSpectrumError(message="Encoding response did not include a positive audio duration")
        returned_token_id = response.headers.get("X-Token-Id", token_id)
        if returned_token_id != token_id:
            raise OfSpectrumError(message="Encoding response token did not match the request")
        content_disp = response.headers.get("Content-Disposition", "")

        # Extract filename from content-disposition
        file_name = "watermarked.wav"
        if "filename*=" in content_disp:
            # UTF-8 encoded filename
            import urllib.parse
            parts = content_disp.split("filename*=UTF-8''")
            if len(parts) > 1:
                file_name = urllib.parse.unquote(parts[1].strip())
        elif "filename=" in content_disp:
            parts = content_disp.split("filename=")
            if len(parts) > 1:
                file_name = parts[1].strip().strip('"')

        result = EncodeResult.from_bytes(
            audio_bytes=audio_bytes,
            audio_duration=duration,
            token_id=returned_token_id,
            file_name=file_name,
            content_type=content_type,
            quality_warning=(
                response.headers.get("X-Encode-Quality-Warning", "").lower() == "true"
            ),
        )

        # Save if output_path provided
        if output_path:
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

        return result

    def decode(
        self,
        audio: Union[str, Path, BinaryIO],
        *,
        public_key: Optional[int] = None,
        save_file: bool = True,
    ) -> DecodeResult:
        """
        Decode (detect) a watermark from an audio file.

        Args:
            audio: Audio file path or file-like object
            public_key: Optional verification key when your workflow requires one
            save_file: Persist decode-side storage when the service supports it (default True)

        Returns:
            DecodeResult with watermark information

        Example:
            result = client.audio.decode("suspect.mp3")
            if result.watermarked:
                print(f"Found watermark! Token: {result.token_id}")
            else:
                print("No watermark detected")
        """
        form_data = {
            "save_file": self._form_bool(save_file, "save_file"),
        }
        if public_key is not None:
            form_data["public_key"] = str(public_key)

        if isinstance(audio, (str, Path)):
            path = Path(audio)
            with open(path, "rb") as f:
                files = {"audio": (path.name, f)}
                response = self._post(
                    "/audio/watermark/decode",
                    data=form_data,
                    files=files,
                    timeout=180.0,
                )
        else:
            filename = getattr(audio, "name", "audio.wav")
            if hasattr(audio, "seek"):
                audio.seek(0)
            files = {"audio": (filename, audio)}
            response = self._post(
                "/audio/watermark/decode",
                data=form_data,
                files=files,
                timeout=180.0,
            )

        data = response.json()
        raise_for_error(data, response.status_code)

        return DecodeResult.from_dict(data.get("data", {}))

    def stream_encode(
        self,
        audio: Union[str, Path, BinaryIO, bytes],
        token_id: str,
        *,
        strength: float = 1.0,
        smooth: bool = True,
        interval: float = 0.0,
        timeout: float = 900.0,
        output_path: Optional[Union[str, Path]] = None,
        save_file: bool = False,
        keep_original: bool = False,
        check_watermark: bool = False,
        verify_and_reencode: bool = True,
        response_format: str = "stream",
    ) -> EncodeResult:
        """Convenience path: read a media file and encode it over the streaming API.

        This is not the default file API. The SDK reads the whole file, sends PCM
        over the streaming API, and rebuilds a playable audio file locally.
        Video, extra audio tracks, the original codec, and source metadata are
        not guaranteed. Use ``encode()`` when those matter.

        Media libraries install with the SDK. A separate FFmpeg install is not
        required. ``smooth`` has the same meaning as file encode.

        Streaming encode does not store files on OfSpectrum. Callers that used
        to send save_file=false, keep_original=false, check_watermark=false,
        and response_format=stream must keep passing those values here.
        ``check_watermark`` is unsupported on this path.

        When ``interval`` is 0, repeated calls on the same client reuse a
        persistent stream pool instead of opening a new WebSocket each time.
        """
        source = read_audio_bytes(audio)
        if not token_id:
            raise ValueError("token_id is required")
        if isinstance(strength, bool) or not math.isfinite(strength) or not 0.1 <= strength <= 2.0:
            raise ValueError("strength must be between 0.1 and 2.0")
        if isinstance(interval, bool) or not math.isfinite(interval) or interval < 0.0:
            raise ValueError("interval must be a finite non-negative number")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("timeout must be a finite positive number")
        if not isinstance(smooth, bool):
            raise ValueError("smooth must be a boolean")
        if save_file is not False:
            raise ValueError("streaming encode cannot save files; pass save_file=False")
        if keep_original is not False:
            raise ValueError("streaming encode cannot keep the original file; pass keep_original=False")
        if check_watermark is not False:
            raise ValueError("streaming encode cannot pre-check watermarks; pass check_watermark=False")
        if not isinstance(verify_and_reencode, bool):
            raise ValueError("verify_and_reencode must be a boolean")
        if str(response_format).strip().lower() != "stream":
            raise ValueError("streaming encode only returns audio bytes; pass response_format='stream'")
        if output_path is not None:
            raise ValueError("streaming encode does not write local files; omit output_path")

        pcm, info = decode_canonical_interleaved_pcm(source)
        channel_count = max(1, int(info.channels))
        if interval == 0.0:
            pool = self._auto_stream_pool(
                token_id=token_id,
                sample_rate=CANONICAL_SAMPLE_RATE,
                channels=channel_count,
                strength=strength,
                smooth=smooth,
                verify_and_reencode=verify_and_reencode,
                timeout=timeout,
            )
            streamed = pool._encode_pcm(pcm, timeout=timeout)
            encoded_pcm = streamed.encoded_pcm
            quality_warning = streamed.quality_warning
            duration = streamed.audio_duration
        elif channel_count == 1:
            streamed = self.stream_encode_pcm(
                [pcm],
                token_id,
                sample_rate=CANONICAL_SAMPLE_RATE,
                channels=1,
                strength=strength,
                smooth=smooth,
                interval=interval,
                timeout=timeout,
                verify_and_reencode=verify_and_reencode,
            )
            encoded_pcm = streamed.encoded_pcm
            quality_warning = streamed.quality_warning
            duration = streamed.audio_duration
        else:
            channel_pcm = split_interleaved_pcm_f32le(pcm, channel_count)
            results = [None] * channel_count

            def _encode_channel(index: int):
                return index, self.stream_encode_pcm(
                    [channel_pcm[index]],
                    token_id,
                    sample_rate=CANONICAL_SAMPLE_RATE,
                    channels=1,
                    strength=strength,
                    smooth=smooth,
                    interval=interval,
                    timeout=timeout,
                    verify_and_reencode=verify_and_reencode,
                )

            with ThreadPoolExecutor(max_workers=channel_count) as workers:
                futures = [
                    workers.submit(_encode_channel, index) for index in range(channel_count)
                ]
                for future in as_completed(futures):
                    index, streamed = future.result()
                    results[index] = streamed
            encoded_pcm = interleave_pcm_f32le(
                tuple(item.encoded_pcm for item in results)
            )
            quality_warning = any(item.quality_warning for item in results)
            duration = max(item.audio_duration for item in results)
        rebuilt = rebuild_encoded_media(encoded_pcm, info)
        duration = int(round(duration))
        if duration <= 0 and info.duration_seconds > 0:
            duration = max(1, int(round(info.duration_seconds)))
        return EncodeResult.from_bytes(
            audio_bytes=rebuilt,
            audio_duration=duration,
            token_id=token_id,
            file_name=suggested_filename(info),
            content_type=info.content_type,
            quality_warning=quality_warning,
        )

    def stream_encode_pcm(
        self,
        pcm_chunks: Iterable[bytes],
        token_id: str,
        *,
        sample_rate: int = 48000,
        channels: int = 1,
        strength: float = 1.0,
        smooth: bool = True,
        interval: float = 0.0,
        timeout: float = 900.0,
        verify_and_reencode: bool = True,
    ) -> StreamingEncodeResult:
        """
        Stream raw PCM float32 little-endian audio for watermark encoding.

        Live capture can feed ``pcm_chunks``, but this synchronous SDK method
        still returns one complete result after the server ``done`` event.
        Only raw WebSocket clients consume provisional binary chunks before
        ``done``. There is no iterator or callback API.

        The SDK sends token_id and product-level encoding settings.
        Returned bytes are encoded raw PCM float32 little-endian, not WAV.
        Yield chunks as they become available so encoding can start before
        the full file is ready.
        """
        if not token_id:
            raise ValueError("token_id is required")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if channels <= 0 or channels > 8:
            raise ValueError("channels must be between 1 and 8")
        if isinstance(strength, bool) or not math.isfinite(strength) or not 0.1 <= strength <= 2.0:
            raise ValueError("strength must be a finite number between 0.1 and 2.0")
        if not isinstance(smooth, bool):
            raise ValueError("smooth must be a boolean")
        if isinstance(interval, bool) or not math.isfinite(interval) or interval < 0.0:
            raise ValueError("interval must be a finite non-negative number")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("timeout must be a finite positive number")
        if not isinstance(verify_and_reencode, bool):
            raise ValueError("verify_and_reencode must be a boolean")

        try:
            from websockets.sync.client import connect
        except Exception as exc:
            raise OfSpectrumError(
                message="Streaming encode requires the 'websockets' package",
                code="MissingDependency",
            ) from exc

        url = self._websocket_url("/audio/watermark/ws/encode")
        headers = {"Authorization": f"Bearer {self._client._api_key}"}
        config = {
            "type": "config",
            "config": {
                "token_id": token_id,
                "sample_rate": sample_rate,
                "channels": channels,
                "strength": strength,
                "smooth": smooth,
                "interval": interval,
                "verify_and_reencode": verify_and_reencode,
            },
        }
        encoded_chunks = []
        events = []
        completed = False

        try:
            ws_context = connect(
                url,
                additional_headers=headers,
                open_timeout=self._client._timeout,
                ping_timeout=None,
                close_timeout=2.0,
            )
        except TypeError:
            ws_context = connect(
                url,
                extra_headers=headers,
                open_timeout=self._client._timeout,
                ping_timeout=None,
                close_timeout=2.0,
            )

        with ws_context as ws:
            ws.send(json.dumps(config))
            deadline = time.monotonic() + float(timeout)

            def drain_output(*, block: bool) -> bool:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        raise OfSpectrumError(
                            message="Streaming encode timed out before completion",
                            code="StreamingEncodeIncomplete",
                        )
                    recv_timeout = remaining if block else min(0.02, remaining)
                    try:
                        message = ws.recv(timeout=recv_timeout)
                    except TimeoutError:
                        if block:
                            raise OfSpectrumError(
                                message="Streaming encode timed out before completion",
                                code="StreamingEncodeIncomplete",
                            ) from None
                        return False
                    if self._collect_stream_encode_message(
                        message, encoded_chunks, events
                    ):
                        return True

            stop_watchdog = _start_deadline_watchdog(ws, deadline)
            try:
                for chunk in pcm_chunks:
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("pcm_chunks must yield bytes-like objects")
                    if len(chunk) == 0:
                        continue
                    ws.send(bytes(chunk))
                    if drain_output(block=False):
                        completed = True
                        break
                if not completed:
                    ws.send(json.dumps({"type": "end"}))
                    completed = drain_output(block=True)
            except (TypeError, ValueError, OfSpectrumError):
                _abort_websocket_transport(ws)
                raise
            except Exception as exc:
                _abort_websocket_transport(ws)
                if time.monotonic() >= deadline:
                    raise OfSpectrumError(
                        message="Streaming encode timed out before completion",
                        code="StreamingEncodeIncomplete",
                    ) from exc
                raise OfSpectrumError(
                    message="Streaming encode connection closed before completion",
                    code="StreamingEncodeIncomplete",
                ) from exc
            finally:
                stop_watchdog.set()

        if not completed:
            raise OfSpectrumError(
                message="Streaming encode did not complete",
                code="StreamingEncodeIncomplete",
            )
        if not encoded_chunks:
            raise OfSpectrumError(
                message="Streaming encode returned no audio",
                code="StreamingEncodeEmpty",
            )

        return StreamingEncodeResult(
            encoded_pcm=b"".join(encoded_chunks),
            token_id=token_id,
            sample_rate=sample_rate,
            channels=channels,
            events=events,
            quality_warning=any(
                event.get("type") == "quality_warning"
                or bool(event.get("quality_warning"))
                for event in events
                if isinstance(event, dict)
            ),
        )

    @staticmethod
    def _collect_stream_encode_message(
        message: Any,
        encoded_chunks: list,
        events: list,
    ) -> bool:
        if isinstance(message, bytes):
            encoded_chunks.append(message)
            return False
        if isinstance(message, str):
            try:
                event = json.loads(message)
            except Exception:
                event = {"type": "message", "message": message}
            if isinstance(event, dict):
                events.append(event)
                if event.get("type") in {"error", "quota_exceeded"}:
                    raise OfSpectrumError(
                        message=str(event.get("message") or "Streaming encode failed"),
                        code=str(event.get("type") or "StreamingEncodeError"),
                    )
                return event.get("type") == "done"
        return False

    # Note: decode_from_url is not yet available
