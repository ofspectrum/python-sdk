# OfSpectrum SDK Integration Guide

This guide helps teams build products or internal tools with the OfSpectrum Python SDK.

It covers SDK capabilities, token modeling choices, notebook/provenance patterns, security notes, and test flows. It also includes a prompt template for AI coding agents, such as Codex, after the integration requirements are clear.

## Repository Orientation for Agents

The public SDK repository is:

```text
https://github.com/ofspectrum/python-sdk
```

Customer applications should normally install the SDK with `pip install ofspectrum`; they should not need the private Neo monorepo source.

If an agent needs SDK source orientation, use the public SDK repository above. From that repository root, inspect these files first:

1. `README.md` for SDK installation, public examples, and user-facing usage.
2. `pyproject.toml` for package name, version, dependencies, and Python requirements.
3. `ofspectrum/` for the SDK client implementation, resource modules, exceptions, and return models.
4. `test_api.py` for a compact end-to-end usage example.
5. `examples/audio/` for local smoke-test audio files.

Use this guide for integration decisions and product modeling.
Use the public SDK `README.md` for package usage details.
Use SDK source and tests to verify method signatures, exception locations, return object shapes, and smoke-test flows.

Do not make the customer application depend on the SDK repository path at runtime. The application should depend on the installed `ofspectrum` package and `OFSPECTRUM_API_KEY`.

## Starter Prompt

If you are not sure how to start, copy this prompt into your AI coding agent first:

```text
I want to use the OfSpectrum Python SDK for audio watermarking.
I am either building a new product/tool or adding watermarking to an existing project — I will tell you which.

Please help me design the integration before writing code.
Ask me one question at a time.
Start by asking whether this is a new project or an existing codebase. If it is existing, ask about the current stack, the domain entities I already have, and where I already store data, so the integration maps onto what exists instead of adding a parallel structure.
After each answer, briefly explain what that choice means for token design, metadata, storage, or audio workflow.
Do not start implementation until the required choices are clear.

Use the OfSpectrum SDK integration guide as the source of truth.
```

## Prompt Template for AI Coding Agents

```text
You are helping design and build an application that uses the OfSpectrum Python SDK for audio watermarking.

Before writing code, first ask the user the integration questions below.
Ask one question at a time because the user may not know all choices upfront.
After each answer, briefly explain the implication, then ask the next question.
Do not ask the full checklist in one message unless the user explicitly requests it.
Do not infer or choose defaults unless the user explicitly asks you to proceed with defaults.
After the user answers, summarize the selected integration plan, then implement.

Use the official SDK package:

from ofspectrum import OfSpectrum

The application must use an API key created in the OfSpectrum dashboard. Do not implement API key creation in the customer app.

Ask these questions before implementation, one at a time:

1. Are you starting a new project or adding OfSpectrum to an existing codebase? If existing, describe the stack (language/framework), the primary domain entities you already have, where you currently store data, and how audio is handled today.
2. What is the application goal, or what does the existing app do and where should watermarking fit?
3. What is the primary entity that should be traceable: voice actor, project, audio asset, or something custom? For an existing project, map this onto an entity you already have.
4. Should each watermarked file get a unique token, or share a token with a voice actor/project/asset group?
5. Do you need a custom public verification key? If not, use Standard tokens.
6. What metadata should be public?
7. What metadata should be private and credential-gated?
8. Do you need to store license, provenance, or C2PA-like manifest files?
9. Should the app support encode only, decode lookup, streaming PCM encode, or all of them?
10. Where should token IDs, notebook IDs, media IDs, and file records be stored? For an existing project, prefer adding columns/relations to existing records rather than creating a parallel schema.
11. For a new project: what should be built (CLI app, web server, worker, API service, notebook script)? For an existing project: where in the current codebase should encode/decode/notebook calls be added (e.g. upload handler, publish step, background job, moderation pipeline)?

Recommended interview flow:

1. Start with new-vs-existing. For an existing codebase, capture the current stack, entities, and storage first.
2. Then the product goal, or where watermarking fits in the existing app.
3. Then decide token ownership, mapping onto existing entities when integrating.
4. Then decide public/private metadata and provenance needs.
5. Then decide audio workflows.
6. Then decide integration points, architecture, and storage — reuse existing storage for an existing project.
7. Only after those answers are clear, propose an implementation plan.

Project context:
- New project, or existing codebase?
- If existing: language/framework, existing domain entities, existing datastore, and how audio is handled today.

Application goal:
- [Describe the product or, for an existing app, what it does and where watermarking fits]

Token ownership model:
- Choose one:
  - One voice actor = one token
  - One project = one token
  - One audio asset = one token
  - Custom: [describe]

Token type policy:
- Use Standard tokens by default.
- Use Pro tokens only when the workflow needs a configurable public verification key.

Metadata/provenance model:
- Choose one:
  - Use notebooks for public/private metadata, provenance, license text, and attachments.
  - Custom: [describe]

Audio workflow:
- Choose one or more:
  - Encode uploaded audio files.
  - Decode suspect audio files.
  - Stream raw PCM audio into watermark encode.

Notebook workflow:
- Choose one or more:
  - Public notebook for metadata visible to anyone who resolves the token.
  - Private notebook protected by a credential.
  - Media attachments for manifests, images, licenses, or reference assets.

Implementation requirements:
- Store OFSPECTRUM_API_KEY in environment variables.
- Never hardcode API keys.
- Catch OfSpectrumError and its subclasses.
- Treat quota errors as customer-actionable errors.
- Keep token IDs and notebook IDs in the app database.
- For an existing project, reuse the current datastore and add references (e.g. ofs_token_id) to existing records instead of duplicating a parallel schema.
- Do not change existing auth, storage, or framework conventions more than the integration requires.
- Show clear, customer-facing error messages.
- Run the final smoke tests listed in this guide.

Build / integration:
- New project: [CLI app / web server / worker / API service / notebook script]
- Existing project: [where the SDK calls are added — e.g. upload endpoint, publish job, moderation pipeline]
- Language/framework:
- Storage/database (reuse existing when integrating):
- File upload/storage approach:
- Expected user flows:
```

