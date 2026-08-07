# Changelog

## 1.2.0 - 2026-07-31

- Standard tokens no longer allow new private notebooks; existing private notebooks remain grandfathered.
- Limited Pro tokens to five private notebooks and Enterprise tokens to ten.
- Pro token creation now requires an explicit `public_key`.
- Added permanent account capacity from acquired tokens: 1 GiB for Standard, 6 GiB for Pro, and 11 GiB for Enterprise.
- Added token-level version-control and storage auto-expansion overrides, effective-setting fields, and permanent-capacity fields.
- Preserved omitted, `None`, `False`, and `True` distinctly when creating or updating token settings: omission leaves an update unchanged, `None` selects inheritance, and booleans explicitly disable or enable a setting.
- Documented whole-GiB allocation, immediate first-allocation charging, monthly renewal, successful-charge non-refund, payment-required restrictions, and the 24-hour unpaid reduction window.
- Updated `notebooks.get()` to return the current notebook revision and ordered media projection.
- Added revision-safe notebook save sessions: begin one session, stage multiple files with its `save_session_id`, inspect session or upload status, then cancel or commit the session.
- Changed existing-notebook `update`, `upload_media`, and `delete_media` helpers to read the authoritative complete projection and commit through one atomic save session; `delete_media` now requires the owning `note_id` so only the selected attachment is removed.
- Added UUID `save_batch_id` support for grouping independent notebook commits.
- Added typed save-session, staged-upload, cancellation, and commit results, plus typed notebook conflict, payment, validation, rate-limit, and availability exceptions.
- Raised notebook current media capacity to 500 files while preserving the 100 MiB per-file and 10 MiB UTF-8 text limits.
- Notebook media now accepts detected image, audio, and video content; SVG and unsupported bytes are rejected.
- Added stable notebook error codes for media validation, revision, save-session and idempotency conflicts, payment-required capacity, version-rate limits, and temporary unavailability.
- Documented full-snapshot version behavior and the 60-version-per-notebook rolling-hour and 500-version-per-account UTC-day limits.
- Owner history remains Web-only; SDK `1.2.0` does not provide history list, download, restore, or delete methods.
- Clarified that version history is not an independent file-backup service.

## 1.1.6

- Documented the notebook media upload constraints available in that release.
- Added SDK methods to list and create reusable AI authorization tags.
- Normalized legacy private notebook-limit responses in public SDK token models.

## 1.1.4

- Updated token documentation for Standard, Pro, and eligible Enterprise workflows.
- Clarified the recommended encode save workflow using `result.save()`.
- Clarified quota and notebook documentation with account-level wording.
- Removed default verification-key examples and internal implementation wording from public docs.

## 1.1.3

- Previous public SDK release.
