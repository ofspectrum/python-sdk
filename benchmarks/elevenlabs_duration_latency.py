"""Measure watermark latency at 2s, 5s, 10s, and 30s audio tiers.

Each tier runs three consecutive paired measurements. One ElevenLabs TTS
response is measured as encode-disabled, then those exact audio bytes are sent
through ``WatermarkController.encode_bytes``. The encode-enabled complete
latency is the TTS latency plus the encode latency, avoiding cross-generation
variance in the comparison.

The script consumes real ElevenLabs and OfSpectrum quota. It checkpoints every
result to one timestamped JSON file under ``benchmarks/results``.

Run:
    python -m benchmarks.elevenlabs_duration_latency
"""

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

from ofspectrum import Ofspectrum
from ofspectrum.media import probe_audio

VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
MODEL_ID = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
ITERATIONS = 3

TIER_TEXTS = {
    2: "Testing audio watermark latency now.",
    5: "This short sample measures watermark latency for a five second spoken audio clip.",
    10: (
        "This ten second sample measures the additional latency introduced by audio "
        "watermark encoding while keeping the voice, model, and output format unchanged."
    ),
    30: (
        "This thirty second benchmark sample measures watermark latency on a longer piece "
        "of generated speech. Every run uses the same voice, model, output format, and "
        "spoken content. First, the script records how long ElevenLabs takes to return the "
        "complete audio file. It then sends those exact audio bytes to OfSpectrum for "
        "watermark encoding. Using the same generated file for both measurements prevents "
        "normal variation between separate speech generations from being counted as "
        "watermark overhead, producing a cleaner and more useful comparison."
    ),
}


def collect_audio(response: Any) -> bytes:
    if isinstance(response, bytes):
        return response
    return b"".join(bytes(chunk) for chunk in response)


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("at least one value is required")
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(values: List[float]) -> Optional[Dict[str, float]]:
    if not values:
        return None
    return {
        "average_ms": round(statistics.fmean(values), 2),
        "p50_ms": round(percentile(values, 0.50), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


def error_record(exc: Exception, elapsed_ms: float) -> Dict[str, Any]:
    return {
        "status": "FAIL",
        "elapsed_until_failure_ms": round(elapsed_ms, 2),
        "error_type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "status_code": getattr(exc, "status_code", None),
        "reason": str(exc),
    }


def summarize_tier(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    completed = [run for run in runs if run["encode_enabled"]["status"] == "PASS"]
    disabled = [run["encode_disabled"]["latency_ms"] for run in runs]
    enabled = [run["encode_enabled"]["complete_latency_ms"] for run in completed]
    additions = [run["added_latency_ms"] for run in completed]
    durations = [run["encode_disabled"]["actual_audio_seconds"] for run in runs]
    return {
        "attempted_pairs": len(runs),
        "successful_pairs": len(completed),
        "failed_pairs": len(runs) - len(completed),
        "actual_audio_seconds": {
            "average": round(statistics.fmean(durations), 3),
            "min": round(min(durations), 3),
            "max": round(max(durations), 3),
        },
        "encode_disabled": latency_summary(disabled),
        "encode_enabled": latency_summary(enabled),
        "added_by_encode": latency_summary(additions),
    }


def write_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require_credentials() -> None:
    names = ("ELEVENLABS_API_KEY", "OFSPECTRUM_API_KEY", "OFSPECTRUM_TOKEN_ID")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise SystemExit("Missing required environment variable(s): " + ", ".join(missing))


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(__file__).resolve().parent / "results" / (
        "elevenlabs_duration_latency_" + timestamp + ".json"
    )


def run(output_path: Path) -> Dict[str, Any]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    require_credentials()

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
            "order": "TTS encode-disabled, then encode the exact same bytes",
            "encode_disabled_ms": "complete ElevenLabs TTS latency",
            "encode_enabled_ms": "TTS latency + OfSpectrum encode latency",
            "added_latency_ms": "OfSpectrum encode latency for the paired audio",
            "retries": 0,
        },
        "request": {
            "voice_id": VOICE_ID,
            "model_id": MODEL_ID,
            "output_format": OUTPUT_FORMAT,
        },
        "tiers": [],
    }  # type: Dict[str, Any]
    write_report(output_path, report)

    try:
        for target_seconds, text in TIER_TEXTS.items():
            tier = {
                "target_seconds": target_seconds,
                "text_word_count": len(text.split()),
                "runs": [],
            }  # type: Dict[str, Any]
            report["tiers"].append(tier)

            for iteration in range(1, ITERATIONS + 1):
                request = {
                    "voice_id": VOICE_ID,
                    "text": text,
                    "model_id": MODEL_ID,
                    "output_format": OUTPUT_FORMAT,
                    "seed": 42,
                }
                tts_started = time.perf_counter()
                try:
                    native_audio = collect_audio(native.text_to_speech.convert(**request))
                    tts_ms = (time.perf_counter() - tts_started) * 1000.0
                    actual_seconds = probe_audio(native_audio).duration_seconds
                    run_result = {
                        "iteration": iteration,
                        "encode_disabled": {
                            "status": "PASS",
                            "latency_ms": round(tts_ms, 2),
                            "actual_audio_seconds": round(actual_seconds, 3),
                            "audio_bytes": len(native_audio),
                        },
                    }  # type: Dict[str, Any]
                except Exception as exc:
                    tts_ms = (time.perf_counter() - tts_started) * 1000.0
                    run_result = {
                        "iteration": iteration,
                        "encode_disabled": error_record(exc, tts_ms),
                        "encode_enabled": {
                            "status": "SKIP",
                            "reason": "encode-disabled TTS request failed",
                        },
                        "added_latency_ms": None,
                    }
                    tier["runs"].append(run_result)
                    write_report(output_path, report)
                    print(json.dumps({"target_seconds": target_seconds, **run_result}), flush=True)
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
                        "complete_latency_ms": round(tts_ms + encode_ms, 2),
                        "encode_latency_ms": round(encode_ms, 2),
                        "audio_bytes": len(encoded_audio),
                    }
                    run_result["added_latency_ms"] = round(encode_ms, 2)
                    run_result["increase_percent_vs_disabled"] = round(
                        encode_ms / tts_ms * 100.0, 2
                    )
                except Exception as exc:
                    encode_ms = (time.perf_counter() - encode_started) * 1000.0
                    run_result["encode_enabled"] = error_record(exc, encode_ms)
                    run_result["added_latency_ms"] = None
                    run_result["increase_percent_vs_disabled"] = None

                tier["runs"].append(run_result)
                write_report(output_path, report)
                print(json.dumps({"target_seconds": target_seconds, **run_result}), flush=True)

            successful_tts = [
                item for item in tier["runs"] if item["encode_disabled"]["status"] == "PASS"
            ]
            if successful_tts:
                tier["summary"] = summarize_tier(successful_tts)
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
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    destination = arguments.output or default_output_path()
    result = run(destination)
    print(json.dumps({"output_file": result["output_file"]}, indent=2))