## Before You Start

Create an API key in the OfSpectrum dashboard before building the app.

Recommended setup flow:

1. Open the OfSpectrum homepage.
2. Click the `Console` button on the right side of the homepage navigation bar.
3. Sign in or create an account.
   - Email signup/sign-in is supported.
   - Google sign-in is supported.
4. In the console, open `Audio Watermarking` from the left navigation.
5. Open `My Tokens`.
6. Click `API Keys` in the top-right area of the My Tokens page.
7. Click `Create API Key`.
8. Enter a key name and choose expiration period.
9. Submit the form and copy the generated API key immediately.
10. Store the key as an environment variable, for example `OFSPECTRUM_API_KEY`.

Important:

- The API key is shown only once after creation.
- Copy and store it immediately in a secure secret manager or environment variable.
- Do not put the API key in frontend browser code, screenshots, logs, git commits, or public issue trackers.

## Supported SDK Capabilities

### Client Setup

```python
import os
from ofspectrum import OfSpectrum

client = OfSpectrum(api_key=os.environ["OFSPECTRUM_API_KEY"])
```

Optional client settings:

```python
client = OfSpectrum(
    api_key=os.environ["OFSPECTRUM_API_KEY"],
    base_url="https://api.ofspectrum.com/api/v1",  # override only for testing
    timeout=120.0,                                  # seconds
)
```

`OfSpectrum` also works as a context manager (`with OfSpectrum(...) as client:`) so the underlying HTTP connection is closed cleanly.

An `AsyncOfSpectrum` client is also exported and used with `async with`. It is currently experimental: its resource methods (`client.tokens.list()`, etc.) still execute synchronously and emit a warning when called inside a running event loop. Prefer the synchronous `OfSpectrum` client for production until true async is available.

Customers must create API keys in the OfSpectrum dashboard. The SDK does not need to create or manage API keys.

### Tokens

Tokens are the primary routing unit for watermark identity. A token is embedded into audio during encode and returned during decode.

Supported SDK methods:

```python
client.tokens.list()
client.tokens.get(token_id)
client.tokens.create(
    name,
    token_type="standard",
    public_key=None,
    ai_auth_enabled=False,
    ai_auth_access_type=None,
    ai_auth_price=None,
    ai_auth_other_instructions=None,
    ai_auth_tags=None,
)
client.tokens.list_ai_auth_tags()
client.tokens.create_ai_auth_tag(tag)
client.tokens.update(
    token_id,
    name=None,
    public_key=None,
    token_type=None,
    enterprise_verification=None,
    ai_auth_enabled=None,
    ai_auth_access_type=None,
    ai_auth_price=None,
    ai_auth_other_instructions=None,
    ai_auth_tags=None,
)
```

