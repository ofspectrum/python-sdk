# OfSpectrum Python SDK

Official Python SDK for the OfSpectrum audio watermarking API. This guide
describes the SDK `1.3.1` contract.

## Installation

```bash
pip install "ofspectrum==1.3.1"
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
print(f"Remaining encode quota: {quota.remaining}/{quota.limit} seconds")
```

## Building With AI Coding Agents

If you are building an app or internal tool with this SDK, see [AGENT_GUIDE.md](./AGENT_GUIDE.md). It explains token modeling patterns, notebook/provenance guidance, security notes, test flows, and includes a copyable prompt for AI coding agents such as Codex.

## Test Audio

Synthetic WAV files for encode/decode smoke tests are available in [`examples/audio`](./examples/audio). They contain no third-party audio and are intended for local SDK verification.

## Token Management

Standard tokens are the simplest option. Pro tokens support workflow-specific verification-key configuration.

Each acquired token also adds permanent notebook media capacity to its owner's
account:

| Token Type | Notebook Contract | Permanent Account Capacity |
|------------|-------------------|----------------------------|
| Standard | One public notebook; no new private notebooks (zero) | Permanent 1 GiB |
| Pro | One public notebook; five private notebooks | Permanent 6 GiB |
| Enterprise | One public notebook; ten private notebooks | Permanent 11 GiB |

Public SDK callers can create Standard and Pro tokens. Enterprise creation is
Admin-managed. Retiring a token does not remove its permanent capacity, and a
Standard-to-Pro upgrade replaces that token's 1 GiB entitlement with 6 GiB; it
does not add them together.

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

# Update a Pro token verification key.
token = client.tokens.update(
    token_id="token-uuid",
    public_key=verification_key,
)

# Upgrade an existing Standard token to Pro.
# Token types can be upgraded, but not downgraded.
token = client.tokens.update(
    token_id="token-uuid",
    token_type="pro",
    public_key=verification_key,
)

# Configure how the token may be used by AI systems.
token = client.tokens.update(
    token_id="token-uuid",
    ai_auth_enabled=True,
    ai_auth_access_type="direct_use",  # or "premium_track"
    ai_auth_price=5,
    ai_auth_other_instructions="Attribution required",
    ai_auth_tags=["voice", "licensed"],
)
```

Passing `ai_auth_price=None` clears the price. Passing `ai_auth_tags=[]` removes all AI authorization tags from the token.

Reusable AI authorization tags can be listed or created separately:

```python
tags = client.tokens.list_ai_auth_tags()
voice_tag = client.tokens.create_ai_auth_tag("Voice Clone")

client.tokens.update(
    token_id="token-uuid",
    ai_auth_tags=[voice_tag.tag],
)
```

Creating a tag does not attach it to a token. Pass the selected tag names to
`tokens.create()` or `tokens.update()` to associate them with a token.

Token deletion is not available via API. Tokens are consumable resources.

### Notebook Settings

SDK `1.2.0` token responses expose configured overrides, effective settings,
and permanent capacity:

```python
token = client.tokens.get("token-uuid")

print(token.version_control_override)      # None, True, or False
print(token.version_control_enabled)       # Effective boolean
print(token.storage_auto_expand_override)  # None, True, or False
print(token.storage_auto_expand_enabled)   # Effective boolean
print(token.storage_entitlement_bytes)     # Permanent capacity in bytes
```

Both `version_control_override` and `storage_auto_expand_override` preserve all
four call states:

| Value passed | `tokens.create()` | `tokens.update()` |
|--------------|-------------------|-------------------|
| Omitted | Make no token-level selection; account behavior applies. | Leave the current override unchanged. |
| `None` | Explicitly inherit the account default. | Clear the current override and inherit the account default. |
| `False` | Explicitly disable the setting for this token. | Explicitly disable the setting for this token. |
| `True` | Explicitly enable the setting for this token. | Explicitly enable the setting for this token. |

```python
# Explicitly enable version control for this token.
token = client.tokens.update(
    token_id="token-uuid",
    version_control_override=True,
)

# Return version control to the account default.
token = client.tokens.update(
    token_id="token-uuid",
    version_control_override=None,
)

