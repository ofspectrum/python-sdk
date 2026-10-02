# TTS Encode

OfSpectrum TTS Encode generates speech through a supported provider, intercepts
the completed audio, encodes the existing OfSpectrum watermark, and returns the
encoded audio through one provider-neutral interface.

The provider still handles speech generation, authentication, model access,
voices, and billing. OfSpectrum handles the watermark step after the provider
returns a complete audio result.

## Processing Flow

```text
Application
    │
    │ TTS.synthesize(...)
    ▼
Provider adapter
    │ maps common arguments to the native SDK call
    ▼
TTS provider
    │ returns completed audio
    ▼
Existing OfSpectrum provider wrapper
    │ encodes the watermark through the persistent pool by default
    ▼
TTSResult
    └── audio: encoded bytes
```

The unified interface covers completed audio. Provider-native realtime and
streaming responses remain on their native interfaces because completed-file
watermarking requires the complete returned audio.

## Supported Providers

| Provider ID | Native client | Adapted native call | Status |
|-------------|---------------|---------------------|--------|
| `elevenlabs` | `ElevenLabs` | `text_to_speech.convert` | Supported |
| `gemini` | `google.genai.Client` | Gemini 3.1 `interactions.create`; Gemini 2.5 `models.generate_content` | Supported where the selected model is available |
| `google-cloud-tts` | `TextToSpeechClient` | `synthesize_speech` | Supported |
| `openai` | `OpenAI` or `AsyncOpenAI` | `audio.speech.create`; Chat Completions for `gpt-audio-*` | Supported |
| `azure-speech` | `SpeechSynthesizer` | Text synthesis or SSML synthesis | Supported |
| `azure-openai` | `AzureOpenAI` | Compatible `audio.speech.create` deployment | Adapter-compatible; not live-verified against an Azure OpenAI TTS resource |

Azure AI Speech and Azure OpenAI are separate services. A working Azure AI
Speech resource does not verify Azure OpenAI TTS availability.

## Installation

Install the OfSpectrum SDK with the extra for each provider used by the
application:

```bash
pip install "ofspectrum[elevenlabs]"
pip install "ofspectrum[gemini]"
pip install "ofspectrum[google-cloud-tts]"
pip install "ofspectrum[openai-tts]"
pip install "ofspectrum[azure-speech]"
```

Only the required provider extras need to be installed.

## Environment Variables

Every provider uses the existing OfSpectrum watermark credentials:

```bash
OFSPECTRUM_API_KEY=
OFSPECTRUM_TOKEN_ID=
```

Provider credentials remain configured on the provider's native SDK:

| Provider | Environment variables or credentials |
|----------|--------------------------------------|
| ElevenLabs | `ELEVENLABS_API_KEY` |
| Gemini | `GEMINI_API_KEY` |
| Google Cloud TTS | Application Default Credentials, or optional `GOOGLE_CLOUD_TTS_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Azure AI Speech | `AZURE_SPEECH_KEY` and either `AZURE_SPEECH_REGION` or `AZURE_SPEECH_ENDPOINT` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_TTS_DEPLOYMENT` |

Do not place provider or OfSpectrum API keys in browser code.

## Unified Quickstart

Construct the native provider client as usual, then pass it to `TTS`:

```python
from openai import OpenAI
from ofspectrum import TTS

with TTS("openai", OpenAI()) as tts:
    result = tts.synthesize(
        "Hello from one common interface",
        model="gpt-4o-mini-tts",
        voice="alloy",
        output_format="mp3",
    )

result.save("watermarked.mp3")
encoded_audio = result.audio
```

The provider client owns its normal connection and authentication settings.
The `api_key` argument on `TTS`, when supplied, is the OfSpectrum API key:

```python
tts = TTS(
    "openai",
    OpenAI(api_key=provider_api_key),
    api_key=ofspectrum_api_key,
    token_id=watermark_token_id,
)
```

## Common Method

```python
result = tts.synthesize(
    text,
    model=None,
    voice=None,
    output_format=None,
    language_code=None,
    endpoint=None,
    provider_options=None,
)
```

| Argument | Meaning |
|----------|---------|
| `text` | Required non-empty text to synthesize |
| `model` | Provider model ID or Azure OpenAI deployment name |
| `voice` | Provider voice name or ElevenLabs voice ID |
| `output_format` | Normalized requested format, such as `mp3`, `wav`, `ogg`, `pcm`, `m4a`, `ulaw`, or `alaw` where supported |
| `language_code` | Language used by Google Cloud voice selection and Azure SSML generation |
| `endpoint` | Optional endpoint selection, such as Gemini `interactions` / `generate-content` or OpenAI `speech` / `chat` |
| `provider_options` | Native provider parameters that are outside the common interface |

Provider APIs do not expose identical models or codecs. The adapter validates a
requested format when the provider gives the SDK that control. Gemini reports
the MIME type it actually returns. Azure AI Speech output format is configured
on `SpeechConfig` before the synthesizer is constructed.