Current public token types:

| Type | Use When |
|------|----------|
| `standard` | Default. Use when the app does not need a custom verification key. |
| `pro` | Use when the workflow needs a configurable `public_key`. |

Recommended behavior:

- Create Standard tokens by default.
- Create Pro tokens only when the customer explicitly needs a configurable verification key.
- Existing tokens can be upgraded from Standard to Pro, but cannot be downgraded.
- A token type upgrade may consume quota or incur a billing charge.
- Store token IDs in the customer app database.

### AI Authorization

Tokens can publish how AI systems are allowed to use the associated content.

Supported token fields:

| Field | Meaning |
|-------|---------|
| `ai_auth_enabled` | Enables or disables the AI authorization policy. |
| `ai_auth_access_type` | Optional access mode: `direct_use` or `premium_track`. |
| `ai_auth_price` | Optional price. When set, it must be at least `1`. |
| `ai_auth_other_instructions` | Additional human-readable usage instructions. |
| `ai_auth_tags` | Searchable labels associated with the policy. |

Use `client.tokens.create()` to configure these fields on a new token, or `client.tokens.update()` to modify them. Updating `ai_auth_tags` replaces the complete tag list; pass an empty list to remove all tags. Pass `ai_auth_price=None` explicitly to clear an existing price.

AI authorization tags are reusable account-level labels. Use
`client.tokens.list_ai_auth_tags()` to load existing choices and
`client.tokens.create_ai_auth_tag()` to create a new choice. Creating a tag
does not attach it to a token; pass its `tag` value in `ai_auth_tags` during
token create or update.

### Audio Encode

Use encode to embed a watermark into an audio file.

```python
result = client.audio.encode(
    audio="input.wav",
    token_id=token.id,
    strength=1.0,
    smooth=True,
)

result.save("watermarked.wav")
```

Use this for:

- Publishing watermarked audio.
- Tracking generated audio assets.
- Registering audio for later detection.

For local smoke tests, use the non-sine synthetic WAV files in `examples/audio`, such as `sample-speech-like-12s.wav` or `sample-broadband-10s.wav`.

Important: the SDK rejects already-watermarked audio with `WatermarkExistsError`; it does not overwrite an existing watermark. Store source and watermarked files separately.

Audio length note: very short clips may be rejected because some tokens require a minimum audio duration. Use the provided sample audio for smoke tests instead of short beeps or tiny fixtures.

### Audio Decode

Use decode to detect whether a file contains an OfSpectrum watermark.

```python
result = client.audio.decode("suspect.wav")

if result.watermarked:
    print(result.token_id)
```

Use `public_key` only when the workflow requires explicit verification key configuration:

```python
result = client.audio.decode("suspect.wav", public_key=258)
```

If a workflow requires `public_key` and the wrong key is provided, decode may return `watermarked=False` instead of raising an error. Treat this as a verification mismatch and check the token configuration.

### Streaming PCM Encode

Use streaming encode when the application already works with raw PCM audio.

```python
def chunks(pcm_bytes: bytes, size: int = 48000):
    for offset in range(0, len(pcm_bytes), size):
        yield pcm_bytes[offset:offset + size]

result = client.audio.stream_encode_pcm(
    pcm_chunks=chunks(pcm_f32le_bytes),
    token_id=token.id,
    sample_rate=48000,
    channels=1,
)
```

This method returns raw PCM bytes, not a WAV/MP3 container. The customer app must wrap or encode the result into the desired delivery format.

### Notebooks

Notebooks attach human-readable metadata and media to a token.

Supported SDK methods:

```python
client.notebooks.list(token_id)
client.notebooks.get(note_id)
client.notebooks.create(token_id, note_name, text_content=None, is_public=True, credential_val=None)
client.notebooks.update(note_id, note_name=None, text_content=None, credential_val=None)
client.notebooks.delete(note_id)
client.notebooks.upload_media(note_id, file, filename=None, media_type=None)
client.notebooks.list_media(note_id)
client.notebooks.get_media_url(media_id)
client.notebooks.download_media(media_id, output_path=None)
client.notebooks.delete_media(media_id)
```

Media helper notes:

- `upload_media` accepts a path, `Path`, or file object. `filename` and `media_type` are optional; when omitted the SDK derives them from the file. Any file type is accepted (see the media limits below).
- `get_media_url` returns a short-lived signed URL for a media file (useful for previews or handing a link to a browser).
- `download_media` returns the raw bytes, or writes to `output_path` and returns the path when provided.

Use notebooks for:

- Public provenance text.
- Private metadata gated by a credential.
- License information.
- Voice actor/profile descriptions.
- Project notes.
- Asset metadata.
- C2PA/provenance manifest drafts as text or attached JSON files.

Notebook visibility:

| Notebook Type | Behavior |
|---------------|----------|
| Public | Visible as public token metadata. |
| Private | Requires a credential and is limited by token/account configuration. |

Notebook limits:

| Token Type | Public Notebooks | Private Notebooks |
|------------|------------------|-------------------|
| `standard` | 1 | 1 |
| `pro` | 1 | Unlimited |
| `enterprise` | 1 | Unlimited |

Default naming:

- When using the SDK, pass an explicit `note_name`.
- If the raw API receives no notebook name, the backend falls back to `Public` for public notebooks and `Private` for private notebooks.
- Explicit names are recommended, for example `Public Provenance`, `Private License Details`, or `C2PA Manifest`.

Additional constraints:

- Notebook names must be unique under the same token.
- Private notebook credentials must be unique under the same token.
- Private notebook credentials are optional at the SDK level, but apps that need credential-gated private metadata should explicitly pass `credential_val`.
- Notebook media is intended for supporting files such as manifests, licenses, images, or small references. Each notebook accepts at most 10 files, each file may be up to 100 MB, and the combined media limit is 10 GB per notebook.
- Standard tokens support one private notebook. Existing Pro and Enterprise tokens have no private notebook limit.
- If a token already has a public notebook, update the existing notebook instead of creating another one.

### Quotas

Use quota methods to preflight customer actions and show actionable UI.

Supported SDK methods:

```python
client.quotas.get_encode_quota()                          # -> Quota
client.quotas.get_decode_quota()                          # -> Quota
client.quotas.check_encode_available(duration_seconds)    # -> bool
client.quotas.check_decode_available(duration_seconds)    # -> bool
```

```python
encode_quota = client.quotas.get_encode_quota()
decode_quota = client.quotas.get_decode_quota()

if client.quotas.check_encode_available(duration_seconds=300):
    client.audio.encode(audio="input.wav", token_id=token.id)
```

A `Quota` exposes `limit`, `used`, `remaining`, `used_percentage`, `is_exceeded`, and `reset_at`.

Show quota errors as customer-actionable messages in the application UI.

### Retry and Resilience

The SDK does not retry automatically. For flaky-network or rate-limited workloads, wrap calls with the exported retry helpers.

```python
from ofspectrum import RetryConfig, with_retry

@with_retry(RetryConfig(max_retries=3))
def encode_with_retry():
    return client.audio.encode(audio="input.wav", token_id=token.id)

result = encode_with_retry()
```

Behavior:

- `RetryConfig` supports `max_retries` (default 3), exponential backoff, and jitter.
- Retries only transient errors: `RateLimitError`, `ServiceUnavailableError`, and `NetworkError`. Other errors (auth, validation, quota, watermark-exists) are raised immediately.
- On `RateLimitError`, the helper waits for the server's `retry_after` when present.
- `with_retry` accepts an optional `on_retry(exception, attempt)` callback for logging.

Do not use retries to work around `QuotaExceededError` or `WatermarkExistsError`; those are customer-actionable, not transient.

## Token Modeling Patterns

Different products should choose different token granularity. This decision affects traceability, privacy, quota use, and how customers query provenance.

### Pattern A: One Voice Actor = One Token

Use when the app manages a catalog of licensed voices or voice actors.

Best for:

- Voice licensing.
- Voice actor identity tracking.
- AI voice marketplace workflows.
- Reuse across many generated files.

Recommended token name:

```text
voice_actor:{actor_id}:{display_name}
```

Recommended notebook structure:

- Public notebook:
  - Voice actor display profile.
  - Authorized use summary.
  - License summary.
- Private notebook:
  - Contract references.
  - Internal rights notes.
  - Verification credential.
- Media:
  - Profile image.
  - License PDF.
  - C2PA/provenance JSON draft.

Encode flow:

```python
token = get_or_create_voice_actor_token(actor_id)
encoded = client.audio.encode(audio=input_path, token_id=token.id)
```

Tradeoffs:

- Easy attribution to the actor.
- Less granular per-project tracking.
- Best when many assets share one rights identity.

### Pattern B: One Project = One Token

Use when the app groups many assets under a campaign, film, album, game, or customer project.

Best for:

- Agency/client projects.
- Production workflows.
- Project-level provenance.
- Batch asset tracking.

Recommended token name:

```text
project:{project_id}:{project_name}
```

Recommended notebook structure:

- Public notebook:
  - Project title.
  - Rights/contact statement.
  - Allowed use summary.
- Private notebook:
  - Internal project metadata.
  - Client contract notes.
  - Contributor mapping.
- Media:
  - Project license.
  - Rights manifest.
  - Reference assets.

Tradeoffs:

- Simple project-level management.
- Decode identifies the project, not necessarily the exact asset.
- Good default for studios and agencies.

### Pattern C: One Audio Asset = One Token

Use when every generated or uploaded audio asset needs unique traceability.

Best for:

- Asset registries.
- Dataset provenance.
- Per-file licensing.
- High-value content distribution.

Recommended token name:

```text
asset:{asset_id}:{filename_or_title}
```

Recommended notebook structure:

- Public notebook:
  - Asset title.
  - Creator/owner.
  - License summary.
  - Public provenance.
- Private notebook:
  - Private asset metadata.
  - Distribution history.
  - Customer/order ID.
- Media:
  - C2PA manifest JSON.
  - License file.
  - Cover/reference asset.

Tradeoffs:

- Maximum traceability.
- Higher token usage.
- Requires stronger customer app data modeling.

### Pattern D: Hybrid Token Model

Use when the app needs both identity-level and asset-level tracking.

Examples:

- One token per voice actor for standard content.
- One token per asset for premium/licensed releases.
- One token per project for drafts, one token per final asset for distribution.

Recommended agent behavior:

```text
If the asset is high-value or externally distributed, create/use an asset token.
Otherwise use the project or voice actor token.
```

## Metadata and C2PA/Provenance Strategy

The current SDK-supported way to attach metadata, license text, provenance details, or C2PA-like manifest files to a token is to use notebooks.

Example public provenance note:

```python
client.notebooks.create(
    token_id=token.id,
    note_name="Public Provenance",
    text_content="""
Creator: Example Studio
Asset ID: asset_123
License: Commercial use permitted
Generated with: Example Voice Model v2
Provenance: See attached manifest
""".strip(),
    is_public=True,
)
```

Attach a manifest:

```python
client.notebooks.upload_media(
    note_id=notebook.id,
    file="c2pa-manifest.json",
    media_type="application/json",
)
```

## Customer App Architecture

For a new project, create dedicated tables as shown below. For an existing project, prefer mapping these fields onto records you already have — for example, add `ofs_token_id` to an existing voice-actor/project/asset row and store notebook/media IDs alongside the related record — rather than adding a parallel schema.

Recommended app database tables (new project):

```text
ofs_tokens
- id
- ofs_token_id
- local_owner_type       # voice_actor, project, asset
- local_owner_id
- token_type
- public_key
- created_at

ofs_notebooks
- id
- ofs_note_id
- ofs_token_id
- purpose                # public_provenance, private_license, c2pa_manifest, profile
- is_public
- created_at

audio_assets
- id
- ofs_token_id
- source_file_path
- watermarked_file_path
- decode_status
- created_at
```

Recommended runtime flow:

1. Resolve or create the correct token for the selected modeling pattern.
2. Create/update notebooks for metadata and provenance.
3. Encode the audio with the token ID.
4. Store the token ID and output file reference in the customer app database.
5. Decode suspect files and use returned token ID to look up local metadata.

## SDK Behavior Notes

- API keys are created in the OfSpectrum dashboard, not through the SDK.
- Token IDs, notebook IDs, and media IDs should be stored in the customer app database.
- Standard tokens are the safest default for new workflows.
- Pro tokens are needed when the workflow requires a configurable `public_key` or unlimited private notebooks.
- The standard SDK encode flow refuses already-watermarked audio instead of overwriting the existing watermark.
- Decode returns a token ID when a watermark is detected; the customer app should use that token ID to look up its own local business metadata.
- Quota can change between a preflight check and the actual encode/decode call, so still handle quota errors from the final request.

## Error Handling Pattern