# Explicitly disable both settings for this token.
token = client.tokens.update(
    token_id="token-uuid",
    version_control_override=False,
    storage_auto_expand_override=False,
)
```

You configure account defaults and authorize storage auto-expansion in the
OfSpectrum Web Console with a verified browser session. An API key cannot authorize
a transition that enables storage charges, including a transition to `None`
when the account default is enabled. Both account defaults are off until the
owner changes them.

When authorized auto-expansion is needed, capacity is allocated in whole 1 GiB
blocks and charged when a block is first allocated. Required blocks renew
monthly while the data needs them, even if auto-expansion is later disabled. A
successful charge is not refunded after media deletion. If renewal fails, data
remains available for read and deletion, but writes that add new media data are
blocked. Deleting media during the 24-hour unpaid reduction window can reduce
the unpaid requirement.

## Audio Watermarking

`client.audio.encode()` is the default OneFile integration: it sends one audio
file to `POST /audio/watermark/encode` and returns one encoded audio file. Omit
`interval` to leave the option unset, or pass `0.0` explicitly for continuous
placement. When the upload file does not carry a content type, the service
infers it from the filename when possible.

`response_format=stream` remains the backward-compatible binary audio-file
response. It is not the advanced streaming PCM integration. OneFile also
accepts `save_file`, `keep_original`, `check_watermark`, and
`verify_and_reencode`; they default to the previous SDK behavior and are
available when a customer needs storage, preflight, or verification control.

`smooth` is the same product option on file encode and streaming encode.

```python
result = client.audio.encode(
    audio="input.mp3",
    token_id=token.id,
    strength=1.0,
    smooth=True,
)
result.save("output.mp3")
if result.quality_warning:
    print("The output is ready, but watermark quality could not be fully verified.")

decode = client.audio.decode("suspect.mp3")
if decode.watermarked:
    print(f"Token: {decode.token_id}")
```

Use `decode(..., public_key=verification_key)` only when your workflow requires an explicit verification key.

## Advanced Streaming PCM Encode

Use `stream_encode()` for low-latency file encode. Installing the SDK includes
the media libraries, so a separate FFmpeg install is not required. Use
`stream_encode_pcm()` only when the application already has raw PCM.

```python
result = client.audio.stream_encode(
    audio=tts_wav_bytes,
    token_id=token.id,
    strength=1.0,
    smooth=True,
    interval=0.0,
    timeout=120.0,
)
encoded_file = result.audio_bytes

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
    timeout=900.0,
)

encoded_pcm = result.encoded_pcm
if result.quality_warning:
    print("The output is ready, but watermark quality could not be fully verified.")
print(f"Encoded {result.audio_duration:.2f}s of PCM")
```

`timeout` bounds the complete streaming session and defaults to 900 seconds.
`encoded_pcm` is raw PCM float32 little-endian, not WAV or MP3. Wrap it in a WAV container or encode it to your desired output format before playback or download.

### Persistent Stream Pool

For repeated mono 48 kHz file encodes, keep a small pool of persistent
connections open. The pool is synchronous and thread-safe: each connection
processes one encode at a time, while different callers can use different
connections concurrently. It reuses a stable opaque connection slot for each
connection and closes every created connection when either the pool or client
is closed.

```python
with client.audio.open_stream_pool(
    token_id=token.id,
    connections=2,
    sample_rate=48000,
    channels=1,
    strength=1.0,
    smooth=True,
    verify_and_reencode=True,
    keepalive_interval_seconds=120,
) as pool:
    result = pool.encode(tts_wav_bytes, timeout=120.0)
    result.save("watermarked.wav")
```

Pool configuration is fixed when it is opened. `pool.encode()` accepts a file
path, file object, or bytes and returns the same `EncodeResult` as
`stream_encode()`. The input channel count must match `channels`; use the
default mono configuration for EthoVox output. Set
`keepalive_interval_seconds` below Neo's idle window (300 seconds by default)
so every pooled connection stays warm without dummy audio. Completing
`admitted` / `ready` is the warmup. Before sending an operation, the SDK
probes an existing pooled connection and replaces it if it is stale. Once
operation input starts, the SDK never replays that operation automatically;
retry at the application level only when the workflow has an idempotency
boundary.

Real encode and decode traffic keeps Neo-to-model sessions alive. Heartbeats
only refresh idle tracking and do not consume encode quota. They cannot skip
hourly connection max-age rotation (`AUDIO_ENCODE_V2_CONNECTION_MAX_AGE_SECONDS`,
default 3600s) or the 40-minute persistent WebSocket rotation. For a long-lived
TTS worker, raise max-age (for example 86400) or accept a reconnect about once
an hour.

## Notebook Management

Attach notes and media files to tokens. Private notebooks require a credential, and limits depend on your account and token configuration.

Standard tokens cannot create new private notebooks. Existing Standard private notebooks are grandfathered and remain editable or deletable, but cannot be replaced after deletion. If a limit is reached, the SDK raises a `ValidationError` with a customer-facing message.

```python
notebook = client.notebooks.create(
    token_id=token.id,
    note_name="Release Notes",
    text_content="## Version 1.0\n\nRelease notes.",
    is_public=True,
)