## Common Result

Every unified call returns `TTSResult`:

```python
result.audio              # completed, encoded bytes with watermarking enabled
result.content            # alias for result.audio
result.provider           # normalized provider ID
result.output_format      # actual normalized result format
result.mime_type          # normalized MIME type
result.model              # resolved model or deployment, when applicable
result.voice              # resolved voice, when applicable
result.provider_response  # native provider response

result.save("output.mp3")
bytes(result)
```

`provider_response` remains available for provider metadata. For an
ElevenLabs iterator, the iterator has already been consumed to produce the
completed encoded bytes.

## Provider Examples

### ElevenLabs

`voice` is required. The default model is `eleven_multilingual_v2`, and the
default output is `mp3_44100_128`.

```python
from elevenlabs.client import ElevenLabs
from ofspectrum import TTS

with TTS("elevenlabs", ElevenLabs()) as tts:
    result = tts.synthesize(
        "Hello from ElevenLabs",
        voice="JBFqnCBsd6RMkjVDRZzb",
        model="eleven_multilingual_v2",
        output_format="mp3",
    )
```

Native ElevenLabs output format names can be passed through
`provider_options`:

```python
result = tts.synthesize(
    "Hello",
    voice="voice-id",
    provider_options={"output_format": "pcm_24000"},
)
```

### Google Gemini

Gemini 3.1 models default to `interactions.create`. Gemini 2.5 models default
to `models.generate_content`.

```python
from google import genai
from ofspectrum import TTS

with TTS("gemini", genai.Client()) as tts:
    result = tts.synthesize(
        "Say this cheerfully: Hello!",
        model="gemini-3.1-flash-tts-preview",
        voice="Kore",
    )
```

Select an endpoint explicitly when required:

```python
result = tts.synthesize(
    "Read this clearly",
    model="gemini-2.5-flash-preview-tts",
    voice="Kore",
    endpoint="generate-content",
)
```

The result format comes from the returned Gemini MIME metadata.

### Google Cloud Text-to-Speech

```python
from google.cloud import texttospeech
from ofspectrum import TTS

native = texttospeech.TextToSpeechClient()

with TTS("google-cloud-tts", native) as tts:
    result = tts.synthesize(
        "Hello from Google Cloud",
        voice="en-US-Standard-A",
        language_code="en-US",
        output_format="mp3",
    )
```

The adapter builds the native synthesis input, voice selection, and audio
configuration. Native call controls such as retry, timeout, and metadata can be
passed with `provider_options`.

### OpenAI

```python
from openai import OpenAI
from ofspectrum import TTS

with TTS("openai", OpenAI()) as tts:
    result = tts.synthesize(
        "Hello from OpenAI",
        model="gpt-4o-mini-tts",
        voice="alloy",
        output_format="mp3",
        provider_options={"speed": 1.05},
    )
```

Models whose names start with `gpt-audio` default to the Chat Completions audio
path. It can also be selected explicitly:

```python
result = tts.synthesize(
    "Say hello",
    model="gpt-audio-1.5",
    voice="alloy",
    output_format="wav",
    endpoint="chat",
)
```

OpenAI SSE speech output is outside the completed-file interface.

### Azure AI Speech

Configure the Azure output format before constructing the synthesizer. Use
`audio_config=None` so the completed in-memory result is the delivery path.

```python
import os
import azure.cognitiveservices.speech as speechsdk
from ofspectrum import TTS

speech_config = speechsdk.SpeechConfig(
    subscription=os.environ["AZURE_SPEECH_KEY"],
    region=os.environ["AZURE_SPEECH_REGION"],
)
speech_config.set_speech_synthesis_output_format(
    speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
)

native = speechsdk.SpeechSynthesizer(
    speech_config=speech_config,
    audio_config=None,
)

with TTS(
    "azure-speech",
    native,
    azure_output_format="audio-24khz-96kbitrate-mono-mp3",
) as tts:
    result = tts.synthesize(
        "Hello from Azure Speech",
        voice="en-US-AvaNeural",
        language_code="en-US",
        output_format="mp3",
    )
```

When `voice` is supplied, the adapter generates SSML for that call. A complete
custom SSML document can be passed as `provider_options={"ssml": ssml}`.

An Azure output sink may receive the native audio before the wrapper sees the
result. Read or save `TTSResult.audio` for the encoded bytes.

### Azure OpenAI Compatibility

Azure OpenAI uses the existing OpenAI adapter only when the Azure resource and
deployment expose a compatible `audio.speech.create` endpoint:

```python
import os
from openai import AzureOpenAI
from ofspectrum import TTS

native = AzureOpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
)

with TTS("azure-openai", native) as tts:
    result = tts.synthesize(
        "Hello from Azure OpenAI",
        model=os.environ["AZURE_OPENAI_TTS_DEPLOYMENT"],
        voice="alloy",
        output_format="mp3",
    )
```

