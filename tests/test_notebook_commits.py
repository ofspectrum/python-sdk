from io import BytesIO
from uuid import UUID

import pytest

from ofspectrum.exceptions import ConflictError, OfSpectrumError, ValidationError
from ofspectrum.models.notebook_version import (
    NotebookCommitResponse,
    NotebookDesiredMedia,
    NotebookDesiredState,
    NotebookSaveSession,
    NotebookSaveSessionCancellation,
    NotebookSaveSessionStatus,
    NotebookStagedUpload,
)
from ofspectrum.resources.notebook_commits import NotebookCommitsResource

NOTE_ID = "note/with space"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
UPLOAD_ID = "22222222-2222-4222-8222-222222222222"
BATCH_ID = UUID("33333333-3333-4333-8333-333333333333")


class _Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def _request(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _session_payload():
    return {
        "save_session_id": SESSION_ID,
        "notebook_id": NOTE_ID,
        "state": "active",
        "expires_at": "2026-08-01T00:00:00Z",
        "created": True,
    }


def _upload_payload():
    return {
        "upload_id": UPLOAD_ID,
        "save_session_id": SESSION_ID,
        "notebook_id": NOTE_ID,
        "state": "staged",
        "expires_at": "2026-08-01T00:00:00Z",
        "filename": "evidence.png",
        "media_type": "image/png",
        "file_size_bytes": 8,
        "reserved_bytes": 8,
    }


def test_begin_returns_typed_session_and_sends_idempotency_header():
    client = _Client([_Response({"data": _session_payload()})])
    resource = NotebookCommitsResource(client)

    session = resource.begin(NOTE_ID, idempotency_key=" begin-key ")

    assert isinstance(session, NotebookSaveSession)
    assert session.save_session_id == SESSION_ID
    assert client.requests == [
        {
            "method": "POST",
            "path": "/watermark-notes/note%2Fwith%20space/save-sessions",
            "headers": {"Idempotency-Key": "begin-key"},
        }
    ]


def test_stage_reuses_session_and_returns_typed_upload():
    client = _Client([_Response(_upload_payload())])
    resource = NotebookCommitsResource(client)
    content = BytesIO(b"\x89PNG\r\n\x1a\n")

    upload = resource.stage(
        NOTE_ID,
        SESSION_ID,
        content,
        filename="evidence.png",
        idempotency_key="stage-key",
        expected_sha256="A" * 64,
    )

    assert isinstance(upload, NotebookStagedUpload)
    assert upload.upload_id == UPLOAD_ID
    request = client.requests[0]
    assert request["path"].endswith(f"/save-sessions/{SESSION_ID}/uploads")
    assert request["headers"] == {"Idempotency-Key": "stage-key"}
    assert request["data"] == {"expected_sha256": "a" * 64}
    assert request["files"]["file"][0:3:2] == ("evidence.png", "image/png")


def test_status_upload_status_and_cancel_return_typed_models():
    status_payload = {**_session_payload(), "uploads": [_upload_payload()]}
    cancellation_payload = {
        "save_session_id": SESSION_ID,
        "state": "cancelled",
        "released_bytes": 8,
        "idempotent": False,
    }
    client = _Client(
        [
            _Response(status_payload),
            _Response(_upload_payload()),
            _Response(cancellation_payload),
        ]
    )
    resource = NotebookCommitsResource(client)

    status = resource.status(NOTE_ID, SESSION_ID)
    upload = resource.upload_status(UPLOAD_ID)
    cancellation = resource.cancel(
        NOTE_ID, SESSION_ID, idempotency_key="cancel-key"
    )

    assert isinstance(status, NotebookSaveSessionStatus)
    assert isinstance(status.uploads[0], NotebookStagedUpload)
    assert isinstance(upload, NotebookStagedUpload)
    assert isinstance(cancellation, NotebookSaveSessionCancellation)
    assert cancellation.released_bytes == 8
    assert client.requests[1]["path"] == f"/watermark-notes/staged-uploads/{UPLOAD_ID}"
    assert client.requests[2]["method"] == "DELETE"


def test_commit_sends_complete_state_and_returns_typed_result():
    response = {
        "notebook_id": NOTE_ID,
        "expected_revision": 4,
        "resulting_revision": 5,
        "changed": True,
        "state": "committed",
        "save_batch_id": str(BATCH_ID),
        "replayed": False,
        "media": [
            {
                "id": "media-1",
                "filename": "evidence.png",
                "media_type": "image/png",
                "file_size_bytes": 8,
                "display_order": 0,
            }
        ],
        "storage": {
            "projected_unique_bytes": 8,
            "storage_auto_expand_enabled": False,
        },
    }
    client = _Client([_Response(response)])
    resource = NotebookCommitsResource(client)
    desired_state = NotebookDesiredState(
        note_name="Evidence",
        text_content="Current text",
        is_public=True,
        media=(
            NotebookDesiredMedia(
                display_order=0,
                upload_id=UPLOAD_ID,
                filename="evidence.png",
            ),
        ),
    )

    result = resource.commit(
        NOTE_ID,
        desired_state=desired_state,
        expected_revision=4,
        idempotency_key="commit-key",
        save_session_id=SESSION_ID,
        save_batch_id=BATCH_ID,
    )

    assert isinstance(result, NotebookCommitResponse)
    assert result.resulting_revision == 5
    assert result.media[0].media_type == "image/png"
    assert result.media[0].file_size == 8
    assert result.storage is not None
    assert result.storage.projected_unique_bytes == 8
    request = client.requests[0]
    assert request["json"] == {
        "desired_state": {
            "note_name": "Evidence",
            "text_content": "Current text",
            "is_public": True,
            "credential_val": None,
            "media": [
                {
                    "display_order": 0,
                    "upload_id": UPLOAD_ID,
                    "filename": "evidence.png",
                }
            ],
        },
        "expected_revision": 4,
        "save_session_id": SESSION_ID,
        "save_batch_id": str(BATCH_ID),
    }


def test_commit_maps_structured_conflict():
    client = _Client(
        [
            _Response(
                {
                    "detail": {
                        "error": "NotebookRevisionConflict",
                        "message": "Reload before saving.",
                        "details": {"current_revision": 6},
                    }
                },
                status_code=409,
            )
        ]
    )
    resource = NotebookCommitsResource(client)

    with pytest.raises(ConflictError) as exc:
        resource.commit(
            NOTE_ID,
            desired_state={
                "note_name": "Evidence",
                "text_content": None,
                "is_public": True,
                "credential_val": None,
                "media": [],
            },
            expected_revision=4,
            idempotency_key="commit-key",
        )

    assert exc.value.code == "NotebookRevisionConflict"
    assert exc.value.details["current_revision"] == 6


def test_malformed_typed_result_raises_sdk_error():
    resource = NotebookCommitsResource(_Client([_Response({"state": "active"})]))

    with pytest.raises(OfSpectrumError) as exc:
        resource.begin(NOTE_ID, idempotency_key="begin-key")

    assert exc.value.code == "InvalidNotebookCommitResponse"


@pytest.mark.parametrize("value", ["", "not-a-uuid"])
def test_save_session_id_must_be_uuid(value):
    resource = NotebookCommitsResource(_Client([]))

    with pytest.raises(ValidationError) as exc:
        resource.status(NOTE_ID, value)

    assert exc.value.code == "InvalidNotebookCommitRequest"
    assert exc.value.field == "save_session_id"


def test_desired_state_requires_contiguous_media_order():
    with pytest.raises(ValueError, match="contiguous"):
        NotebookDesiredState(
            note_name="Evidence",
            text_content=None,
            is_public=True,
            media=(
                NotebookDesiredMedia(
                    display_order=1,
                    upload_id=UPLOAD_ID,
                    filename="evidence.png",
                ),
            ),
        )


def test_staged_desired_media_requires_filename():
    with pytest.raises(ValueError, match="filename is required"):
        NotebookDesiredMedia(display_order=0, upload_id=UPLOAD_ID)
