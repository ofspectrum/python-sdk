"""Run duration-tier latency tests across ElevenLabs complete-audio services.

Services: Speech-to-Speech, Sound Effects, Text-to-Dialogue, Audio Isolation,
Music Compose, and Video-to-Music. Each service runs 2s, 5s, 10s, and 30s
tiers three consecutive times. Every native response is then watermarked using
the exact same bytes, producing a paired encode-disabled / encode-enabled
comparison without cross-generation variance.

This script consumes real API quota and checkpoints all results to one JSON
file under ``benchmarks/results``.
"""

import argparse
import json
import os
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

from ofspectrum import Ofspectrum
from ofspectrum.media import probe_audio

from .elevenlabs_api_smoke import create_test_video
from .elevenlabs_duration_latency import (
    ITERATIONS,
    MODEL_ID,
    OUTPUT_FORMAT,
    TIER_TEXTS,
    VOICE_ID,
    collect_audio,
    error_record,
    summarize_tier,
    write_report,
)

SERVICES = (
    "speech_to_speech",
    "sound_effects",
    "text_to_dialogue",
    "audio_isolation",
    "music_compose",
    "video_to_music",
)


def create_tier_wav(source: Path, destination: Path, seconds: int) -> None:
    """Trim or repeat the repository speech sample to an exact WAV duration."""
    with wave.open(str(source), "rb") as input_file:
        parameters = input_file.getparams()
        source_frames = input_file.readframes(input_file.getnframes())
    frame_bytes = parameters.sampwidth * parameters.nchannels
    required_bytes = int(parameters.framerate * seconds) * frame_bytes
    repeats = required_bytes // len(source_frames) + 1
    output_frames = (source_frames * repeats)[:required_bytes]
    with wave.open(str(destination), "wb") as output_file:
        output_file.setparams(parameters)
        output_file.writeframes(output_frames)


def native_operation(
    native: ElevenLabs,
    service: str,
    target_seconds: int,
    text: str,
    wav_input: Tuple[str, bytes, str],
    video_input: Tuple[str, bytes, str],
) -> Any:
    if service == "speech_to_speech":
        return native.speech_to_speech.convert(
            voice_id=VOICE_ID,
            audio=wav_input,
            model_id="eleven_multilingual_sts_v2",
            output_format=OUTPUT_FORMAT,
            enable_logging=False,
        )
    if service == "sound_effects":
        return native.text_to_sound_effects.convert(
            text="A steady ocean shoreline with rolling waves and gentle wind",
            duration_seconds=float(target_seconds),
            output_format=OUTPUT_FORMAT,
        )
    if service == "text_to_dialogue":
        return native.text_to_dialogue.convert(
            inputs=[{"voice_id": VOICE_ID, "text": text}],
            output_format=OUTPUT_FORMAT,
            enable_logging=False,
        )
    if service == "audio_isolation":
        return native.audio_isolation.convert(audio=wav_input)
    if service == "music_compose":
        return native.music.compose(
            prompt="A calm instrumental ambient track with soft piano and warm pads",
            music_length_ms=target_seconds * 1000,
            force_instrumental=True,
            output_format=OUTPUT_FORMAT,
        )
    if service == "video_to_music":
        return native.music.video_to_music(
            videos=[video_input],
            description="A calm instrumental background track",
            output_format=OUTPUT_FORMAT,
        )
    raise ValueError("Unsupported service: " + service)


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(__file__).resolve().parent / "results" / (
        "elevenlabs_services_duration_latency_" + timestamp + ".json"
    )


def require_credentials() -> None:
    names = ("ELEVENLABS_API_KEY", "OFSPECTRUM_API_KEY", "OFSPECTRUM_TOKEN_ID")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise SystemExit("Missing required environment variable(s): " + ", ".join(missing))


def selected_services(requested: Optional[Iterable[str]]) -> Set[str]:
    selected = set(requested or SERVICES)
    unsupported = selected - set(SERVICES)
    if unsupported:
        raise ValueError("Unsupported service(s): " + ", ".join(sorted(unsupported)))
    return selected


def empty_summary(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "attempted_pairs": len(runs),
        "successful_pairs": 0,
        "failed_pairs": len(runs),
        "actual_audio_seconds": None,
        "encode_disabled": None,
        "encode_enabled": None,
        "added_by_encode": None,
    }


