from io import BytesIO
from types import SimpleNamespace

import pytest

from ofspectrum.exceptions import (
    OfSpectrumError,
    ServiceUnavailableError,
    ValidationError,
    raise_for_error,
)
from ofspectrum.models.notebook import Notebook
from ofspectrum.models.notebook_version import (
    NotebookCommitMedia,
    NotebookCommitResponse,
)
from ofspectrum.resources.notebooks import NotebooksResource

SESSION_ID = "11111111-1111-4111-8111-111111111111"
UPLOAD_ID = "22222222-2222-4222-8222-222222222222"


class _Response:
    def __init__(self, data=None, status_code=200):
        self._data = (
            data
            if data is not None
            else {"id": "media-1", "media_type": "image/png"}
        )
        self.status_code = status_code

    def json(self):
        return self._data


class _Client:
    def __init__(self, commits=None):
        self.notebook_commits = commits


class _Commits:
    def __init__(self, response=None, *, begin_error=None, commit_error=None):
        self.response = response or _commit_response([])
        self.begin_error = begin_error
        self.commit_error = commit_error
        self.begin_calls = []
        self.stage_calls = []
        self.commit_calls = []
        self.cancel_calls = []

    def begin(self, note_id, *, idempotency_key):
        self.begin_calls.append((note_id, idempotency_key))
        if self.begin_error:
            raise self.begin_error
        return SimpleNamespace(save_session_id=SESSION_ID)

    def stage(
        self,
        note_id,
        save_session_id,
        file,
        *,
        filename,
        content_type,
        idempotency_key,
    ):
        self.stage_calls.append(
            {
                "note_id": note_id,
                "save_session_id": save_session_id,
                "file": file,
                "filename": filename,
                "content_type": content_type,
                "idempotency_key": idempotency_key,
            }
        )
        return SimpleNamespace(upload_id=UPLOAD_ID, filename=filename)

    def commit(self, note_id, **kwargs):
        self.commit_calls.append((note_id, kwargs))
        if self.commit_error:
            raise self.commit_error
        return self.response

    def cancel(self, note_id, save_session_id, *, idempotency_key):
        self.cancel_calls.append((note_id, save_session_id, idempotency_key))


def _media(media_id, filename, media_type, display_order, file_size_bytes=10):
    return {
        "id": media_id,
        "filename": filename,
        "media_type": media_type,
        "file_size_bytes": file_size_bytes,
        "display_order": display_order,
    }


def _projection(*, media=None, revision=7):
    return {
        "id": "note-1",
        "token_id": "token-1",
        "note_name": "Private Evidence",
        "text_content": "Authoritative text",
        "is_public": False,
        "credential_val": "secret",
        "revision": revision,
        "media": media if media is not None else [],
    }


def _commit_response(media, *, revision=8):
    return NotebookCommitResponse(
        notebook_id="note-1",
        expected_revision=revision - 1,
        resulting_revision=revision,
        changed=True,
        state="committed",
        media=tuple(
            NotebookCommitMedia(
                id=item["id"],
                filename=item["filename"],
                media_type=item["media_type"],
                file_size_bytes=item["file_size_bytes"],
                display_order=item["display_order"],
            )
            for item in media
        ),
    )


def test_upload_media_uses_one_session_and_commits_complete_projection(monkeypatch):
    current_media = [_media("media-1", "first.wav", "audio/wav", 0)]
    committed_media = current_media + [
        _media("media-2", "spoofed.txt", "image/png", 1, file_size_bytes=8)
    ]
    commits = _Commits(_commit_response(committed_media))
    resource = NotebooksResource(_Client(commits))
    requested = []
    monkeypatch.setattr(
        resource,
        "_get",
        lambda path: requested.append(path) or _Response(_projection(media=current_media)),
    )
    monkeypatch.setattr(
        resource,
        "_post",
        lambda *_args, **_kwargs: pytest.fail("legacy upload must not be used"),
    )
    content = BytesIO(b"\x89PNG\r\n\x1a\n")

    result = resource.upload_media(
        "note-1",
        content,
        filename="spoofed.txt",
        media_type="text/plain",
    )

    assert result["media_type"] == "image/png"
    assert result["id"] == "media-2"
    assert requested == ["/watermark-notes/note-1"]
    assert len(commits.begin_calls) == 1
    assert len(commits.stage_calls) == 1
    assert len(commits.commit_calls) == 1
    assert commits.stage_calls[0]["save_session_id"] == SESSION_ID
    assert commits.stage_calls[0]["content_type"] == "text/plain"
    _, commit_kwargs = commits.commit_calls[0]
    assert commit_kwargs["save_session_id"] == SESSION_ID
    desired = commit_kwargs["desired_state"].to_dict()
    assert desired == {
        "note_name": "Private Evidence",
        "text_content": "Authoritative text",
        "is_public": False,
        "credential_val": "secret",
        "media": [
            {"display_order": 0, "media_id": "media-1", "filename": "first.wav"},
            {"display_order": 1, "upload_id": UPLOAD_ID, "filename": "spoofed.txt"},
        ],
    }
    assert content.tell() == 0


