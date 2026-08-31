"""Benchmark native ElevenLabs TTS against OfSpectrum-wrapped TTS.

Required environment variables:
    ELEVENLABS_API_KEY
    OFSPECTRUM_API_KEY
    OFSPECTRUM_TOKEN_ID

Example:
    python -m benchmarks.elevenlabs_latency --iterations 20 --warmups 2
"""

import argparse
import json
import math
import os
import statistics
import time
from typing import Any, Dict, Iterable, List, Tuple

from ofspectrum import Ofspectrum


def collect_audio(response: Any) -> bytes:
    if isinstance(response, bytes):
        return response
    return b"".join(bytes(chunk) for chunk in response)


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("at least one value is required")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summary(values: List[float]) -> Dict[str, float]:
    return {
        "average_ms": statistics.fmean(values) * 1000.0,
        "p50_ms": percentile(values, 0.50) * 1000.0,
        "p95_ms": percentile(values, 0.95) * 1000.0,
    }


def timed_tts(client: Any, request: Dict[str, Any]) -> Tuple[float, bytes]:
    started = time.perf_counter()
    audio = collect_audio(client.text_to_speech.convert(**request))
    return time.perf_counter() - started, audio


def output_filename(output_format: str) -> str:
    codec = output_format.split("_", 1)[0].lower()
    extension = "mp3" if codec == "auto" else codec
    return "elevenlabs-output." + extension


def run(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        from dotenv import load_dotenv
        from elevenlabs.client import ElevenLabs
    except ImportError as exc:
        raise SystemExit(
            'The benchmark requires the optional dependency: pip install "ofspectrum[elevenlabs]"'
        ) from exc

    load_dotenv()

    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    ofspectrum_key = os.environ.get("OFSPECTRUM_API_KEY")
    token_id = os.environ.get("OFSPECTRUM_TOKEN_ID")
    missing = [
        name
        for name, value in (
            ("ELEVENLABS_API_KEY", elevenlabs_key),
            ("OFSPECTRUM_API_KEY", ofspectrum_key),
            ("OFSPECTRUM_TOKEN_ID", token_id),
        )
        if not value
    ]
    if missing:
        raise SystemExit("Missing required environment variable(s): " + ", ".join(missing))

    native = ElevenLabs(api_key=elevenlabs_key)
    wrapped = Ofspectrum(
        native,
        api_key=ofspectrum_key,
        token_id=token_id,
    )
    request = {
        "text": args.text,
        "voice_id": args.voice_id,
        "model_id": args.model_id,
        "output_format": args.output_format,
    }

    native_times = []  # type: List[float]
    wrapped_times = []  # type: List[float]
    encode_times = []  # type: List[float]
    additions = []  # type: List[float]
    try:
        for _ in range(args.warmups):
            _, audio = timed_tts(native, request)
            timed_tts(wrapped, request)
            wrapped.watermark.encode_bytes(
                audio, filename=output_filename(args.output_format)
            )

        for index in range(args.iterations):
            # Alternate order to reduce connection warming and service drift
            # from systematically favoring either client path.
            if index % 2:
                wrapped_elapsed, _ = timed_tts(wrapped, request)
                native_elapsed, native_audio = timed_tts(native, request)
            else:
                native_elapsed, native_audio = timed_tts(native, request)
                wrapped_elapsed, _ = timed_tts(wrapped, request)

            encode_started = time.perf_counter()
            wrapped.watermark.encode_bytes(
                native_audio,
                filename=output_filename(args.output_format),
            )
            encode_elapsed = time.perf_counter() - encode_started

            native_times.append(native_elapsed)
            wrapped_times.append(wrapped_elapsed)
            encode_times.append(encode_elapsed)
            additions.append(wrapped_elapsed - native_elapsed)
    finally:
        wrapped.close()

    return {
        "iterations": args.iterations,
        "warmups": args.warmups,
        "request": request,
        "native_elevenlabs": summary(native_times),
        "elevenlabs_plus_watermark": summary(wrapped_times),
        "watermark_encode_only": summary(encode_times),
        "added_to_complete_request": summary(additions),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--voice-id", default="JBFqnCBsd6RMkjVDRZzb")
    parser.add_argument("--model-id", default="eleven_multilingual_v2")
    parser.add_argument("--output-format", default="mp3_44100_128")
    parser.add_argument(
        "--text",
        default=(
            "Audio watermark latency needs a sample long enough for reliable encoding. "
            "This benchmark uses the same ElevenLabs request for both the native client "
            "and the OfSpectrum wrapper. The resulting measurements compare generation "
            "time, watermark encoding time, and the total additional request latency "
            "without changing the voice, model, output format, or spoken content."
        ),
    )
    args = parser.parse_args()
    if args.iterations < 1 or args.warmups < 0:
        parser.error("iterations must be positive and warmups cannot be negative")
    return args


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))
