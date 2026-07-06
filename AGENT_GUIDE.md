# OfSpectrum SDK Integration Guide

This guide helps teams build products or internal tools with the OfSpectrum Python SDK.

It covers SDK capabilities, token modeling choices, notebook/provenance patterns, security notes, and test flows. It also includes a prompt template for AI coding agents, such as Codex, after the integration requirements are clear.

## Prompt Template for AI Coding Agents

```text
You are building an application that uses the OfSpectrum Python SDK for audio watermarking.

Use the official SDK package:

from ofspectrum import OfSpectrum

The application must use an API key created in the OfSpectrum dashboard. Do not implement API key creation in the customer app.

Application goal:
- [Describe the product, e.g. voice marketplace, project collaboration app, audio asset registry, licensing workflow]

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
- Show clear, customer-facing error messages.
- Run the final smoke tests listed in this guide.

Build:
- [CLI app / web server / worker / API service / notebook script]
- Language/framework:
- Storage/database:
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

Customers must create API keys in the OfSpectrum dashboard. The SDK does not need to create or manage API keys.

### Tokens

Tokens are the primary routing unit for watermark identity. A token is embedded into audio during encode and returned during decode.

Supported SDK methods:

```python
client.tokens.list()
client.tokens.get(token_id)
client.tokens.create(name, token_type="standard", public_key=None)
client.tokens.update(token_id, name=None, public_key=None)
```

Current public token types:

| Type | Use When |
|------|----------|
| `standard` | Default. Use when the app does not need a custom verification key. |
| `pro` | Use when the workflow needs a configurable `public_key`. |

Recommended behavior:

- Create Standard tokens by default.
- Create Pro tokens only when the customer explicitly needs a configurable verification key.
- Store token IDs in the customer app database.

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
client.notebooks.create(token_id, note_name, text_content, is_public=True, credential_val=None)
client.notebooks.update(note_id, note_name=None, text_content=None, credential_val=None)
client.notebooks.delete(note_id)
client.notebooks.upload_media(note_id, file)
client.notebooks.list_media(note_id)
client.notebooks.download_media(media_id, output_path=None)
client.notebooks.delete_media(media_id)
```

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
| `standard` | 1 | 0 |
| `pro` | 1 | 1 |

Default naming:

- When using the SDK, pass an explicit `note_name`.
- If the raw API receives no notebook name, the backend falls back to `Public` for public notebooks and `Private` for private notebooks.
- Explicit names are recommended, for example `Public Provenance`, `Private License Details`, or `C2PA Manifest`.

Additional constraints:

- Notebook names must be unique under the same token.
- Private notebook credentials must be unique under the same token.
- Private notebook credentials are optional at the SDK level, but apps that need credential-gated private metadata should explicitly pass `credential_val`.
- Notebook media is intended for supporting files such as manifests, licenses, images, or small references. Avoid large assets; the default total media limit is 100 MB per notebook.
- If a customer app needs private metadata, use a Pro token.
- If a token already has a public notebook, update the existing notebook instead of creating another one.

### Quotas

Use quota methods to preflight customer actions and show actionable UI.

```python
encode_quota = client.quotas.get_encode_quota()
decode_quota = client.quotas.get_decode_quota()

if client.quotas.check_encode_available(duration_seconds=300):
    client.audio.encode(audio="input.wav", token_id=token.id)
```

Show quota errors as customer-actionable messages in the application UI.

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

Recommended app database tables:

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
- Pro tokens are needed when the workflow requires a configurable `public_key` or private notebook metadata.
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

1. What is the primary entity that should be traceable: voice actor, project, or audio asset?
2. Should each watermarked file get a unique token, or share a token?
3. Do you need a custom public verification key? If not, use Standard tokens.
4. What metadata should be public?
5. What metadata should be private and credential-gated?
6. Do you need to store license/provenance/C2PA-like manifests?
7. Should the app support decode and lookup workflows?
8. Where should token IDs, notebook IDs, and file records be stored locally?

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
   - If using Pro tokens, create one private notebook with a credential.
   - Confirm Standard tokens do not allow private notebooks.
   - Upload a small manifest or license file as notebook media.

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