def test_sdk_rejects_obvious_svg_before_upload(monkeypatch):
    resource = NotebooksResource(_Client())
    monkeypatch.setattr(
        resource,
        "_post",
        lambda *_args, **_kwargs: pytest.fail("SVG must not be uploaded"),
    )

    with pytest.raises(ValidationError, match="SVG is not supported") as exc:
        resource.upload_media(
            "note-1",
            BytesIO(b'  <svg xmlns="http://www.w3.org/2000/svg"></svg>'),
            filename="image.svg",
        )

    assert exc.value.code == "UnsupportedNotebookMedia"
    assert exc.value.field == "file"


def test_sdk_maps_structured_unsupported_media_error():
    with pytest.raises(ValidationError) as exc:
        raise_for_error(
            {
                "detail": {
                    "error": "UnsupportedNotebookMedia",
                    "message": "Only server-detected image, audio, and video files are supported.",
                }
            },
            415,
        )

    assert exc.value.code == "UnsupportedNotebookMedia"
    assert exc.value.status_code == 415


def test_get_uses_current_get_endpoint_and_returns_revision_and_ordered_media(monkeypatch):
    resource = NotebooksResource(_Client())
    requested = []
    monkeypatch.setattr(
        resource,
        "_get",
        lambda path: (
            requested.append(path)
            or _Response(
                {
                    "id": "note-1",
                    "token_id": "token-1",
                    "note_name": "Evidence",
                    "text_content": "",
                    "content": "legacy content must not replace an explicit empty value",
                    "is_public": True,
                    "credential_val": None,
                    "revision": 7,
                    "media": [
                        {
                            "id": "media-2",
                            "filename": "second.wav",
                            "media_type": "audio/wav",
                            "file_size_bytes": 22,
                            "display_order": 1,
                        },
                        {
                            "id": "media-1",
                            "filename": "first.png",
                            "media_type": "image/png",
                            "content_type": "legacy/type",
                            "file_size_bytes": 11,
                            "file_size": 999,
                            "display_order": 0,
                        },
                    ],
                }
            )
        ),
    )
    monkeypatch.setattr(
        resource,
        "_patch",
        lambda *_args, **_kwargs: pytest.fail("notebooks.get() must not mutate"),
    )

    notebook = resource.get("note-1")

    assert requested == ["/watermark-notes/note-1"]
    assert notebook.revision == 7
    assert notebook.text_content == ""
    assert notebook.media is not None
    assert [media.id for media in notebook.media] == ["media-1", "media-2"]
    assert notebook.media[0].media_type == "image/png"
    assert notebook.media[0].file_size_bytes == 11


def test_update_preserves_visibility_credential_name_and_ordered_media(monkeypatch):
    current_media = [
        _media("media-2", "second.wav", "audio/wav", 1, file_size_bytes=22),
        _media("media-1", "first.png", "image/png", 0, file_size_bytes=11),
    ]
    committed_media = [current_media[1], current_media[0]]
    commits = _Commits(_commit_response(committed_media))
    resource = NotebooksResource(_Client(commits))
    monkeypatch.setattr(
        resource,
        "_get",
        lambda _path: _Response(_projection(media=current_media)),
    )
    monkeypatch.setattr(
        resource,
        "_patch",
        lambda *_args, **_kwargs: pytest.fail("legacy update must not be used"),
    )

    updated = resource.update("note-1", text_content="Updated text")

    assert updated.revision == 8
    assert updated.note_name == "Private Evidence"
    assert updated.is_public is False
    assert updated.credential_val == "secret"
    assert [item.id for item in updated.media or []] == ["media-1", "media-2"]
    _, commit_kwargs = commits.commit_calls[0]
    assert commit_kwargs["desired_state"].to_dict() == {
        "note_name": "Private Evidence",
        "text_content": "Updated text",
        "is_public": False,
        "credential_val": "secret",
        "media": [
            {"display_order": 0, "media_id": "media-1", "filename": "first.png"},
            {"display_order": 1, "media_id": "media-2", "filename": "second.wav"},
        ],
    }


