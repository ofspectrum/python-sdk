"""Bundled media helpers for streaming file encode."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
from typing import BinaryIO, Iterator, Optional, Union

from .exceptions import OfSpectrumError


CANONICAL_SAMPLE_RATE = 48000
CANONICAL_CHANNELS = 1
DEFAULT_CHUNK_SAMPLES = 24000
MAX_UPLOAD_BYTES = 100 * 1024 * 1024

_CONTENT_TYPES = {
    "wav": "audio/wav",
    "wave": "audio/wav",
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "aac": "audio/aac",
    "webm": "audio/webm",
}

_OUTPUT_FORMAT = {
    "wav": "wav",
    "wave": "wav",
    "mp3": "mp3",
    "flac": "flac",
    "ogg": "ogg",
    "opus": "ogg",
    "m4a": "ipod",
    "mp4": "mp4",
    "aac": "adts",
    "webm": "webm",
}

_CHANNEL_LAYOUTS = {
    1: "mono",
    2: "stereo",
    3: "3.0",
    4: "quad",
    5: "5.0",
    6: "5.1",
    7: "6.1",
    8: "7.1",
}

_OUTPUT_CODEC = {
    "wav": "pcm_s16le",
    "wave": "pcm_s16le",
    "mp3": "libmp3lame",
    "flac": "flac",
    "ogg": "libvorbis",
    "opus": "libopus",
    "m4a": "aac",
    "mp4": "aac",
    "aac": "aac",
    "webm": "libopus",
}


@dataclass(frozen=True)
class AudioMediaInfo:
    format_name: str
    codec_name: str
    sample_rate: int
    channels: int
    duration_seconds: float
    extension: str
    content_type: str


def _import_av():
    try:
        import av
    except Exception as exc:
        raise OfSpectrumError(
            message="Streaming file encode requires the bundled 'av' package",
            code="MissingDependency",
        ) from exc
    return av


def read_audio_bytes(audio: Union[str, Path, BinaryIO, bytes]) -> bytes:
    if isinstance(audio, (bytes, bytearray, memoryview)):
        payload = bytes(audio)
    elif isinstance(audio, (str, Path)):
        payload = Path(audio).read_bytes()
    else:
        if hasattr(audio, "seek"):
            audio.seek(0)
        payload = audio.read()
        if hasattr(audio, "seek"):
            audio.seek(0)
    if not payload:
        raise ValueError("audio file is empty")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValueError("audio exceeds the 100 MiB upload limit")
    return payload


def _extension_from_format(format_name: str, codec_name: str) -> str:
    names = {part.strip().lower() for part in (format_name or "").split(",") if part.strip()}
    if "mp3" in names or codec_name == "mp3":
        return "mp3"
    if "wav" in names or "wave" in names or codec_name.startswith("pcm_"):
        return "wav"
    if "flac" in names or codec_name == "flac":
        return "flac"
    if "ogg" in names:
        return "opus" if codec_name == "opus" else "ogg"
    if "webm" in names:
        return "webm"
    if "mp4" in names or "ipod" in names or "m4a" in names:
        return "m4a"
    if "aac" in names or codec_name == "aac":
        return "aac"
    return "wav"


def probe_audio(audio_bytes: bytes) -> AudioMediaInfo:
    av = _import_av()
    with av.open(io.BytesIO(audio_bytes), mode="r") as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise OfSpectrumError(message="audio file has no audio stream")
        codec_name = str(getattr(stream.codec_context, "name", "") or "")
        sample_rate = int(stream.rate or 0)
        channels = int(stream.channels or 0)
        duration = 0.0
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        elif container.duration:
            duration = float(container.duration) / 1_000_000.0
        format_name = str(getattr(container.format, "name", "") or "")
    if sample_rate <= 0 or channels <= 0:
        raise OfSpectrumError(message="audio metadata is unsupported")
    extension = _extension_from_format(format_name, codec_name)
    return AudioMediaInfo(
        format_name=format_name,
        codec_name=codec_name,
        sample_rate=sample_rate,
        channels=channels,
        duration_seconds=duration,
        extension=extension,
        content_type=_CONTENT_TYPES.get(extension, "application/octet-stream"),
    )


def _flush_pcm_chunks(buffer: bytearray, chunk_bytes: int) -> Iterator[bytes]:
    chunks = []
    offset = 0
    length = len(buffer)
    while offset + chunk_bytes <= length:
        chunks.append(bytes(buffer[offset : offset + chunk_bytes]))
        offset += chunk_bytes
    if offset:
        del buffer[:offset]
    yield from chunks


def _layout_for_channels(channels: int) -> str:
    layout = _CHANNEL_LAYOUTS.get(int(channels))
    if layout is None:
        raise OfSpectrumError(message="audio channel count is unsupported")
    return layout


def split_interleaved_pcm_f32le(pcm_f32le: bytes, channels: int) -> tuple[bytes, ...]:
    import numpy as np

    if channels <= 0 or channels > 8:
        raise OfSpectrumError(message="audio channel count is unsupported")
    frame_bytes = 4 * channels
    if not pcm_f32le or len(pcm_f32le) % frame_bytes:
        raise OfSpectrumError(message="encoded PCM is invalid")
    frames = np.frombuffer(pcm_f32le, dtype="<f4").reshape(-1, channels)
    return tuple(np.ascontiguousarray(frames[:, index]).tobytes() for index in range(channels))


def interleave_pcm_f32le(channel_pcm: tuple[bytes, ...]) -> bytes:
    import numpy as np

    if not channel_pcm:
        raise OfSpectrumError(message="encoded PCM is invalid")
    arrays = [np.frombuffer(item, dtype="<f4") for item in channel_pcm]
    sizes = {item.size for item in arrays}
    if len(sizes) != 1 or 0 in sizes:
        raise OfSpectrumError(message="encoded PCM is invalid")
    stacked = np.stack(arrays, axis=1)
    return np.ascontiguousarray(stacked, dtype="<f4").tobytes()


def decode_canonical_interleaved_pcm(audio_bytes: bytes) -> tuple[bytes, AudioMediaInfo]:
    """Decode a file to 48 kHz interleaved float32 PCM, keeping source channels."""
    info = probe_audio(audio_bytes)
    av = _import_av()
    layout = _layout_for_channels(info.channels)
    buffer = bytearray()
    with av.open(io.BytesIO(audio_bytes), mode="r") as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise OfSpectrumError(message="audio file has no audio stream")
        resampler = av.AudioResampler(
            format="flt",
            layout=layout,
            rate=CANONICAL_SAMPLE_RATE,
        )
        for frame in container.decode(stream):
            converted = resampler.resample(frame)
            if converted is None:
                continue
            if not isinstance(converted, (list, tuple)):
                converted = [converted]
            for item in converted:
                if item is None or item.samples <= 0:
                    continue
                buffer.extend(_ndarray_to_interleaved_f32(item.to_ndarray()))
        flushed = resampler.resample(None)
        if flushed is None:
            flushed = []
        elif not isinstance(flushed, (list, tuple)):
            flushed = [flushed]
        for item in flushed:
            if item is None or item.samples <= 0:
                continue
            buffer.extend(_ndarray_to_interleaved_f32(item.to_ndarray()))
    if not buffer:
        raise OfSpectrumError(message="audio file is empty")
    return bytes(buffer), info


def _ndarray_to_interleaved_f32(array) -> bytes:
    import numpy as np

    values = np.asarray(array)
    if values.ndim == 2:
        if values.shape[0] <= 8 and values.shape[0] <= values.shape[1]:
            values = values.T
        values = np.ascontiguousarray(values).reshape(-1)
    return np.asarray(values, dtype="<f4").tobytes()


def iter_canonical_pcm_chunks(
    audio_bytes: bytes,
    *,
    chunk_samples: int = DEFAULT_CHUNK_SAMPLES,
) -> Iterator[bytes]:
    """Decode any supported file and yield 48 kHz mono float32le chunks."""

    av = _import_av()
    if chunk_samples <= 0:
        raise ValueError("chunk_samples must be positive")
    chunk_bytes = chunk_samples * 4
    buffer = bytearray()
    with av.open(io.BytesIO(audio_bytes), mode="r") as container:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise OfSpectrumError(message="audio file has no audio stream")
        resampler = av.AudioResampler(
            format="flt",
            layout="mono",
            rate=CANONICAL_SAMPLE_RATE,
        )
        for frame in container.decode(stream):
            converted = resampler.resample(frame)
            if converted is None:
                continue
            if not isinstance(converted, (list, tuple)):
                converted = [converted]
            for item in converted:
                if item is None or item.samples <= 0:
                    continue
                buffer.extend(_ndarray_to_interleaved_f32(item.to_ndarray()))
                yield from _flush_pcm_chunks(buffer, chunk_bytes)
        flushed = resampler.resample(None)
        if flushed is None:
            flushed = []
        elif not isinstance(flushed, (list, tuple)):
            flushed = [flushed]
        for item in flushed:
            if item is None or item.samples <= 0:
                continue
            buffer.extend(_ndarray_to_interleaved_f32(item.to_ndarray()))
            yield from _flush_pcm_chunks(buffer, chunk_bytes)
    if buffer:
        yield bytes(buffer)


def rebuild_encoded_media(
    encoded_pcm_f32le: bytes,
    info: AudioMediaInfo,
) -> bytes:
    """Rebuild a playable container from encoded 48 kHz interleaved float32 PCM."""

    av = _import_av()
    import numpy as np

    channel_count = max(1, int(info.channels))
    frame_bytes = 4 * channel_count
    if not encoded_pcm_f32le or len(encoded_pcm_f32le) % frame_bytes:
        raise OfSpectrumError(message="encoded PCM is invalid")
    samples = np.frombuffer(encoded_pcm_f32le, dtype="<f4")
    if samples.size % channel_count:
        raise OfSpectrumError(message="encoded PCM is invalid")
    if not np.isfinite(samples).all():
        raise OfSpectrumError(message="encoded PCM contains non-finite samples")
    layout = _layout_for_channels(channel_count)
    if channel_count == 1:
        frame = av.AudioFrame.from_ndarray(
            np.expand_dims(samples, 0),
            format="flt",
            layout=layout,
        )
    else:
        planar = np.ascontiguousarray(samples.reshape(-1, channel_count).T)
        frame = av.AudioFrame.from_ndarray(planar, format="fltp", layout=layout)
    frame.sample_rate = CANONICAL_SAMPLE_RATE
    codec = _OUTPUT_CODEC.get(info.extension, "pcm_s16le")
    container_format = _OUTPUT_FORMAT.get(info.extension, "wav")
    if info.codec_name.startswith("pcm_") and info.extension in {"wav", "wave"}:
        codec = "pcm_s16le"
        container_format = "wav"
    output = io.BytesIO()
    with av.open(output, mode="w", format=container_format) as container:
        out_stream = container.add_stream(codec, rate=info.sample_rate)
        out_stream.layout = layout
        resampler = av.AudioResampler(
            format=out_stream.format.name if out_stream.format else "s16",
            layout=layout,
            rate=info.sample_rate,
        )
        converted = resampler.resample(frame) or []
        if not isinstance(converted, (list, tuple)):
            converted = [converted]
        flushed = resampler.resample(None) or []
        if not isinstance(flushed, (list, tuple)):
            flushed = [flushed]
        for item in list(converted) + list(flushed):
            if item is None or item.samples <= 0:
                continue
            for packet in out_stream.encode(item):
                container.mux(packet)
        for packet in out_stream.encode(None):
            container.mux(packet)
    return output.getvalue()


def suggested_filename(info: AudioMediaInfo, stem: str = "watermarked") -> str:
    return f"{stem}.{info.extension}"
