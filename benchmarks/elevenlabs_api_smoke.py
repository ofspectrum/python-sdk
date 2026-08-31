"""Run one live request for each supported ElevenLabs complete-audio endpoint.

This is a credentialed, quota-consuming smoke test, not a latency benchmark.
It loads ``.env`` from the repository root and prints no credentials.

Run:
    python -m benchmarks.elevenlabs_api_smoke
"""

import argparse
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Set

from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

from ofspectrum import Ofspectrum

VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
OUTPUT_FORMAT = "mp3_44100_128"
LONG_TEXT = (
    "This live integration check uses a sufficiently long audio sample for reliable "
    "watermark encoding. It verifies that ElevenLabs can generate a complete audio "
    "file, that the transparent OfSpectrum wrapper intercepts the response, and that "
    "the encoded audio returns through the same client method without changing the "
    "call structure expected by an existing application."
)


class SmokeSkip(Exception):
    pass


def collect_audio(response: Any) -> bytes:
    if isinstance(response, bytes):
        return response
    return b"".join(bytes(chunk) for chunk in response)


def create_test_video(path: Path, seconds: int = 12) -> None:
    """Create a tiny deterministic MP4 used only by video-to-music."""
    import av
    import numpy as np

    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("mpeg4", rate=1)
        stream.width = 320
        stream.height = 180
        stream.pix_fmt = "yuv420p"
        for index in range(seconds):
            pixels = np.zeros((180, 320, 3), dtype=np.uint8)
            pixels[:, :, 0] = min(255, index * 15)
            pixels[:, :, 1] = 48
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def run_case(name: str, operation: Callable[[], Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        audio = collect_audio(operation())
        if not audio:
            raise RuntimeError("endpoint returned empty audio")
        return {
            "endpoint": name,
            "status": "PASS",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "audio_bytes": len(audio),
        }
    except SmokeSkip as exc:
        return {
            "endpoint": name,
            "status": "SKIP",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "reason": str(exc),
        }
    except Exception as exc:
        return {
            "endpoint": name,
            "status": "FAIL",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            "error_type": type(exc).__name__,
            "reason": str(exc),
        }


def first_history_id(native: ElevenLabs, expected_text: str) -> str:
    response = native.history.list(page_size=10, sort_direction="desc")
    history = getattr(response, "history", None) or []
    for item in history:
        if getattr(item, "text", None) != expected_text:
            continue
        item_id = getattr(item, "history_item_id", None)
        if item_id:
            return item_id
    raise SmokeSkip("the controlled TTS smoke item was not found in recent history")


def first_voice_sample(native: ElevenLabs) -> tuple:
    voice = native.voices.get(VOICE_ID)
    samples = getattr(voice, "samples", None) or []
    for sample in samples:
        sample_id = getattr(sample, "sample_id", None)
        if sample_id:
            return VOICE_ID, sample_id
    raise SmokeSkip("the selected voice has no downloadable sample")


def first_conversation_id(native: ElevenLabs) -> str:
    response = native.conversational_ai.conversations.list(page_size=10)
    conversations = getattr(response, "conversations", None) or []
    if not conversations:
        raise SmokeSkip("the account has no existing ElevenLabs conversation")
    for conversation in conversations:
        conversation_id = getattr(conversation, "conversation_id", None)
        if conversation_id:
            return conversation_id
    raise SmokeSkip("existing conversations have no usable ID")


def require_credentials() -> None:
    required = ("ELEVENLABS_API_KEY", "OFSPECTRUM_API_KEY", "OFSPECTRUM_TOKEN_ID")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit("Missing required environment variable(s): " + ", ".join(missing))


def skip_account_audio(kind: str) -> Any:
    raise SmokeSkip(
        kind
        + " requires --include-account-audio because existing private audio would be sent to OfSpectrum"
    )


def run(
    *,
    include_account_audio: bool = False,
    only: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    require_credentials()

    native = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    wrapped = Ofspectrum(
        native,
        api_key=os.environ["OFSPECTRUM_API_KEY"],
        token_id=os.environ["OFSPECTRUM_TOKEN_ID"],
    )
    test_text = LONG_TEXT + " The unique smoke marker is " + uuid.uuid4().hex[:8] + "."
    source_path = Path(__file__).resolve().parents[1] / "examples/audio/sample-speech-like-12s.wav"
    source_audio = (source_path.name, source_path.read_bytes(), "audio/wav")
    selected: Optional[Set[str]] = set(only) if only else None
    results = []

    with tempfile.TemporaryDirectory(prefix="ofspectrum-elevenlabs-smoke-") as temp_dir:
        video_path = Path(temp_dir) / "input.mp4"
        create_test_video(video_path)
        source_video = (video_path.name, video_path.read_bytes(), "video/mp4")

        cases = [
            (
                "text_to_speech.convert",
                lambda: wrapped.text_to_speech.convert(
                    voice_id=VOICE_ID,
                    text=test_text,
                    model_id="eleven_multilingual_v2",
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "speech_to_speech.convert",
                lambda: wrapped.speech_to_speech.convert(
                    voice_id=VOICE_ID,
                    audio=source_audio,
                    model_id="eleven_multilingual_sts_v2",
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "text_to_sound_effects.convert",
                lambda: wrapped.text_to_sound_effects.convert(
                    text="A steady ocean shoreline with rolling waves and gentle wind",
                    duration_seconds=12.0,
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "text_to_dialogue.convert",
                lambda: wrapped.text_to_dialogue.convert(
                    inputs=[
                        {"voice_id": VOICE_ID, "text": LONG_TEXT},
                        {
                            "voice_id": VOICE_ID,
                            "text": "The second speaker confirms that the complete dialogue file is ready.",
                        },
                    ],
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "audio_isolation.convert",
                lambda: wrapped.audio_isolation.convert(audio=source_audio),
            ),
            (
                "music.compose",
                lambda: wrapped.music.compose(
                    prompt="A calm instrumental ambient track with soft piano and warm pads",
                    music_length_ms=12000,
                    force_instrumental=True,
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "music.video_to_music",
                lambda: wrapped.music.video_to_music(
                    videos=[source_video],
                    description="A calm instrumental background track",
                    output_format=OUTPUT_FORMAT,
                ),
            ),
            (
                "history.get_audio",
                lambda: wrapped.history.get_audio(first_history_id(native, test_text)),
            ),
            (
                "voices.samples.audio.get",
                (
                    lambda: wrapped.voices.samples.audio.get(*first_voice_sample(native))
                    if include_account_audio
                    else skip_account_audio("voice sample audio")
                ),
            ),
            (
                "conversational_ai.conversations.audio.get",
                (
                    lambda: wrapped.conversational_ai.conversations.audio.get(
                        first_conversation_id(native)
                    )
                    if include_account_audio
                    else skip_account_audio("conversation audio")
                ),
            ),
        ]

        try:
            for name, operation in cases:
                if selected is not None and name not in selected:
                    continue
                result = run_case(name, operation)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            wrapped.close()

    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("PASS", "FAIL", "SKIP")
    }
    return {"summary": counts, "results": results}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-account-audio",
        action="store_true",
        help=(
            "read an existing voice sample and conversation recording from the "
            "ElevenLabs account and send each to OfSpectrum for watermark encoding"
        ),
    )
    parser.add_argument(
        "--only",
        action="append",
        help="run only the named endpoint; repeat this option for multiple endpoints",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    report = run(
        include_account_audio=arguments.include_account_audio,
        only=arguments.only,
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    if report["summary"]["FAIL"]:
        raise SystemExit(1)