```python
from ofspectrum import (
    OfSpectrumError,
    AuthenticationError,
    QuotaExceededError,
    WatermarkExistsError,
)

try:
    result = client.audio.encode(audio="input.wav", token_id=token.id)
except QuotaExceededError:
    show_user_message("Quota exceeded. Please upgrade your plan or contact support.")
except AuthenticationError:
    show_user_message("Invalid OfSpectrum API key. Update your integration settings.")
except WatermarkExistsError:
    show_user_message("This audio already appears to contain a watermark.")
except OfSpectrumError as exc:
    show_user_message(f"OfSpectrum request failed: {exc.message}")
```

Show concise, customer-facing error messages rather than raw API payloads.

## Agent Implementation Checklist

Ask the customer these questions before coding:

1. New project or an existing codebase? If existing, what is the stack, what entities exist, and where is data stored today?
2. What is the primary entity that should be traceable: voice actor, project, or audio asset? Map onto an existing entity when integrating.
3. Should each watermarked file get a unique token, or share a token?
4. Do you need a custom public verification key? If not, use Standard tokens.
5. What metadata should be public?
6. What metadata should be private and credential-gated?
7. Do you need to store license/provenance/C2PA-like manifests?
8. Should the app support decode and lookup workflows?
9. Where should token IDs, notebook IDs, and file records be stored? Reuse existing storage when integrating.

Generate code only after these choices are clear.

## Final Test Flow

Ask the agent to run these checks after implementation. Use a staging or test API key when possible.

1. **Environment check**
   - Confirm `OFSPECTRUM_API_KEY` is set.
   - Confirm the app does not expose the API key to browser code or logs.

2. **Token check**
   - Create or select a test token.
   - Store the token ID in the customer app database.
   - Confirm `client.tokens.get(token.id)` returns the expected token.

3. **Notebook check**
   - Create one public notebook for the token.
   - Confirm creating a second public notebook is handled as a clear validation error.
   - Create one private notebook with a credential on a Standard token.
   - If using a Pro token, confirm multiple private notebooks can be created.
   - Upload a small manifest or license file as notebook media.
   - Confirm an eleventh media file is rejected.

4. **Encode/decode check**
   - Encode one sample audio file.
   - Save the watermarked output separately from the source file.
   - Decode the watermarked output.
   - Confirm `decoded.watermarked` is true and `decoded.token_id` matches the token used for encode.
   - Confirm short or invalid audio is handled as a clear validation error.
   - If the workflow uses `public_key`, test both the correct key and an incorrect key.

5. **Duplicate watermark check**
   - Try to encode the already-watermarked output again.
   - Confirm the app handles `WatermarkExistsError` and does not treat this as a successful overwrite.

6. **Quota and billing check**
   - Call `client.quotas.get_encode_quota()` before encode.
   - Run encode/decode.
   - Call quota again and confirm usage/remaining values changed as expected for the environment.
   - Confirm quota or balance failures show customer-facing messages.

7. **Lookup check**
   - Use the decoded token ID to load the token and notebooks.
   - Confirm the customer app can show the correct local voice actor, project, or audio asset metadata.

## Do Not Implement

- Do not create API keys inside the customer app. API keys are created in the OfSpectrum dashboard.
- Do not hardcode credentials, token IDs, or public keys.
- Do not place `OFSPECTRUM_API_KEY` in browser-side code.
- Do not assume encode overwrites an existing watermark.
- Do not create multiple public notebooks for the same token; update the existing public notebook instead.

## Minimal End-to-End Example

```python
import os
from ofspectrum import OfSpectrum

client = OfSpectrum(api_key=os.environ["OFSPECTRUM_API_KEY"])

token = client.tokens.create(
    name="asset:asset_123:trailer_voiceover",
    token_type="standard",
)

public_note = client.notebooks.create(
    token_id=token.id,
    note_name="Public Provenance",
    text_content="Owner: Example Studio\nLicense: Commercial use permitted",
    is_public=True,
)

client.notebooks.upload_media(
    note_id=public_note.id,
    file="c2pa-manifest.json",
    media_type="application/json",
)

encoded = client.audio.encode(
    audio="input.wav",
    token_id=token.id,
)
encoded.save("output.watermarked.wav")

decoded = client.audio.decode("output.watermarked.wav")
if decoded.watermarked:
    token = client.tokens.get(decoded.token_id)
    notebooks = client.notebooks.list(token_id=token.id)
    print(token.name)
    for notebook in notebooks:
        print(notebook.note_name)
```
