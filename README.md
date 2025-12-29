# OfSpectrum Python SDK

Official Python SDK for the OfSpectrum Audio Watermarking API.

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

# Initialize client with your API key
client = OfSpectrum(api_key="your_api_key")

# Create a watermark token (simple - uses "standard" type by default)
token = client.tokens.create(name="Production Token")
print(f"Created token: {token.id}")

# Or specify a type (creator/enterprise require public_key)
# token = client.tokens.create(
#     name="Creator Token",
#     token_type="creator",
#     public_key=12345
# )

# Encode watermark into audio
result = client.audio.encode(
    audio="input.mp3",
    token_id=token.id,
    output_path="watermarked.mp3"
)
print(f"Encoded {result.audio_duration}s of audio")

# Decode (detect) watermark from audio
decode = client.audio.decode("suspect.mp3")
if decode.watermarked:
    print(f"Watermark detected! Token ID: {decode.token_id}")
else:
    print("No watermark detected")

# Check your quota
quota = client.quotas.get_encode_quota()
print(f"Remaining encode quota: {quota.remaining}/{quota.quota_limit} seconds")
```

## Features

### Token Management

```python
# List all tokens
tokens = client.tokens.list()

# Get a specific token
token = client.tokens.get("token-uuid")

# Update a token
token = client.tokens.update(
    token_id="token-uuid",
    name="New Name"
)

# Note: Token deletion is not available via API.
# Tokens are consumable resources.
```

### Audio Watermarking

```python
# Encode with custom settings
result = client.audio.encode(
    audio="input.mp3",
    token_id=token.id,
    strength=1.0,          # 0.1-2.0
    normalize=True,         # Smooth audio to reduce artifacts
    check_watermark=True,   # Check for existing watermark first
    output_path="output.mp3"
)

# Decode watermark from audio file
decode = client.audio.decode("suspect.mp3")
if decode.watermarked:
    print(f"Token: {decode.token_id}")
```

### Notebook (Notes) Management

```python
# Create a public notebook for a token
notebook = client.notebooks.create(
    token_id=token.id,
    note_name="Release Notes",
    text_content="## Version 1.0\n\nInitial release.",
    is_public=True
)

# Create a private notebook (default password: "123")
private_nb = client.notebooks.create(
    token_id=token.id,
    note_name="Private Notes",
    text_content="Confidential content",
    is_public=False,
    credential_val="123"  # Optional, defaults to "123"
)

# Upload media to notebook
client.notebooks.upload_media(
    note_id=notebook.id,
    file="cover.jpg"
)

# List notebooks for a token
notebooks = client.notebooks.list(token_id=token.id)
```

### Quota Checking

```python
# Get all quotas
quotas = client.quotas.get_all()
for quota in quotas:
    print(f"{quota.service_name}: {quota.remaining}/{quota.quota_limit}")

# Check if encoding is available
if client.quotas.check_encode_available(duration_seconds=300):
    # Proceed with encoding
    pass
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
    print(f"Rate limited! Retry after {e.retry_after} seconds")
except QuotaExceededError as e:
    print(f"Quota exceeded for {e.service}")
except WatermarkExistsError:
    print("Audio already has a watermark!")
except AuthenticationError:
    print("Invalid API key")
except OfSpectrumError as e:
    print(f"API error: {e.code} - {e.message}")
```

## Retry Logic

```python
from ofspectrum import OfSpectrum, RetryConfig, with_retry

# Use built-in retry decorator
@with_retry(RetryConfig(max_retries=3))
def encode_with_retry():
    return client.audio.encode(...)

# Or configure retry globally
config = RetryConfig(
    max_retries=5,
    initial_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
    jitter=True
)
```

## Context Manager

```python
# Recommended: Use context manager for automatic cleanup
with OfSpectrum(api_key="your_api_key") as client:
    tokens = client.tokens.list()
```

## Configuration

```python
client = OfSpectrum(
    api_key="your_api_key",
    base_url="https://api.ofspectrum.com/api/v1",  # Optional: custom base URL
    timeout=120.0  # Optional: request timeout in seconds
)
```

## Requirements

- Python 3.8+
- httpx >= 0.24.0

## License

MIT License
