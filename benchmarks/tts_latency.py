"""Compare native TTS, paired watermark encode, and wrapped end-to-end latency.

Examples (run from the SDK directory after filling .env)::

    python -m benchmarks.tts_latency --provider gemini --model gemini-3.1-flash-tts-preview
    python -m benchmarks.tts_latency --provider gemini --gemini-endpoint interactions
    python -m benchmarks.tts_latency --provider google-cloud-tts
    python -m benchmarks.tts_latency --provider openai --model gpt-4o-mini-tts
    python -m benchmarks.tts_latency --provider openai --openai-endpoint chat --model gpt-audio-1.5
    python -m benchmarks.tts_latency --provider azure-speech --duration-tiers
    python -m benchmarks.tts_latency --provider azure-openai --duration-tiers
    python -m benchmarks.tts_latency --provider elevenlabs
    python -m benchmarks.tts_latency --provider gemini --duration-tiers

In the default mode, each iteration makes one native and one wrapped provider
request. Duration-tier mode makes one native request at each 5/10/30-second
text tier and then encodes those exact bytes. These calls consume provider and
OfSpectrum quota.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os
import statistics
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from ofspectrum import AzureSpeechTTS, Gemini, GoogleCloudTTS, OfSpectrum, Ofspectrum, OpenAITTS
from ofspectrum._tts import _encode_pcm
from ofspectrum.media import probe_audio

DEFAULT_TEXT = (
    "This sample measures the time required to generate speech and add an audio "
    "watermark. Each native result is encoded separately so the paired overhead "
    "is measured using the exact same generated audio."
)

TIER_TEXTS = {
    5: "This short sample measures watermark latency for a five second spoken audio clip.",
    10: (
        "This ten second sample measures the additional latency introduced by audio "
        "watermark encoding while keeping the voice, model, and output format unchanged."
    ),
    30: (
        "This thirty second benchmark sample measures watermark latency on a longer piece "
        "of generated speech. Every run uses the same voice, model, output format, and "
        "spoken content. First, the script records how long the provider takes to return "
        "the complete audio file. It then sends those exact audio bytes to OfSpectrum "
        "for watermark encoding. Using the same generated file for both measurements "
        "prevents normal variation between separate speech generations from being "
        "counted as watermark overhead."
    ),
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit("Missing required environment variable: " + name)
    return value


def _percentile(values: List[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(values: List[float]) -> Dict[str, float]:
    return {
        "average_ms": round(statistics.fmean(values) * 1000, 2),
        "p50_ms": round(_percentile(values, 0.5) * 1000, 2),
        "p95_ms": round(_percentile(values, 0.95) * 1000, 2),
    }


def _duration_seconds(provider: str, audio: bytes) -> float:
    # Gemini TTS returns headerless 24 kHz, mono, signed 16-bit PCM.
    if provider == "gemini":
        return len(audio) / (24000 * 2)
    return probe_audio(audio).duration_seconds


def _pool_input(provider: str, audio: bytes) -> bytes:
    """Return a playable file for StreamEncodePool.encode()."""
    if provider != "gemini":
        return audio
    if not audio or len(audio) % 2:
        raise ValueError("Gemini PCM must contain complete signed 16-bit samples")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(audio)
    return output.getvalue()


def _run_pool_comparison(
    args: argparse.Namespace, native: Any,
    timed_call: Callable[[Any], Tuple[float, bytes]],
    file_encode: Callable[[bytes], bytes], endpoint: str, request: Dict[str, str],
    iterations: int, warmups: int,
) -> Dict[str, Any]:
    """Compare file encode and a prewarmed pool on each identical TTS result."""
    pool_client = OfSpectrum(api_key=_required("OFSPECTRUM_API_KEY"))
    pool = pool_client.audio.open_stream_pool(
        _required("OFSPECTRUM_TOKEN_ID"), connections=1, timeout=900.0,
        keepalive_interval_seconds=120.0,
    )
    warm_started = time.perf_counter()
    if not pool.heartbeat(timeout=30.0):
        pool_client.close()
        raise RuntimeError("Stream encode pool could not establish a ready connection")
    pool_warmup = time.perf_counter() - warm_started

    def pooled_encode(audio: bytes) -> bytes:
        result = pool.encode(_pool_input(args.provider, audio), timeout=900.0)
        if not result.audio_bytes:
            raise ValueError("Pooled watermark encode returned no audio")
        return result.audio_bytes

    original_text = args.text
    tiers = []
    try:
        for target_seconds, text in TIER_TEXTS.items():
            args.text = text
            runs = []
            native_times = []
            file_times = []
            pool_times = []
            durations = []
            for _ in range(warmups):
                _, audio = timed_call(native)
                file_encode(audio)
                pooled_encode(audio)
            for iteration in range(1, iterations + 1):
                native_elapsed, audio = timed_call(native)
                actual_seconds = _duration_seconds(args.provider, audio)

                def timed_encode(encode: Callable[[bytes], bytes]) -> float:
                    started = time.perf_counter()
                    encoded = encode(audio)
                    elapsed = time.perf_counter() - started
                    if not encoded:
                        raise ValueError("Watermark encode returned no audio")
                    return elapsed

                # Alternate order so service drift does not systematically favor
                # either transport while both receive the exact same source bytes.
                if iteration % 2:
                    file_elapsed = timed_encode(file_encode)
                    pool_elapsed = timed_encode(pooled_encode)
                else:
                    pool_elapsed = timed_encode(pooled_encode)
                    file_elapsed = timed_encode(file_encode)

                native_times.append(native_elapsed)
                file_times.append(file_elapsed)
                pool_times.append(pool_elapsed)
                durations.append(actual_seconds)
                savings = file_elapsed - pool_elapsed
                runs.append({
                    "iteration": iteration,
                    "encode_order": "file,pool" if iteration % 2 else "pool,file",
                    "actual_audio_seconds": round(actual_seconds, 3),
                    "native_tts_ms": round(native_elapsed * 1000, 2),
                    "file_encode_ms": round(file_elapsed * 1000, 2),
                    "pooled_encode_ms": round(pool_elapsed * 1000, 2),
                    "file_total_ms": round((native_elapsed + file_elapsed) * 1000, 2),
                    "pooled_total_ms": round((native_elapsed + pool_elapsed) * 1000, 2),
                    "pooled_savings_ms": round(savings * 1000, 2),
                    "pooled_savings_percent": round(savings / file_elapsed * 100, 2),
                })
            tiers.append({
                "target_seconds": target_seconds,
                "text_word_count": len(text.split()),
                "runs": runs,
                "actual_audio_seconds": {
                    "average": round(statistics.fmean(durations), 3),
                    "min": round(min(durations), 3),
                    "max": round(max(durations), 3),
                },
                "native_tts": _summary(native_times),
                "file_encode": _summary(file_times),
                "pooled_encode": _summary(pool_times),
                "file_total": _summary([
                    native_elapsed + encode_elapsed
                    for native_elapsed, encode_elapsed in zip(native_times, file_times)
                ]),
                "pooled_total": _summary([
                    native_elapsed + encode_elapsed
                    for native_elapsed, encode_elapsed in zip(native_times, pool_times)
                ]),
                "pooled_savings": _summary([
                    file_elapsed - pool_elapsed
                    for file_elapsed, pool_elapsed in zip(file_times, pool_times)
                ]),
            })
    finally:
        args.text = original_text
        pool_client.close()
    return {
        "provider": args.provider,
        "endpoint": endpoint,
        "request": request,
        "methodology": (
            "one native TTS result per run; encode identical audio through the file API "
            "and a prewarmed persistent stream pool"
        ),
        "pool": {
            "connections": 1,
            "prewarmed_with_heartbeat": True,
            "warmup_ms_excluded_from_encode": round(pool_warmup * 1000, 2),
        },
        "iterations_per_tier": iterations,
        "warmups_per_tier": warmups,
        "tiers": tiers,
    }


def _run_duration_tiers(
    args: argparse.Namespace, native: Any,
    timed_call: Callable[[Any], Tuple[float, bytes]],
    encode: Callable[[bytes], bytes], endpoint: str, request: Dict[str, str],
    iterations: int, warmups: int,
) -> Dict[str, Any]:
    original_text = args.text
    tiers = []
    try:
        for target_seconds, text in TIER_TEXTS.items():
            args.text = text
            runs = []
            native_times = []
            encode_times = []
            durations = []
            for _ in range(warmups):
                _, audio = timed_call(native)
                encode(audio)
            for iteration in range(1, iterations + 1):
                native_elapsed, audio = timed_call(native)
                actual_seconds = _duration_seconds(args.provider, audio)
                started = time.perf_counter()
                encoded = encode(audio)
                encode_elapsed = time.perf_counter() - started
                if not encoded:
                    raise ValueError("Watermark encode returned no audio")
                native_times.append(native_elapsed)
                encode_times.append(encode_elapsed)
                durations.append(actual_seconds)
                runs.append({
                    "iteration": iteration,
                    "actual_audio_seconds": round(actual_seconds, 3),
                    "native_tts_ms": round(native_elapsed * 1000, 2),
                    "watermark_encode_ms": round(encode_elapsed * 1000, 2),
                    "native_plus_encode_ms": round((native_elapsed + encode_elapsed) * 1000, 2),
                })
            tiers.append({
                "target_seconds": target_seconds,
                "text_word_count": len(text.split()),
                "runs": runs,
                "actual_audio_seconds": {
                    "average": round(statistics.fmean(durations), 3),
                    "min": round(min(durations), 3),
                    "max": round(max(durations), 3),
                },
                "encode_disabled": _summary(native_times),
                "encode_enabled": _summary([
                    native_elapsed + encode_elapsed
                    for native_elapsed, encode_elapsed in zip(native_times, encode_times)
                ]),
                "added_by_encode": _summary(encode_times),
            })
    finally:
        args.text = original_text
    return {
        "provider": args.provider,
        "endpoint": endpoint,
        "request": request,
        "methodology": "native TTS, then encode the exact same audio bytes",
        "iterations_per_tier": iterations,
        "warmups_per_tier": warmups,
        "tiers": tiers,
    }


def _build(
    args: argparse.Namespace,
) -> Tuple[
    Any, Callable[[Any], Any], Callable[[Any], bytes], Callable[[bytes], bytes],
    str, Dict[str, str],
]:
    watermark_key = _required("OFSPECTRUM_API_KEY")
    token_id = _required("OFSPECTRUM_TOKEN_ID")
    provider = args.provider

    if provider == "elevenlabs":
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:
            raise SystemExit('Install the provider with pip install "ofspectrum[elevenlabs]"') from exc
        native = ElevenLabs(api_key=_required("ELEVENLABS_API_KEY"))
        wrapped = Ofspectrum(native, api_key=watermark_key, token_id=token_id)
        model = args.model or "eleven_multilingual_v2"
        voice = args.voice or "JBFqnCBsd6RMkjVDRZzb"

        def call(client: Any) -> Any:
            return client.text_to_speech.convert(
                text=args.text, voice_id=voice, model_id=model, output_format="mp3_44100_128"
            )

        def extract(result: Any) -> bytes:
            return b"".join(result)

        def encode(audio: bytes) -> bytes:
            return wrapped.watermark.encode_bytes(
                audio, filename="elevenlabs-output.mp3", transport="file"
            )

        return wrapped, call, extract, encode, "text_to_speech.convert", {
            "model": model, "voice": voice, "output_format": "mp3_44100_128",
        }

    if provider == "gemini":
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise SystemExit('Install the provider with pip install "ofspectrum[gemini]"') from exc
        native = genai.Client(api_key=_required("GEMINI_API_KEY"))
        wrapped = Gemini(native, api_key=watermark_key, token_id=token_id)
        model = args.model or "gemini-3.1-flash-tts-preview"
        voice = args.voice or "Kore"
        if args.gemini_endpoint == "interactions":

            def call(client: Any) -> Any:
                return client.interactions.create(
                    model=model, input=args.text, response_format={"type": "audio"},
                    generation_config={"speech_config": [{"voice": voice}]},
                )

            def extract(result: Any) -> bytes:
                return base64.b64decode(result.output_audio.data)

            endpoint = "interactions.create"
        else:

            def call(client: Any) -> Any:
                return client.models.generate_content(
                    model=model, contents=args.text,
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                            )
                        ),
                    ),
                )

            def extract(result: Any) -> bytes:
                return result.candidates[0].content.parts[0].inline_data.data

            endpoint = "models.generate_content"

        def encode(audio: bytes) -> bytes:
            return _encode_pcm(
                wrapped.watermark, audio, filename="gemini-output", transport="file"
            )

        return wrapped, call, extract, encode, endpoint, {
            "model": model, "voice": voice, "output_format": "pcm_24000_mono",
        }

    if provider == "google-cloud-tts":
        try:
            from google.cloud import texttospeech
        except ImportError as exc:
            raise SystemExit(
                'Install the provider with pip install "ofspectrum[google-cloud-tts]"'
            ) from exc
        cloud_key = os.environ.get("GOOGLE_CLOUD_TTS_API_KEY", "").strip()
        native = texttospeech.TextToSpeechClient(
            client_options={"api_key": cloud_key} if cloud_key else None
        )
        wrapped = GoogleCloudTTS(native, api_key=watermark_key, token_id=token_id)
        voice = args.voice or "en-US-Standard-A"

        def call(client: Any) -> Any:
            return client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=args.text),
                voice=texttospeech.VoiceSelectionParams(language_code="en-US", name=voice),
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3
                ),
            )

        def extract(result: Any) -> bytes:
            return result.audio_content

        def encode(audio: bytes) -> bytes:
            return wrapped.watermark.encode_bytes(
                audio, filename="google-cloud-tts-output.mp3", transport="file"
            )

        return wrapped, call, extract, encode, "synthesize_speech", {
            "model": "google-cloud-tts", "voice": voice, "output_format": "mp3",
        }

    if provider == "azure-speech":
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as exc:
            raise SystemExit(
                'Install the provider with pip install "ofspectrum[azure-speech]"'
            ) from exc
        speech_endpoint = os.environ.get("AZURE_SPEECH_ENDPOINT", "").strip()
        speech_location = (
            {"endpoint": speech_endpoint} if speech_endpoint
            else {"region": _required("AZURE_SPEECH_REGION")}
        )
        config = speechsdk.SpeechConfig(
            subscription=_required("AZURE_SPEECH_KEY"), **speech_location
        )
        voice = args.voice or "en-US-AvaNeural"
        config.speech_synthesis_voice_name = voice
        config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
        )
        native = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        wrapped = AzureSpeechTTS(native, api_key=watermark_key, token_id=token_id)

        def call(client: Any) -> Any:
            return client.speak_text(args.text)

        def extract(result: Any) -> bytes:
            return result.audio_data

        def encode(audio: bytes) -> bytes:
            return wrapped.watermark.encode_bytes(
                audio, filename="azure-speech-output.mp3", transport="file"
            )

        return wrapped, call, extract, encode, "speak_text", {
            "model": "azure-speech", "voice": voice, "output_format": "mp3",
        }

    if provider == "azure-openai":
        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise SystemExit('Install the provider with pip install "ofspectrum[openai-tts]"') from exc
        if getattr(args, "openai_endpoint", "speech") != "speech":
            raise SystemExit("Azure OpenAI benchmark supports the speech endpoint")
        native = AzureOpenAI(
            api_key=_required("AZURE_OPENAI_API_KEY"),
            azure_endpoint=_required("AZURE_OPENAI_ENDPOINT"),
            api_version=_required("AZURE_OPENAI_API_VERSION"),
        )
    else:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise SystemExit('Install the provider with pip install "ofspectrum[openai-tts]"') from exc
        native = OpenAI(api_key=_required("OPENAI_API_KEY"))
    wrapped = OpenAITTS(native, api_key=watermark_key, token_id=token_id)
    voice = args.voice or "alloy"
    if getattr(args, "openai_endpoint", "speech") == "chat":
        model = args.model or "gpt-audio-1.5"

        def call(client: Any) -> Any:
            return client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": args.text}],
                modalities=["text", "audio"],
                audio={"voice": voice, "format": "mp3"},
            )

        def extract(result: Any) -> bytes:
            return base64.b64decode(result.choices[0].message.audio.data)

        endpoint = "chat.completions.create"
    else:
        model = args.model or (
            _required("AZURE_OPENAI_TTS_DEPLOYMENT") if provider == "azure-openai"
            else "gpt-4o-mini-tts"
        )

        def call(client: Any) -> Any:
            return client.audio.speech.create(model=model, voice=voice, input=args.text)

        def extract(result: Any) -> bytes:
            return result.content

        endpoint = "audio.speech.create"

    def encode(audio: bytes) -> bytes:
        return wrapped.watermark.encode_bytes(
            audio, filename="openai-tts-output.mp3", transport="file"
        )

    return wrapped, call, extract, encode, endpoint, {
        "model": model, "voice": voice, "output_format": "mp3",
    }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise SystemExit("Install python-dotenv to load the SDK .env file") from exc
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    wrapped, call, extract, encode, endpoint, request = _build(args)
    native = wrapped.wrapped_client
    duration_tiers = bool(getattr(args, "duration_tiers", False))
    compare_pool = bool(getattr(args, "compare_pool", False))
    if compare_pool:
        duration_tiers = True
    iterations = args.iterations if args.iterations is not None else (3 if duration_tiers else 20)
    warmups = args.warmups if args.warmups is not None else (0 if duration_tiers else 2)
    native_times: List[float] = []
    wrapped_times: List[float] = []
    encode_times: List[float] = []

    def timed_call(client: Any) -> Tuple[float, bytes]:
        started = time.perf_counter()
        audio = extract(call(client))
        if not audio:
            raise ValueError("TTS provider returned no audio")
        return time.perf_counter() - started, audio

    if compare_pool:
        try:
            return _run_pool_comparison(
                args, native, timed_call, encode, endpoint, request, iterations, warmups
            )
        finally:
            wrapped.close()

    if duration_tiers:
        try:
            return _run_duration_tiers(
                args, native, timed_call, encode, endpoint, request, iterations, warmups
            )
        finally:
            wrapped.close()

    try:
        for _ in range(warmups):
            _, native_audio = timed_call(native)
            timed_call(wrapped)
            encode(native_audio)
        for index in range(iterations):
            if index % 2:
                wrapped_elapsed, _ = timed_call(wrapped)
                native_elapsed, native_audio = timed_call(native)
            else:
                native_elapsed, native_audio = timed_call(native)
                wrapped_elapsed, _ = timed_call(wrapped)
            started = time.perf_counter()
            encode(native_audio)
            encode_elapsed = time.perf_counter() - started
            native_times.append(native_elapsed)
            wrapped_times.append(wrapped_elapsed)
            encode_times.append(encode_elapsed)
    finally:
        wrapped.close()

    return {
        "provider": args.provider,
        "endpoint": endpoint,
        "request": request,
        "iterations": iterations,
        "warmups": warmups,
        "native_tts": _summary(native_times),
        "watermark_encode_only": _summary(encode_times),
        "paired_native_plus_encode": _summary(
            [native + encode for native, encode in zip(native_times, encode_times)]
        ),
        "wrapped_end_to_end": _summary(wrapped_times),
        "observed_wrapped_minus_native": _summary(
            [wrapped - native for wrapped, native in zip(wrapped_times, native_times)]
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", required=True,
        choices=("elevenlabs", "gemini", "google-cloud-tts", "openai",
                 "azure-speech", "azure-openai"),
    )
    parser.add_argument("--gemini-endpoint", choices=("generate-content", "interactions"),
                        default="generate-content")
    parser.add_argument("--openai-endpoint", choices=("speech", "chat"), default="speech")
    parser.add_argument("--model")
    parser.add_argument("--voice")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--duration-tiers", action="store_true",
                        help="run paired 5, 10, and 30 second text tiers")
    parser.add_argument("--compare-pool", action="store_true",
                        help="compare file encode with a prewarmed stream pool at each tier")
    parser.add_argument("--iterations", type=int,
                        help="runs per tier (default 3), or default 20 in single-text mode")
    parser.add_argument("--warmups", type=int,
                        help="warmups per tier (default 0), or default 2 in single-text mode")
    args = parser.parse_args()
    if ((args.iterations is not None and args.iterations < 1)
            or (args.warmups is not None and args.warmups < 0)):
        parser.error("iterations must be positive and warmups cannot be negative")
    return args


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), indent=2, sort_keys=True))