# Private notebook creation requires a Pro or Enterprise token.
private_notebook = client.notebooks.create(
    token_id=token.id,
    note_name="Private Notes",
    text_content="Confidential content",
    is_public=False,
    credential_val="choose-a-secure-credential",
)

notebooks = client.notebooks.list(token_id=token.id)
```

Each notebook accepts up to 500 current media files, and each file may be up to
100 MiB. Notebook text may contain up to 10 MiB of UTF-8 data. Media uses the
account's available capacity from permanent token entitlements, legacy credit,
and any paid storage blocks. The server detects supported image, audio, and video
content from file bytes; SVG and unsupported bytes are rejected. Filenames and
submitted MIME values are hints only.

Keep original copies of important files. Notebook version history is not an
independent file-backup service.

For existing notebooks, `notebooks.update()`, `notebooks.upload_media()`, and
`notebooks.delete_media()` are atomic convenience methods. Each reads the
authoritative current revision and complete ordered media projection before it
writes. Unchanged name, text, visibility, and credential fields are retained;
an upload is staged once in one save session; and a media delete removes only
the selected ID. Pass the owning notebook ID when deleting media:

```python
client.notebooks.delete_media(
    media_id="media-uuid",
    note_id=notebook.id,
)
```

Do not build a desired state from `notebooks.list()` or a partial local cache.
Use `notebooks.get()` when constructing a manual commit. Notebook creation and
whole-notebook deletion continue to use `notebooks.create()` and
`notebooks.delete()` respectively.

### Revision-Safe Staged Saves

Use `client.notebook_commits` when one save changes text and media together.
First call `notebooks.get()`; unlike a list summary, it returns the current
revision and ordered media needed to build the complete desired state.
Current media exposes the API field names `media_type`, `file_size_bytes`, and
`display_order`; the legacy `content_type` and `file_size` aliases remain
available for compatibility.

The save-session methods return typed models:

| Method | Return type |
|--------|-------------|
| `begin(note_id, idempotency_key=...)` | `NotebookSaveSession` |
| `stage(note_id, save_session_id, file, idempotency_key=...)` | `NotebookStagedUpload` |
| `status(note_id, save_session_id)` | `NotebookSaveSessionStatus` |
| `upload_status(upload_id)` | `NotebookStagedUpload` |
| `cancel(note_id, save_session_id, idempotency_key=...)` | `NotebookSaveSessionCancellation` |
| `commit(note_id, ..., save_session_id=..., save_batch_id=...)` | `NotebookCommitResponse` |

Begin one session and reuse its `save_session_id` for every file in that logical
save:

```python
from uuid import uuid4

from ofspectrum import NotebookDesiredMedia, NotebookDesiredState

current = client.notebooks.get(notebook.id)
if current.revision is None or current.media is None:
    raise RuntimeError("The current notebook response is incomplete")

session = client.notebook_commits.begin(
    current.id,
    idempotency_key=str(uuid4()),
)

cover = client.notebook_commits.stage(
    current.id,
    session.save_session_id,
    file="cover.jpg",
    idempotency_key=str(uuid4()),
)
preview = client.notebook_commits.stage(
    current.id,
    session.save_session_id,
    file="preview.mp3",
    idempotency_key=str(uuid4()),
)

status = client.notebook_commits.status(
    current.id,
    session.save_session_id,
)
for upload in status.uploads:
    print(upload.filename, upload.state)

retained_media = tuple(
    NotebookDesiredMedia(
        media_id=media.id,
        filename=media.filename,
        display_order=index,
    )
    for index, media in enumerate(current.media)
)

desired_state = NotebookDesiredState(
    note_name=current.note_name,
    text_content="## Version 1.1\n\nUpdated release notes.",
    is_public=current.is_public,
    credential_val=current.credential_val,
    media=retained_media + (
        NotebookDesiredMedia(
            upload_id=cover.upload_id,
            filename="cover.jpg",
            display_order=len(retained_media),
        ),
        NotebookDesiredMedia(
            upload_id=preview.upload_id,
            filename="preview.mp3",
            display_order=len(retained_media) + 1,
        ),
    ),
)

save_batch_id = uuid4()
committed = client.notebook_commits.commit(
    note_id=current.id,
    desired_state=desired_state,
    expected_revision=current.revision,
    idempotency_key=str(uuid4()),
    save_session_id=session.save_session_id,
    save_batch_id=save_batch_id,
)
print(committed.resulting_revision)
for media in committed.media:
    print(media.display_order, media.filename)