This adapter is covered by mocked integration tests with the official
`AzureOpenAI` client and binary response type. It has not been verified with a
live Azure OpenAI TTS deployment. Model availability, endpoint availability,
regions, and API versions remain controlled by Azure.

## Advanced Provider Options

`provider_options` preserves provider-specific capabilities while keeping the
main method stable. Values present in the mapping take precedence over common
defaults where the native endpoint uses the same field.

```python
result = openai_tts.synthesize(
    "Speak slightly faster",
    voice="alloy",
    provider_options={"speed": 1.15},
)
```

For complex native request objects, use the provider's transparent wrapper when
that produces clearer application code.

## Asynchronous Calls

Use the same common arguments with `synthesize_async`:

```python
from openai import AsyncOpenAI
from ofspectrum import TTS

async with TTS("openai", AsyncOpenAI()) as tts:
    result = await tts.synthesize_async(
        "Hello asynchronously",
        model="gpt-4o-mini-tts",
        voice="alloy",
    )
```

For a synchronous provider client, `synthesize_async` runs the provider work in
an executor so it does not block the caller's event loop. Async ElevenLabs
completed-audio iterators are collected before one watermark encode.

## Persistent Connection Pool

The unified interface defaults to `transport="pool"`. The first completed-audio
call opens the matching OfSpectrum stream connection lazily. Repeated calls on
the same `TTS` instance reuse its matching persistent pool automatically:

```python
with TTS("openai", OpenAI()) as tts:
    first = tts.synthesize("First message")
    second = tts.synthesize("Second message")
```

Pools are keyed by watermark token, channel count, strength, smoothness, and
verification settings. Keep one `TTS` instance for the lifetime of a service or
worker, and close it during application shutdown.

Use the file endpoint explicitly when required:

```python
tts = TTS("openai", OpenAI(), transport="file")

# Or update an existing instance.
tts.watermark.config(transport="file")
```

A nonzero watermark `interval`, `check_watermark=True`, and raw A-law or μ-law
audio use the file endpoint because those options do not fit the pooled stream
protocol.

## Watermark Configuration

Watermark settings are passed when constructing `TTS` or updated through the
shared controller:

```python
tts = TTS(
    "openai",
    OpenAI(),
    token_id="token-uuid",
    strength=1.0,
    smooth=True,
    verify_and_reencode=True,
)

tts.watermark.config(
    strength=0.9,
    smooth=True,
    verify_and_reencode=True,
)
```

Configuration is read as a snapshot for each encode. Updating an instance while
a call is running affects subsequent calls.

## Transparent Provider Wrappers

The existing wrappers remain available when an application wants to preserve
the full native provider interface:

| Provider | Transparent wrapper |
|----------|---------------------|
| ElevenLabs | `Ofspectrum` |
| Gemini | `Gemini` |
| Google Cloud TTS | `GoogleCloudTTS` |
| OpenAI and compatible Azure OpenAI deployments | `OpenAITTS` |
| Azure AI Speech | `AzureSpeechTTS` |

The unified `TTS` interface uses these wrappers internally. Watermark encoding
logic is not duplicated.

## Latency Benchmark

The shared benchmark measures native TTS, encode-only latency on the exact
native result, and wrapped end-to-end latency.

Run approximate 5-, 10-, and 30-second tiers:

```bash
python -m benchmarks.tts_latency --provider elevenlabs --duration-tiers
python -m benchmarks.tts_latency --provider gemini --model gemini-3.1-flash-tts-preview --duration-tiers
python -m benchmarks.tts_latency --provider google-cloud-tts --duration-tiers
python -m benchmarks.tts_latency --provider openai --model gpt-4o-mini-tts --duration-tiers
python -m benchmarks.tts_latency --provider azure-speech --duration-tiers
```

Compare the OneFile endpoint with a prewarmed persistent pool:

```bash
python -m benchmarks.tts_latency \
    --provider openai \
    --model gpt-4o-mini-tts \
    --compare-pool
```

Pool warmup is reported separately and excluded from encode latency. Benchmark
runs call live provider and OfSpectrum APIs and consume their respective quota.

The Azure OpenAI benchmark requires a real Azure OpenAI TTS deployment and all
four `AZURE_OPENAI_*` variables. CLI support does not imply availability in
every Azure region or resource.

## Error Behavior

The unified interface validates common configuration before returning audio:

- Unknown providers and endpoints raise `ValueError`.
- Missing required voice or deployment values raise `ValueError`.
- Unsupported provider formats raise `ValueError` when they can be validated
  before the request.
- A synchronous call made with an asynchronous provider client raises
  `TypeError` and directs the caller to `synthesize_async`.
- Missing OfSpectrum credentials or token configuration raises
  `WatermarkConfigurationError` when encoding begins.
- Provider SDK authentication, quota, model, and network failures retain their
  native exception behavior.
- OfSpectrum encode failures retain the existing `OfSpectrumError` hierarchy.

With watermarking enabled (the default), the unified method passes completed
provider audio through the configured watermark wrapper before returning it.