def test_delete_media_removes_only_selected_media(monkeypatch):
    current_media = [
        _media("media-1", "first.png", "image/png", 0),
        _media("media-2", "second.wav", "audio/wav", 1),
        _media("media-3", "third.mp4", "video/mp4", 2),
    ]
    committed_media = [
        current_media[0],
        {**current_media[2], "display_order": 1},
    ]
    commits = _Commits(_commit_response(committed_media))
    resource = NotebooksResource(_Client(commits))
    monkeypatch.setattr(
        resource,
        "_get",
        lambda _path: _Response(_projection(media=current_media)),
    )
    monkeypatch.setattr(
        resource,
        "_delete",
        lambda *_args, **_kwargs: pytest.fail("legacy delete must not be used"),
    )

    assert resource.delete_media("media-2", note_id="note-1") is True

    _, commit_kwargs = commits.commit_calls[0]
    desired = commit_kwargs["desired_state"].to_dict()
    assert desired["note_name"] == "Private Evidence"
    assert desired["text_content"] == "Authoritative text"
    assert desired["is_public"] is False
    assert desired["credential_val"] == "secret"
    assert desired["media"] == [
        {"display_order": 0, "media_id": "media-1", "filename": "first.png"},
        {"display_order": 1, "media_id": "media-3", "filename": "third.mp4"},
    ]


def test_delete_media_requires_note_id_before_any_request():
    commits = _Commits()
    resource = NotebooksResource(_Client(commits))

    with pytest.raises(ValidationError) as exc:
        resource.delete_media("media-1")

    assert exc.value.code == "InvalidNotebookMediaRequest"
    assert exc.value.field == "note_id"
    assert commits.begin_calls == []


def test_write_rejects_incomplete_projection_instead_of_committing(monkeypatch):
    incomplete = _projection()
    incomplete.pop("credential_val")
    commits = _Commits()
    resource = NotebooksResource(_Client(commits))
    monkeypatch.setattr(resource, "_get", lambda _path: _Response(incomplete))
    monkeypatch.setattr(
        resource,
        "_patch",
        lambda *_args, **_kwargs: pytest.fail("partial legacy update must not run"),
    )

    with pytest.raises(OfSpectrumError) as exc:
        resource.update("note-1", text_content="unsafe")

    assert exc.value.code == "InvalidNotebookProjectionResponse"
    assert commits.begin_calls == []


@pytest.mark.parametrize(
    "disabled_code",
    [
        "immutable_writes_disabled",
        "NotebookImmutableWritesDisabled",
        "IMMUTABLE_WRITES_DISABLED",
    ],
)
def test_explicit_immutable_disabled_response_uses_legacy_update(
    monkeypatch, disabled_code
):
    disabled = OfSpectrumError(
        "Immutable writes are disabled",
        code=disabled_code,
        status_code=409,
    )
    commits = _Commits(begin_error=disabled)
    resource = NotebooksResource(_Client(commits))
    monkeypatch.setattr(resource, "_get", lambda _path: _Response(_projection()))
    recorded = {}

    def patch(path, *, data):
        recorded.update(path=path, data=data)
        return _Response({**_projection(), "text_content": "Legacy update"})

    monkeypatch.setattr(resource, "_patch", patch)

    updated = resource.update("note-1", text_content="Legacy update")

    assert updated.text_content == "Legacy update"
    assert recorded == {
        "path": "/watermark-notes/note-1",
        "data": {"text_content": "Legacy update"},
    }


def test_generic_atomic_failure_never_falls_back_to_legacy_update(monkeypatch):
    commits = _Commits(
        begin_error=ServiceUnavailableError(
            "Unavailable",
            code="NotebookCommitUnavailable",
            status_code=503,
        )
    )
    resource = NotebooksResource(_Client(commits))
    monkeypatch.setattr(resource, "_get", lambda _path: _Response(_projection()))
    monkeypatch.setattr(
        resource,
        "_patch",
        lambda *_args, **_kwargs: pytest.fail("generic failures must not fall back"),
    )

    with pytest.raises(ServiceUnavailableError):
        resource.update("note-1", text_content="Do not write partially")


def test_create_and_delete_notebook_endpoints_are_unchanged(monkeypatch):
    resource = NotebooksResource(_Client())
    calls = []
    monkeypatch.setattr(
        resource,
        "_post",
        lambda path, *, data: calls.append(("POST", path, data))
        or _Response(
            {
                "id": "note-1",
                "token_id": "token-1",
                "note_name": "Evidence",
                "is_public": True,
            }
        ),
    )
    monkeypatch.setattr(
        resource,
        "_delete",
        lambda path: calls.append(("DELETE", path, None))
        or _Response({"deleted_note_id": "note-1"}),
    )

    created = resource.create("token-1", "Evidence")
    deleted = resource.delete("note-1")

    assert created.id == "note-1"
    assert deleted is True
    assert calls[0][0:2] == ("POST", "/watermark-notes")
    assert calls[1] == ("DELETE", "/watermark-notes/note-1", None)


def test_notebook_summary_distinguishes_omitted_media_from_empty_current_media():
    summary = Notebook.from_dict(
        {"id": "note-1", "token_id": "token-1", "note_name": "Summary"}
    )
    current = Notebook.from_dict(
        {
            "id": "note-1",
            "token_id": "token-1",
            "note_name": "Current",
            "media": [],
            "revision": 0,
        }
    )

    assert summary.media is None
    assert current.media == []
    assert current.revision == 0
