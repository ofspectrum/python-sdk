"""
Notebooks resource for managing token notes
"""

import mimetypes
from pathlib import Path
from typing import (
    Any,
    BinaryIO,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Union,
)
from uuid import uuid4

from ..exceptions import OfSpectrumError, ValidationError, raise_for_error
from ..models.notebook import (
    Notebook,
    NotebookCreateParams,
    NotebookMedia,
    NotebookUpdateParams,
)
from ..models.notebook_version import (
    NotebookCommitMedia,
    NotebookCommitResponse,
    NotebookDesiredMedia,
    NotebookDesiredState,
)
from .base import BaseResource

_IMMUTABLE_DISABLED_CODES = {
    "immutable_write_disabled",
    "immutable_writes_disabled",
    "notebook_immutable_write_disabled",
    "notebook_immutable_writes_disabled",
}
_UNCHANGED = object()


class NotebooksResource(BaseResource):
    """Resource for managing watermark token notebooks (notes)"""

    def list(self, token_id: str) -> List[Notebook]:
        """
        List all notebooks for a specific token.

        Args:
            token_id: The token UUID

        Returns:
            List of Notebook objects. Summary responses that omit media expose
            ``Notebook.media`` as ``None`` rather than an authoritative empty list.

        Note:
            Use :meth:`get` when building a complete desired-state update; it
            returns the current revision and ordered media projection.

        Example:
            notebooks = client.notebooks.list(token_id="...")
            for nb in notebooks:
                print(f"{nb.note_name}: {nb.id}")
        """
        response = self._get(f"/watermark-notes?token_id={token_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns a direct list
        notes_data = data if isinstance(data, list) else data.get("data", {}).get("notes", [])
        return [Notebook.from_dict(n) for n in notes_data]

    def get(self, note_id: str) -> Notebook:
        """
        Get a specific notebook by ID.

        Args:
            note_id: The notebook UUID

        Returns:
            Notebook object

        Note:
            This side-effect-free request returns the current revision and the
            authoritative ordered media projection for desired-state workflows.
        """
        return self._fetch_notebook(note_id, require_authoritative=False)

    def _fetch_notebook(
        self,
        note_id: str,
        *,
        require_authoritative: bool,
    ) -> Notebook:
        response = self._get(f"/watermark-notes/{note_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns the note directly or wrapped in data
        note_data = (
            data
            if isinstance(data, dict) and "id" in data
            else data.get("data", {})
            if isinstance(data, dict)
            else None
        )
        if require_authoritative:
            return _authoritative_notebook(note_data, expected_note_id=note_id)
        try:
            return Notebook.from_dict(note_data)
        except (KeyError, TypeError, ValueError) as exc:
            raise _invalid_projection_response() from exc

    def create(
        self,
        token_id: str,
        note_name: str,
        text_content: Optional[str] = None,
        is_public: bool = True,
        credential_val: Optional[str] = None,
    ) -> Notebook:
        """
        Create a new notebook for a token.

        Args:
            token_id: The token UUID to attach the notebook to
            note_name: Notebook name/title
            text_content: Notebook content (markdown supported)
            is_public: Whether the notebook is publicly visible (default: True)
            credential_val: Optional credential for private notes

        Returns:
            Newly created Notebook object

        Example:
            notebook = client.notebooks.create(
                token_id="...",
                note_name="My Notes",
                text_content="Some content",
                is_public=True
            )
        """
        params = NotebookCreateParams(
            token_id=token_id,
            note_name=note_name,
            text_content=text_content,
            is_public=is_public,
            credential_val=credential_val,
        )

        response = self._post("/watermark-notes", data=params.to_dict())
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns the note directly
        note_data = data if isinstance(data, dict) and "id" in data else data.get("data", {})
        return Notebook.from_dict(note_data)

    def update(
        self,
        note_id: str,
        note_name: Optional[str] = None,
        text_content: Optional[str] = None,
        credential_val: Optional[str] = None,
    ) -> Notebook:
        """
        Update an existing notebook.

        Args:
            note_id: The notebook UUID
            note_name: New name/title (optional)
            text_content: New content (optional)
            credential_val: New password for private notes (optional)

        Returns:
            Updated Notebook object

        Note:
            is_public cannot be changed after creation.
        """
        params = NotebookUpdateParams(
            note_name=note_name,
            text_content=text_content,
            credential_val=credential_val,
        )

        update_data = params.to_dict()
        if not update_data:
            # Nothing to update; return the authoritative current projection.
            return self.get(note_id)

        current = self._fetch_notebook(note_id, require_authoritative=True)
        desired_state = _desired_state(
            current,
            note_name=(
                current.note_name
                if note_name is None or not note_name.strip()
                else note_name
            ),
            text_content=(current.text_content if text_content is None else text_content),
            credential_val=(
                current.credential_val
                if credential_val is None
                else credential_val or None
            ),
        )

        session_id = None
        try:
            commits = self._client.notebook_commits
            session = commits.begin(note_id, idempotency_key=str(uuid4()))
            session_id = session.save_session_id
            committed = commits.commit(
                note_id,
                desired_state=desired_state,
                expected_revision=_current_revision(current),
                idempotency_key=str(uuid4()),
                save_session_id=session_id,
                save_batch_id=uuid4(),
            )
            return _notebook_from_commit(current, desired_state, committed)
        except OfSpectrumError as exc:
            self._cancel_session(note_id, session_id)
            if _is_explicit_immutable_disabled(exc):
                return self._legacy_update(note_id, update_data)
            raise
        except Exception:
            self._cancel_session(note_id, session_id)
            raise

    def delete(self, note_id: str) -> bool:
        """
        Delete a notebook.

        Args:
            note_id: The notebook UUID

        Returns:
            True if deleted successfully
        """
        response = self._delete(f"/watermark-notes/{note_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return True

    def list_media(self, note_id: str) -> List[dict]:
        """
        List all media files attached to a notebook.

        Args:
            note_id: The notebook UUID

        Returns:
            List of media dicts with id, filename, media_type, etc.
        """
        response = self._get(f"/watermark-notes/{note_id}/media")
        data = response.json()
        raise_for_error(data, response.status_code)

        return data if isinstance(data, list) else []

    def upload_media(
        self,
        note_id: str,
        file: Union[str, Path, BinaryIO],
        filename: Optional[str] = None,
        media_type: Optional[str] = None,
    ) -> dict:
        """
        Upload a media file to a notebook.

        Args:
            note_id: The notebook UUID
            file: File path or file-like object
            filename: Optional filename (required if file is a file-like object)
            media_type: Optional MIME hint; the server detects the type from bytes

        Returns:
            Dict containing the committed media record

        Example:
            result = client.notebooks.upload_media(
                note_id="...",
                file="path/to/audio.mp3"
            )
            print(f"Uploaded: {result['id']}")

        Note:
            Existing notebook fields and ordered media are read first, then the
            file is staged once in one save session and committed as a complete
            desired state.
        """
        if isinstance(file, (str, Path)):
            path = Path(file)
            actual_filename = path.name
            with open(path, "rb") as f:
                _reject_obvious_svg(f)
        else:
            if not filename:
                raise ValidationError(
                    message="filename is required when uploading a file-like object",
                    code="InvalidNotebookMediaRequest",
                    status_code=400,
                    field="filename",
                    details={"field": "filename"},
                )
            actual_filename = filename
            _reject_obvious_svg(file)

        actual_media_type = media_type or _guess_media_type(actual_filename)
        initial_position = _stream_position(file)
        current = self._fetch_notebook(note_id, require_authoritative=True)
        retained_media = _desired_media(current.media or [])
        session_id = None
        stage_attempted = False
        try:
            commits = self._client.notebook_commits
            session = commits.begin(note_id, idempotency_key=str(uuid4()))
            session_id = session.save_session_id
            stage_attempted = True
            staged = commits.stage(
                note_id,
                session_id,
                file,
                filename=actual_filename,
                content_type=actual_media_type,
                idempotency_key=str(uuid4()),
            )
            desired_state = _desired_state(
                current,
                media=retained_media
                + (
                    NotebookDesiredMedia(
                        upload_id=staged.upload_id,
                        filename=staged.filename or actual_filename,
                        display_order=len(retained_media),
                    ),
                ),
            )
            committed = commits.commit(
                note_id,
                desired_state=desired_state,
                expected_revision=_current_revision(current),
                idempotency_key=str(uuid4()),
                save_session_id=session_id,
                save_batch_id=uuid4(),
            )
            _notebook_from_commit(current, desired_state, committed)
            uploaded = _committed_media_at(committed, len(retained_media))
            return _media_result(uploaded, note_id=note_id)
        except OfSpectrumError as exc:
            self._cancel_session(note_id, session_id)
            if _is_explicit_immutable_disabled(exc):
                if stage_attempted and not _restore_stream_position(
                    file, initial_position
                ):
                    raise
                return self._legacy_upload_media(
                    note_id,
                    file,
                    filename=filename,
                    media_type=media_type,
                )
            raise
        except Exception:
            self._cancel_session(note_id, session_id)
            raise

    def delete_media(self, media_id: str, note_id: Optional[str] = None) -> bool:
        """
        Delete a media file.

        Args:
            media_id: The media UUID
            note_id: The owning notebook UUID. Required so the SDK can fetch and
                preserve the complete authoritative notebook projection.

        Returns:
            True if deleted successfully

        Note:
            The atomic commit removes only ``media_id`` and retains every other
            media item in its current order.
        """
        if not isinstance(note_id, str) or not note_id.strip():
            raise ValidationError(
                message="note_id is required for an atomic notebook media delete",
                code="InvalidNotebookMediaRequest",
                status_code=400,
                field="note_id",
                details={"field": "note_id"},
            )

        current = self._fetch_notebook(note_id, require_authoritative=True)
        current_media = current.media or []
        if not any(item.id == media_id for item in current_media):
            raise ValidationError(
                message="media_id is not present in the current notebook projection",
                code="InvalidNotebookMediaRequest",
                status_code=400,
                field="media_id",
                details={"field": "media_id"},
            )

        retained = [item for item in current_media if item.id != media_id]
        desired_state = _desired_state(current, media=_desired_media(retained))
        session_id = None
        try:
            commits = self._client.notebook_commits
            session = commits.begin(note_id, idempotency_key=str(uuid4()))
            session_id = session.save_session_id
            committed = commits.commit(
                note_id,
                desired_state=desired_state,
                expected_revision=_current_revision(current),
                idempotency_key=str(uuid4()),
                save_session_id=session_id,
                save_batch_id=uuid4(),
            )
            _notebook_from_commit(current, desired_state, committed)
            return True
        except OfSpectrumError as exc:
            self._cancel_session(note_id, session_id)
            if _is_explicit_immutable_disabled(exc):
                return self._legacy_delete_media(media_id)
            raise
        except Exception:
            self._cancel_session(note_id, session_id)
            raise

    def _cancel_session(self, note_id: str, session_id: Optional[str]) -> None:
        if session_id is None:
            return
        try:
            self._client.notebook_commits.cancel(
                note_id,
                session_id,
                idempotency_key=str(uuid4()),
            )
        except Exception:
            # Preserve the original write error; abandoned sessions expire server-side.
            pass

    def _legacy_update(self, note_id: str, update_data: Dict[str, str]) -> Notebook:
        response = self._patch(f"/watermark-notes/{note_id}", data=update_data)
        data = response.json()
        raise_for_error(data, response.status_code)

        note_data = (
            data
            if isinstance(data, dict) and "id" in data
            else data.get("data", {})
            if isinstance(data, dict)
            else {}
        )
        return Notebook.from_dict(note_data)

    def _legacy_upload_media(
        self,
        note_id: str,
        file: Union[str, Path, BinaryIO],
        *,
        filename: Optional[str],
        media_type: Optional[str],
    ) -> dict:
        if isinstance(file, (str, Path)):
            path = Path(file)
            actual_filename = path.name
            actual_media_type = media_type or _guess_media_type(actual_filename)
            with open(path, "rb") as handle:
                _reject_obvious_svg(handle)
                response = self._post(
                    f"/watermark-notes/{note_id}/media",
                    files={"file": (actual_filename, handle)},
                    data={"media_type": actual_media_type},
                )
        else:
            if not filename:
                raise ValidationError(
                    message="filename is required when uploading a file-like object",
                    code="InvalidNotebookMediaRequest",
                    status_code=400,
                    field="filename",
                    details={"field": "filename"},
                )
            _reject_obvious_svg(file)
            response = self._post(
                f"/watermark-notes/{note_id}/media",
                files={"file": (filename, file)},
                data={"media_type": media_type or _guess_media_type(filename)},
            )

        data = response.json()
        raise_for_error(data, response.status_code)
        return data if isinstance(data, dict) else data.get("data", {})

    def _legacy_delete_media(self, media_id: str) -> bool:
        response = self._delete(f"/watermark-notes/media/{media_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return True

    def get_media_url(self, media_id: str) -> str:
        """
        Get a signed URL for accessing a media file.

        Args:
            media_id: The media UUID

        Returns:
            Signed URL string

        Note:
            The signed URL may have an expiration time.
        """
        response = self._get(f"/watermark-notes/media/{media_id}/signed-url")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns {"url": "..."} or {"data": {"url": "..."}}
        if isinstance(data, dict):
            return data.get("url", "") or data.get("data", {}).get("url", "")
        return ""

    def download_media(
        self,
        media_id: str,
        output_path: Optional[Union[str, Path]] = None,
    ) -> Union[bytes, str]:
        """
        Download a media file.

        Args:
            media_id: The media UUID
            output_path: Optional path to save the file. If provided,
                        saves to file and returns the path. If not,
                        returns the raw bytes.

        Returns:
            If output_path is provided: the output path as string
            Otherwise: the raw file bytes

        Example:
            # Download to file
            path = client.notebooks.download_media(
                media_id="...",
                output_path="downloaded.mp3"
            )

            # Download to memory
            content = client.notebooks.download_media(media_id="...")
        """
        response = self._get(f"/watermark-notes/media/{media_id}/download")

        if response.status_code != 200:
            try:
                data = response.json()
            except ValueError:
                data = None
            if data is not None:
                raise_for_error(data, response.status_code)
            raise OfSpectrumError(
                f"Download failed with status {response.status_code}",
                status_code=response.status_code,
            )

        content = response.content

        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
            return str(path)

        return content


def _authoritative_notebook(
    data: Any,
    *,
    expected_note_id: str,
) -> Notebook:
    required_fields = {
        "id",
        "token_id",
        "note_name",
        "text_content",
        "is_public",
        "credential_val",
        "revision",
        "media",
    }
    if not isinstance(data, Mapping) or not required_fields.issubset(data):
        raise _invalid_projection_response()
    if data.get("id") != expected_note_id:
        raise _invalid_projection_response()
    if not isinstance(data.get("token_id"), str):
        raise _invalid_projection_response()
    if not isinstance(data.get("note_name"), str):
        raise _invalid_projection_response()
    if data.get("text_content") is not None and not isinstance(data.get("text_content"), str):
        raise _invalid_projection_response()
    if not isinstance(data.get("is_public"), bool):
        raise _invalid_projection_response()
    if data.get("credential_val") is not None and not isinstance(
        data.get("credential_val"), str
    ):
        raise _invalid_projection_response()
    revision = data.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _invalid_projection_response()
    raw_media = data.get("media")
    if not isinstance(raw_media, list):
        raise _invalid_projection_response()

    media_ids = []
    for item in raw_media:
        if not isinstance(item, Mapping):
            raise _invalid_projection_response()
        media_id = item.get("id")
        if not isinstance(media_id, str) or not media_id.strip():
            raise _invalid_projection_response()
        media_ids.append(media_id)
    if len(media_ids) != len(set(media_ids)):
        raise _invalid_projection_response()

    try:
        return Notebook.from_dict(dict(data))
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_projection_response() from exc


def _invalid_projection_response() -> OfSpectrumError:
    return OfSpectrumError(
        message="Notebook service returned an incomplete current projection",
        code="InvalidNotebookProjectionResponse",
    )


def _current_revision(notebook: Notebook) -> int:
    revision = notebook.revision
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise _invalid_projection_response()
    return revision


def _desired_media(media: Sequence[NotebookMedia]) -> tuple:
    return tuple(
        NotebookDesiredMedia(
            media_id=item.id,
            filename=item.filename,
            display_order=index,
        )
        for index, item in enumerate(media)
    )


def _desired_state(
    current: Notebook,
    *,
    note_name: Any = _UNCHANGED,
    text_content: Any = _UNCHANGED,
    credential_val: Any = _UNCHANGED,
    media: Optional[Sequence[NotebookDesiredMedia]] = None,
) -> NotebookDesiredState:
    if current.media is None:
        raise _invalid_projection_response()
    return NotebookDesiredState(
        note_name=current.note_name if note_name is _UNCHANGED else note_name,
        text_content=current.text_content if text_content is _UNCHANGED else text_content,
        is_public=current.is_public,
        credential_val=(
            current.credential_val if credential_val is _UNCHANGED else credential_val
        ),
        media=_desired_media(current.media) if media is None else tuple(media),
    )


def _notebook_from_commit(
    current: Notebook,
    desired_state: NotebookDesiredState,
    committed: NotebookCommitResponse,
) -> Notebook:
    ordered = _complete_committed_media(committed, expected_count=len(desired_state.media))
    for expected, actual in zip(desired_state.media, ordered):
        if expected.media_id is not None and expected.media_id != actual.id:
            raise OfSpectrumError(
                message="Notebook commit service returned a mismatched media projection",
                code="InvalidNotebookCommitResponse",
            )
    return Notebook(
        id=current.id,
        token_id=current.token_id,
        note_name=desired_state.note_name or "",
        text_content=desired_state.text_content,
        is_public=desired_state.is_public,
        credential_val=desired_state.credential_val,
        media=[
            NotebookMedia(
                id=item.id,
                filename=item.filename,
                file_size=item.file_size_bytes,
                content_type=item.media_type,
                display_order=item.display_order,
            )
            for item in ordered
        ],
        created_at=current.created_at,
        updated_at=current.updated_at,
        revision=committed.resulting_revision,
    )


def _complete_committed_media(
    committed: NotebookCommitResponse,
    *,
    expected_count: int,
) -> List[NotebookCommitMedia]:
    ordered = sorted(committed.media, key=lambda item: item.display_order)
    if len(ordered) != expected_count or [item.display_order for item in ordered] != list(
        range(expected_count)
    ):
        raise OfSpectrumError(
            message="Notebook commit service returned an incomplete media projection",
            code="InvalidNotebookCommitResponse",
        )
    return ordered


def _committed_media_at(
    committed: NotebookCommitResponse,
    display_order: int,
) -> NotebookCommitMedia:
    ordered = _complete_committed_media(committed, expected_count=display_order + 1)
    return ordered[display_order]


def _media_result(media: NotebookCommitMedia, *, note_id: str) -> dict:
    return {
        "id": media.id,
        "note_id": note_id,
        "filename": media.filename,
        "media_type": media.media_type,
        "file_size_bytes": media.file_size_bytes,
        "display_order": media.display_order,
    }


def _guess_media_type(filename: str) -> str:
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


def _reject_obvious_svg(stream: Any) -> None:
    if not hasattr(stream, "tell") or not hasattr(stream, "seek"):
        return
    position = stream.tell()
    prefix = stream.read(8192)
    stream.seek(position)
    if not isinstance(prefix, bytes):
        return
    normalized = prefix.lstrip(b"\xef\xbb\xbf\x00\t\n\r ").lower()
    if normalized.startswith(b"<svg") or (
        normalized.startswith(b"<?xml") and b"<svg" in normalized
    ):
        raise ValidationError(
            message="SVG is not supported for notebook media",
            code="UnsupportedNotebookMedia",
            status_code=415,
            field="file",
            details={"field": "file"},
        )


def _stream_position(file: Union[str, Path, BinaryIO]) -> Optional[int]:
    if isinstance(file, (str, Path)) or not hasattr(file, "tell"):
        return None
    try:
        return file.tell()
    except (OSError, ValueError):
        return None


def _restore_stream_position(
    file: Union[str, Path, BinaryIO],
    position: Optional[int],
) -> bool:
    if isinstance(file, (str, Path)):
        return True
    if position is None or not hasattr(file, "seek"):
        return False
    try:
        file.seek(position)
        return True
    except (OSError, ValueError):
        return False


def _is_explicit_immutable_disabled(exc: OfSpectrumError) -> bool:
    candidates = [exc.code]
    details = exc.details if isinstance(exc.details, Mapping) else {}
    candidates.extend((details.get("code"), details.get("error")))
    nested = details.get("details")
    if isinstance(nested, Mapping):
        candidates.extend((nested.get("code"), nested.get("error")))

    return any(_normalize_error_code(value) in _IMMUTABLE_DISABLED_CODES for value in candidates)


def _normalize_error_code(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = []
    previous = ""
    for character in value.strip():
        if character.isupper() and previous and (
            previous.islower() or previous.isdigit()
        ):
            normalized.append("_")
        normalized.append(character.lower() if character.isalnum() else "_")
        previous = character
    return "_".join(filter(None, "".join(normalized).split("_")))