def run(output_path: Path, requested_services: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    require_credentials()
    selected = selected_services(requested_services)

    native = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    wrapped = Ofspectrum(
        native,
        api_key=os.environ["OFSPECTRUM_API_KEY"],
        token_id=os.environ["OFSPECTRUM_TOKEN_ID"],
    )
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "iterations_per_tier": ITERATIONS,
            "tiers_seconds": list(TIER_TEXTS),
            "order": "native service response, then encode the exact same bytes",
            "encode_disabled_ms": "complete native ElevenLabs service latency",
            "encode_enabled_ms": "native latency + OfSpectrum encode latency",
            "added_latency_ms": "OfSpectrum encode latency for the paired audio",
            "retries": 0,
        },
        "request": {
            "voice_id": VOICE_ID,
            "tts_model_id": MODEL_ID,
            "output_format": OUTPUT_FORMAT,
        },
        "services": [],
    }  # type: Dict[str, Any]
    write_report(output_path, report)

    source_path = Path(__file__).resolve().parents[1] / "examples/audio/sample-speech-like-12s.wav"
    try:
        with tempfile.TemporaryDirectory(prefix="ofspectrum-duration-services-") as temp_dir:
            temp_path = Path(temp_dir)
            inputs = {}
            for target_seconds in TIER_TEXTS:
                wav_path = temp_path / ("speech-" + str(target_seconds) + "s.wav")
                video_path = temp_path / ("video-" + str(target_seconds) + "s.mp4")
                create_tier_wav(source_path, wav_path, target_seconds)
                create_test_video(video_path, seconds=target_seconds)
                inputs[target_seconds] = {
                    "wav": (wav_path.name, wav_path.read_bytes(), "audio/wav"),
                    "video": (video_path.name, video_path.read_bytes(), "video/mp4"),
                }

            for service in SERVICES:
                if service not in selected:
                    continue
                service_result = {"service": service, "tiers": []}
                report["services"].append(service_result)

                for target_seconds, text in TIER_TEXTS.items():
                    tier = {"target_seconds": target_seconds, "runs": []}
                    service_result["tiers"].append(tier)

                    for iteration in range(1, ITERATIONS + 1):
                        native_started = time.perf_counter()
                        try:
                            response = native_operation(
                                native,
                                service,
                                target_seconds,
                                text,
                                inputs[target_seconds]["wav"],
                                inputs[target_seconds]["video"],
                            )
                            native_audio = collect_audio(response)
                            native_ms = (time.perf_counter() - native_started) * 1000.0
                            actual_seconds = probe_audio(native_audio).duration_seconds
                            run_result = {
                                "iteration": iteration,
                                "encode_disabled": {
                                    "status": "PASS",
                                    "latency_ms": round(native_ms, 2),
                                    "actual_audio_seconds": round(actual_seconds, 3),
                                    "audio_bytes": len(native_audio),
                                },
                            }  # type: Dict[str, Any]
                        except Exception as exc:
                            native_ms = (time.perf_counter() - native_started) * 1000.0
                            run_result = {
                                "iteration": iteration,
                                "encode_disabled": error_record(exc, native_ms),
                                "encode_enabled": {
                                    "status": "SKIP",
                                    "reason": "native service request failed",
                                },
                                "added_latency_ms": None,
                                "increase_percent_vs_disabled": None,
                            }
                            tier["runs"].append(run_result)
                            write_report(output_path, report)
                            print(
                                json.dumps(
                                    {"service": service, "target_seconds": target_seconds, **run_result}
                                ),
                                flush=True,
                            )
                            continue

                        encode_started = time.perf_counter()
                        try:
                            encoded_audio = wrapped.watermark.encode_bytes(
                                native_audio,
                                filename="elevenlabs-output.mp3",
                            )
                            encode_ms = (time.perf_counter() - encode_started) * 1000.0
                            run_result["encode_enabled"] = {
                                "status": "PASS",
                                "complete_latency_ms": round(native_ms + encode_ms, 2),
                                "encode_latency_ms": round(encode_ms, 2),
                                "audio_bytes": len(encoded_audio),
                            }
                            run_result["added_latency_ms"] = round(encode_ms, 2)
                            run_result["increase_percent_vs_disabled"] = round(
                                encode_ms / native_ms * 100.0, 2
                            )
                        except Exception as exc:
                            encode_ms = (time.perf_counter() - encode_started) * 1000.0
                            run_result["encode_enabled"] = error_record(exc, encode_ms)
                            run_result["added_latency_ms"] = None
                            run_result["increase_percent_vs_disabled"] = None

                        tier["runs"].append(run_result)
                        write_report(output_path, report)
                        print(
                            json.dumps(
                                {"service": service, "target_seconds": target_seconds, **run_result}
                            ),
                            flush=True,
                        )

                    native_successes = [
                        item
                        for item in tier["runs"]
                        if item["encode_disabled"]["status"] == "PASS"
                    ]
                    tier["summary"] = (
                        summarize_tier(native_successes)
                        if native_successes
                        else empty_summary(tier["runs"])
                    )
                    write_report(output_path, report)
    finally:
        wrapped.close()

    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["output_file"] = str(output_path)
    write_report(output_path, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--service",
        action="append",
        choices=SERVICES,
        help="run only this service; repeat for multiple services",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    destination = arguments.output or default_output_path()
    result = run(destination, requested_services=arguments.service)
    print(json.dumps({"output_file": result["output_file"]}, indent=2))
