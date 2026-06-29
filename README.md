# OfSpectrum Python SDK

Official Python SDK for the OfSpectrum audio watermarking API.

## Installation

```bash
pip install ofspectrum
```

Or install from source:

```bash
pip install -e /path/to/neo/sdk
```

## Quick Start

```python
from ofspectrum import OfSpectrum

client = OfSpectrum(api_key="your_api_key")

# Create a Standard token.
token = client.tokens.create(name="Production Token")
print(f"Created token: {token.id}")

# Encode and save watermarked audio.
result = client.audio.encode(
    audio="input.mp3",
    token_id=token.id,
)
result.save("watermarked.mp3")
print(f"Encoded {result.audio_duration}s of audio")

# Decode watermark from audio.
decode = client.audio.decode("suspect.mp3")
if decode.watermarked:
    print(f"Watermark detected. Token ID: {decode.token_id}")
else:
    print("No watermark detected")

# Check your quota.
quota = client.quotas.get_encode_quota()
print(f"Remaining encode quota: {quota.remaining}/{quota.quota_limit} seconds")
```

## Token Management

Standard tokens are the simplest option. Pro tokens support workflow-specific verification-key configuration. Enterprise token configuration is available for eligible enterprise accounts or existing enterprise tokens.

```python
import os

# List all tokens.
tokens = client.tokens.list()

# Get a specific token.
token = client.tokens.get("token-uuid")

# Create a Pro token when your workflow requires a configurable verification key.
verification_key = int(os.environ["OFSPECTRUM_PUBLIC_KEY"])
token = client.tokens.create(
    name="Pro Token",
    token_type="pro",
    public_key=verification_key,
)

# Update a token name.
token = client.tokens.update(
    token_id="token-uuid",
    name="New Name",
)

# Update a Pro or eligible Enterprise token verification key.
token = client.tokens.update(
    token_id="token-uuid",
    public_key=verification_key,
)
```

Token deletion is not available via API. Tokens are consumable resources.

## Audio Watermarking

```python
result = client.audio.encode(
    audio="input.mp3",
    token_id=token.id,
    strength=1.0,
    smooth=True,
)
result.save("output.mp3")

decode = client.audio.decode("suspect.mp3")
if decode.watermarked:
    print(f"Token: {decode.token_id}")
```

Use `decode(..., public_key=verification_key)` only when your workflow requires an explicit verification key.

## Streaming PCM Encode

Use `stream_encode_pcm()` when your application already works with raw PCM audio or needs low-latency streaming from a file-processing pipeline, microphone, call, meeting, or live stream.

The input must be raw PCM float32 little-endian bytes. 48 kHz mono is recommended. The SDK does not currently decode MP3/WAV/FLAC files, resample audio, or convert containers for this streaming method.

```python
def chunk_pcm(pcm_bytes: bytes, chunk_seconds: float = 0.5):
    sample_rate = 48000
    channels = 1
    bytes_per_second = sample_rate * channels * 4
    chunk_size = int(bytes_per_second * chunk_seconds)
    for offset in range(0, len(pcm_bytes), chunk_size):
        yield pcm_bytes[offset:offset + chunk_size]

result = client.audio.stream_encode_pcm(
    pcm_chunks=chunk_pcm(pcm_f32le_bytes),
    token_id=token.id,
    sample_rate=48000,
    channels=1,
    smooth=True,
)

encoded_pcm = result.encoded_pcm
print(f"Encoded {result.audio_duration:.2f}s of PCM")
```

`encoded_pcm` is raw PCM float32 little-endian, not WAV or MP3. Wrap it in a WAV container or encode it to your desired output format before playback or download.

## Notebook Management

Attach notes and media files to tokens. Private notebooks require a credential, and limits depend on your account and token configuration.

```python
notebook = client.notebooks.create(
    token_id=token.id,
    note_name="Release Notes",
    text_content="## Version 1.0\n\nRelease notes.",
    is_public=True,
)

private_notebook = client.notebooks.create(
    token_id=token.id,
    note_name="Private Notes",
    text_content="Confidential content",
    is_public=False,
    credential_val="choose-a-secure-credential",
)

client.notebooks.upload_media(
    note_id=notebook.id,
    file="cover.jpg",
)

notebooks = client.notebooks.list(token_id=token.id)
```

## Quota Checking

```python
quota = client.quotas.get_encode_quota()
print(f"Remaining encode quota: {quota.remaining}")

decode_quota = client.quotas.get_decode_quota()
print(f"Remaining decode quota: {decode_quota.remaining}")

if client.quotas.check_encode_available(duration_seconds=300):
    result = client.audio.encode(audio="input.mp3", token_id=token.id)
```

## Error Handling

```python
from ofspectrum import (
    OfSpectrumError,
    AuthenticationError,
    RateLimitError,
    QuotaExceededError,
    WatermarkExistsError,
    ResourceNotFoundError,
)

try:
    result = client.audio.encode(audio="input.mp3", token_id="...")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except QuotaExceededError as e:
    print(f"Quota exceeded for {e.service}")
except WatermarkExistsError:
    print("Audio already has a watermark")
except AuthenticationError:
    print("Invalid API key")
except OfSpectrumError as e:
    print(f"API error: {e.code} - {e.message}")
```

## Context Manager

```python
with OfSpectrum(api_key="your_api_key") as client:
    tokens = client.tokens.list()
```
