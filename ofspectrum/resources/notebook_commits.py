"""Transport helpers for revision-safe notebook save sessions."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any, BinaryIO, Callable, Dict, Mapping, Optional, TypeVar, Union
from urllib.parse import quote
from uuid import UUID

from ..exceptions import OfSpectrumError, ValidationError, raise_for_error
from ..models.notebook_version import (
    NotebookCommitResponse,
    NotebookDesiredState,
    NotebookSaveSession,
    NotebookSaveSessionCancellation,
    NotebookSaveSessionStatus,
    NotebookStagedUpload,
)
from .base import BaseResource

FileInput = Union[str, Path, BinaryIO]
UUIDInput = Union[str, UUID]
ResultModel = TypeVar("ResultModel")

_NOTEBOOKS_PATH = "/watermark-notes"
_MAX_IDEMPOTENCY_KEY_LENGTH = 200
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class NotebookCommitsResource(BaseResource):
    """Stage media in one save session and atomically commit desired state."""

    def begin(self, note_id: str, *, idempotency_key: str) -> NotebookSaveSession:
        """Begin or replay an active notebook save session."""

        response = self._idempotent_request(
            "POST",
            f"{_NOTEBOOKS_PATH}/{_path_id(note_id, 'note_id')}/save-sessions",
            idempotency_key=idempotency_key,
        )
        return _typed_result(response, NotebookSaveSession.from_dict)

    def stage(
        self,
        note_id: str,
        save_session_id: UUIDInput,
        file: FileInput,
        *,
        idempotency_key: str,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        expected_sha256: Optional[str] = None,
    ) -> NotebookStagedUpload:
        """Stream one file into an existing save session.

        Call this method repeatedly with the same ``save_session_id`` and a new
        idempotency key for each file to stage multiple files in one save.
        """

        session_id = _uuid_text(save_session_id, "save_session_id")
        form: Dict[str, str] = {}
        if expected_sha256 is not None:
            form["expected_sha256"] = _sha256(expected_sha256)

        if isinstance(file, (str, Path)):
            path = Path(file)
            actual_filename = filename or path.name
            actual_content_type = content_type or _guess_content_type(actual_filename)
            with path.open("rb") as handle:
                response = self._idempotent_request(
                    "POST",
                    self._uploads_path(note_id, session_id),
                    idempotency_key=idempotency_key,
                    data=form,
                    files={"file": (actual_filename, handle, actual_content_type)},
                )
        else:
            if not callable(getattr(file, "read", None)):
                raise _invalid_request("file must be a path or binary file handle", "file")
            actual_filename = filename or _handle_filename(file)
            if not actual_filename:
                raise _invalid_request(
                    "filename is required for an unnamed file handle",
                    "filename",
                )
            actual_content_type = content_type or _guess_content_type(actual_filename)
            response = self._idempotent_request(
                "POST",
                self._uploads_path(note_id, session_id),
                idempotency_key=idempotency_key,
                data=form,
                files={"file": (actual_filename, file, actual_content_type)},
            )

        return _typed_result(response, NotebookStagedUpload.from_dict)

    def status(
        self,
        note_id: str,
        save_session_id: UUIDInput,
    ) -> NotebookSaveSessionStatus:
        """Return a save session and the status of all its uploads."""

        response = self._get(self._session_path(note_id, save_session_id))
        return _typed_result(response, NotebookSaveSessionStatus.from_dict)

    def upload_status(self, upload_id: UUIDInput) -> NotebookStagedUpload:
        """Return the status of one staged upload."""

        response = self._get(
            f"{_NOTEBOOKS_PATH}/staged-uploads/{quote(_uuid_text(upload_id, 'upload_id'))}"
        )
        return _typed_result(response, NotebookStagedUpload.from_dict)

    def cancel(
        self,
        note_id: str,
        save_session_id: UUIDInput,
        *,
        idempotency_key: str,
    ) -> NotebookSaveSessionCancellation:
        """Cancel a save session and release its staged reservations."""

        response = self._idempotent_request(
            "DELETE",
            self._session_path(note_id, save_session_id),
            idempotency_key=idempotency_key,
        )
        return _typed_result(response, NotebookSaveSessionCancellation.from_dict)

    def commit(
        self,
        note_id: str,
        *,
        desired_state: Union[NotebookDesiredState, Mapping[str, Any]],
        expected_revision: int,
        idempotency_key: str,
        save_session_id: Optional[UUIDInput] = None,
        save_batch_id: Optional[UUIDInput] = None,
    ) -> NotebookCommitResponse:
        """Atomically commit a complete desired notebook state."""

        if not isinstance(desired_state, Mapping):
            raise _invalid_request("desired_state must be an object", "desired_state")
        state = (
            desired_state.to_dict()
            if isinstance(desired_state, NotebookDesiredState)
            else dict(desired_state)
        )

        body: Dict[str, Any] = {
            "desired_state": state,
            "expected_revision": _revision(expected_revision, "expected_revision"),
        }
        if save_session_id is not None:
            body["save_session_id"] = _uuid_text(save_session_id, "save_session_id")
        if save_batch_id is not None:
            body["save_batch_id"] = _uuid_text(save_batch_id, "save_batch_id")

        response = self._idempotent_request(
            "POST",
            f"{_NOTEBOOKS_PATH}/{_path_id(note_id, 'note_id')}/commits",
            idempotency_key=idempotency_key,
            json=body,
        )
        return _typed_result(response, NotebookCommitResponse.from_dict)

    def _session_path(self, note_id: str, save_session_id: UUIDInput) -> str:
        return (
            f"{_NOTEBOOKS_PATH}/{_path_id(note_id, 'note_id')}/save-sessions/"
            f"{quote(_uuid_text(save_session_id, 'save_session_id'))}"
        )

    def _uploads_path(self, note_id: str, save_session_id: UUIDInput) -> str:
        return f"{self._session_path(note_id, save_session_id)}/uploads"

    def _idempotent_request(
        self,
        method: str,
        path: str,
        *,
        idempotency_key: str,
        **kwargs: Any,
    ) -> Any:
        return self._client._request(
            method=method,
            path=path,
            headers={
                "Idempotency-Key": _required_text(
                    idempotency_key,
                    "idempotency_key",
                    max_length=_MAX_IDEMPOTENCY_KEY_LENGTH,
                )
            },
            **kwargs,
        )


def _result_mapping(response: Any) -> Mapping[str, Any]:
    status_code = int(getattr(response, "status_code", 0) or 0)
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise OfSpectrumError(
            message="Notebook commit service returned an invalid response",
            code="InvalidNotebookCommitResponse",
            status_code=status_code or None,
            details={},
        ) from exc

    raise_for_error(payload, status_code)
    if status_code >= 400:
        raise OfSpectrumError(
            message="Notebook commit request failed",
            code="NotebookCommitRequestFailed",
            status_code=status_code,
            details={},
        )
    if not isinstance(payload, Mapping):
        raise OfSpectrumError(
            message="Notebook commit service returned an invalid response",
            code="InvalidNotebookCommitResponse",
            status_code=status_code or None,
            details={},
        )

    result = payload.get("data", payload)
    if not isinstance(result, Mapping):
        raise OfSpectrumError(
            message="Notebook commit service returned an invalid response",
            code="InvalidNotebookCommitResponse",
            status_code=status_code or None,
            details={},
        )
    return result


def _typed_result(
    response: Any,
    factory: Callable[[Mapping[str, Any]], ResultModel],
) -> ResultModel:
    try:
        return factory(_result_mapping(response))
    except OfSpectrumError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise OfSpectrumError(
            message="Notebook commit service returned an invalid response",
            code="InvalidNotebookCommitResponse",
            status_code=int(getattr(response, "status_code", 0) or 0) or None,
            details={},
        ) from exc


def _required_text(
    value: Any,
    field: str,
    *,
    max_length: Optional[int] = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_request(f"{field} must not be empty", field)
    normalized = value.strip()
    if max_length is not None and len(normalized) > max_length:
        raise _invalid_request(f"{field} is too long", field)
    return normalized


def _revision(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _invalid_request(f"{field} must be a non-negative integer", field)
    return value


def _uuid_text(value: Any, field: str) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(_required_text(value, field))
    except (AttributeError, TypeError, ValueError):
        raise _invalid_request(f"{field} must be a UUID", field) from None
    return str(parsed)


def _sha256(value: Any) -> str:
    normalized = _required_text(value, "expected_sha256").lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise _invalid_request(
            "expected_sha256 must be a 64-character hexadecimal digest",
            "expected_sha256",
        )
    return normalized


def _path_id(value: Any, field: str) -> str:
    return quote(_required_text(value, field), safe="")


def _handle_filename(handle: BinaryIO) -> Optional[str]:
    name = getattr(handle, "name", None)
    if not isinstance(name, (str, Path)):
        return None
    filename = Path(name).name
    return filename or None


def _guess_content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _invalid_request(message: str, field: str) -> ValidationError:
    return ValidationError(
        message=message,
        code="InvalidNotebookCommitRequest",
        status_code=400,
        details={"field": field},
        field=field,
    )