```

Use `media_id` instead of `upload_id` in `NotebookDesiredMedia` to retain an
existing current file. Each entry requires exactly one of those IDs.

If the user abandons the save before commit, cancel that same session instead:

```python
cancelled = client.notebook_commits.cancel(
    current.id,
    session.save_session_id,
    idempotency_key=str(uuid4()),
)
print(cancelled.state, cancelled.released_bytes)
```

Cancel and commit are alternative terminal actions; do not cancel a session you
intend to commit.

A staged save follows this sequence:

1. Read the notebook with `notebooks.get()` and retain its current revision and
   ordered media.
2. Begin one save session.
3. Stage every new image, audio, or video with that session ID and a distinct
   idempotency key.
4. Check session status when you need to inspect all staged files.
5. Commit the complete desired notebook state with the same session ID, the
   revision from step 1, and a UUID `save_batch_id`; or cancel the session.
6. Reuse an operation's idempotency key only when retrying that exact operation.

Staging reserves capacity but does not allocate or charge a paid block. Commit
rechecks the complete desired state and applies any required charge atomically
with the notebook change.

The commit is atomic: it either applies the complete current state and returns a
new revision, or applies none of it. For a multi-notebook save, generate one UUID
`save_batch_id` and pass it to each independent notebook commit so one failed
notebook does not block the others.

### Version Control

When a token's effective version-control setting is enabled, a changed commit
creates a full notebook snapshot. Canonical no-op saves create no version and do
not consume a rate-limit unit.

Version rate limits are:

- 60 effective versions per notebook in a rolling hour.
- 500 effective versions per account per UTC day.
- There is no total historical version-count limit.
- API keys cannot access owner history. Owner history is available only in the
  Web Console; SDK `1.2.0` does not provide history list, download, restore, or
  delete methods.
- In the Web Console, restore creates a new version from the selected snapshot
  while preserving current visibility and credentials.
- You may delete individual versions in the Web Console, but at least one live
  version must remain for a versioned notebook.
- Disabling version control preserves existing history for viewing and download,
  but restore remains unavailable until version control is re-enabled.

## Quota Checking

```python
quota = client.quotas.get_encode_quota()
print(f"Remaining encode quota: {quota.remaining}/{quota.limit}")

decode_quota = client.quotas.get_decode_quota()
print(f"Remaining decode quota: {decode_quota.remaining}/{decode_quota.limit}")

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
    print(e.message)
except WatermarkExistsError:
    print("Audio already has a watermark")
except AuthenticationError:
    print("Invalid API key")
except OfSpectrumError as e:
    print(f"API error: {e.code} - {e.message}")
```

For notebook saves, branch on `e.code`; do not parse `e.message`. Stable notebook
codes map to typed SDK exceptions:

```python
from uuid import uuid4

from ofspectrum import (
    ConflictError,
    PaymentRequiredError,
    RateLimitError,
    ServiceUnavailableError,
    ValidationError,
)

try:
    committed = client.notebook_commits.commit(
        note_id=current.id,
        desired_state=desired_state,
        expected_revision=current.revision,
        idempotency_key=str(uuid4()),
        save_session_id=session.save_session_id,
        save_batch_id=uuid4(),
    )
except ConflictError as e:
    if e.code == "NotebookRevisionConflict":
        print("Reload the notebook before saving again")
    else:
        print(f"Save conflict: {e.code}")
except PaymentRequiredError as e:
    print(f"Storage action required: {e.code}")
except ValidationError as e:
    print(f"Invalid notebook save: {e.code}")
except RateLimitError as e:
    print(f"Save rate limited: {e.code}")
except ServiceUnavailableError as e:
    print(f"Save temporarily unavailable: {e.code}")
```

Key mappings include:

| Exception | Example stable codes |
|-----------|----------------------|
| `ConflictError` | `NotebookRevisionConflict`, `NotebookCommitIdempotencyConflict`, `NotebookStagedReferenceConflict`, `NotebookCommitConflict`, `NotebookSaveSessionConflict`, `NotebookSaveSessionRequired` |
| `PaymentRequiredError` | `NotebookStorageAutoExpandDisabled`, `NotebookStoragePaymentRequired`, `StorageChargeAuthorizationRequired` |
| `ValidationError` | `NotebookMediaTooLarge`, `NotebookMediaFileLimitExceeded`, `NotebookTextTooLarge`, `UnsupportedNotebookMedia`, `NotebookMediaHashMismatch`, `NotebookCommitValidationError`, `NotebookCommitPayloadTooLarge` |
| `RateLimitError` | `NotebookVersionRateLimitExceeded` |
| `ServiceUnavailableError` | `NotebookStorageUnavailable`, `NotebookCommitUnavailable` |

Local staged-commit argument validation raises `ValidationError` with
`code="InvalidNotebookCommitRequest"`. OfSpectrum still validates media,
capacity, revision, and rate limits when it processes the request.

## Context Manager

```python
with OfSpectrum(api_key="your_api_key") as client:
    tokens = client.tokens.list()
```
