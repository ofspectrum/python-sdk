"""Typed models for notebook settings and revision-safe saves."""

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence


def _optional_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _effective_bool(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _non_negative_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized >= 0 else default


def _optional_non_negative_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _optional_text(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is missing from the API response")
    return value


def _required_non_negative_int(data: Mapping[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} is invalid in the API response")
    return value


def _required_bool(data: Mapping[str, Any], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} is invalid in the API response")
    return value


@dataclass(frozen=True)
class NotebookSettingOverrides:
    """Nullable token overrides; ``None`` means inherit the account default."""

    version_control_override: Optional[bool] = None
    storage_auto_expand_override: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookSettingOverrides":
        return cls(
            version_control_override=_optional_bool(data.get("version_control_override")),
            storage_auto_expand_override=_optional_bool(
                data.get("storage_auto_expand_override")
            ),
        )

    def to_dict(self) -> Dict[str, Optional[bool]]:
        return {
            "version_control_override": self.version_control_override,
            "storage_auto_expand_override": self.storage_auto_expand_override,
        }


@dataclass(frozen=True)
class NotebookEffectiveSettings:
    """Server-calculated notebook capabilities and included storage."""

    version_control_enabled: bool = False
    storage_auto_expand_enabled: bool = False
    storage_entitlement_bytes: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookEffectiveSettings":
        return cls(
            version_control_enabled=_effective_bool(data.get("version_control_enabled")),
            storage_auto_expand_enabled=_effective_bool(
                data.get("storage_auto_expand_enabled")
            ),
            storage_entitlement_bytes=_non_negative_int(
                data.get("storage_entitlement_bytes")
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_control_enabled": self.version_control_enabled,
            "storage_auto_expand_enabled": self.storage_auto_expand_enabled,
            "storage_entitlement_bytes": self.storage_entitlement_bytes,
        }


@dataclass(frozen=True)
class NotebookSettingsResponse:
    """Configured overrides and server-calculated effective settings."""

    version_control_override: Optional[bool] = None
    storage_auto_expand_override: Optional[bool] = None
    version_control_enabled: bool = False
    storage_auto_expand_enabled: bool = False
    storage_entitlement_bytes: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookSettingsResponse":
        overrides = NotebookSettingOverrides.from_dict(data)
        effective = NotebookEffectiveSettings.from_dict(data)
        return cls(
            version_control_override=overrides.version_control_override,
            storage_auto_expand_override=overrides.storage_auto_expand_override,
            version_control_enabled=effective.version_control_enabled,
            storage_auto_expand_enabled=effective.storage_auto_expand_enabled,
            storage_entitlement_bytes=effective.storage_entitlement_bytes,
        )

    @property
    def overrides(self) -> NotebookSettingOverrides:
        return NotebookSettingOverrides(
            version_control_override=self.version_control_override,
            storage_auto_expand_override=self.storage_auto_expand_override,
        )

    @property
    def effective(self) -> NotebookEffectiveSettings:
        return NotebookEffectiveSettings(
            version_control_enabled=self.version_control_enabled,
            storage_auto_expand_enabled=self.storage_auto_expand_enabled,
            storage_entitlement_bytes=self.storage_entitlement_bytes,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {**self.overrides.to_dict(), **self.effective.to_dict()}


@dataclass(frozen=True)
class NotebookDesiredMedia:
    """One current-media or staged-upload reference in desired order."""

    display_order: int
    media_id: Optional[str] = None
    upload_id: Optional[str] = None
    filename: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.media_id is None) == (self.upload_id is None):
            raise ValueError("exactly one of media_id or upload_id is required")
        selected_id = self.media_id if self.media_id is not None else self.upload_id
        if not isinstance(selected_id, str) or not selected_id.strip():
            raise ValueError("media_id and upload_id cannot be empty")
        if (
            isinstance(self.display_order, bool)
            or not isinstance(self.display_order, int)
            or self.display_order < 0
        ):
            raise ValueError("display_order must be a non-negative integer")
        if self.upload_id is not None and self.filename is None:
            raise ValueError("filename is required for staged media")
        if self.filename is not None:
            if not isinstance(self.filename, str) or not self.filename.isprintable():
                raise ValueError("filename must be a printable string")
            filename = self.filename.strip()
            if not filename or len(filename) > 1024:
                raise ValueError("filename must contain between 1 and 1024 characters")
            object.__setattr__(self, "filename", filename)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookDesiredMedia":
        return cls(
            display_order=_required_non_negative_int(data, "display_order"),
            media_id=_optional_text(data.get("media_id")),
            upload_id=_optional_text(data.get("upload_id")),
            filename=_optional_text(data.get("filename")),
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"display_order": self.display_order}
        if self.media_id is not None:
            data["media_id"] = self.media_id
        if self.upload_id is not None:
            data["upload_id"] = self.upload_id
        if self.filename is not None:
            data["filename"] = self.filename
        return data


@dataclass(frozen=True)
class NotebookDesiredState(Mapping[str, Any]):
    """Complete desired state accepted by the notebook commit endpoint."""

    note_name: Optional[str]
    text_content: Optional[str]
    is_public: bool
    credential_val: Optional[str] = None
    media: Sequence[NotebookDesiredMedia] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.is_public, bool):
            raise ValueError("is_public must be a boolean")
        if any(not isinstance(item, NotebookDesiredMedia) for item in self.media):
            raise ValueError("media must contain NotebookDesiredMedia values")
        orders = sorted(item.display_order for item in self.media)
        if orders != list(range(len(orders))):
            raise ValueError("media display_order values must be contiguous from zero")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookDesiredState":
        media = data.get("media") or []
        return cls(
            note_name=_optional_text(data.get("note_name")),
            text_content=_optional_text(data.get("text_content")),
            is_public=data.get("is_public"),
            credential_val=_optional_text(data.get("credential_val")),
            media=tuple(
                NotebookDesiredMedia.from_dict(item)
                for item in media
                if isinstance(item, Mapping)
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "note_name": self.note_name,
            "text_content": self.text_content,
            "is_public": self.is_public,
            "credential_val": self.credential_val,
            "media": [item.to_dict() for item in self.media],
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(("note_name", "text_content", "is_public", "credential_val", "media"))

    def __len__(self) -> int:
        return 5


@dataclass(frozen=True)
class NotebookStorageAdmission:
    """Capacity projection returned by staging or commit operations."""

    used_media_bytes: Optional[int] = None
    reserved_media_bytes: Optional[int] = None
    projected_unique_bytes: Optional[int] = None
    included_entitlement_bytes: Optional[int] = None
    legacy_credit_bytes: Optional[int] = None
    allocated_paid_blocks: Optional[int] = None
    required_paid_blocks: Optional[int] = None
    projected_new_paid_blocks: Optional[int] = None
    storage_auto_expand_enabled: Optional[bool] = None
    payment_eligible: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookStorageAdmission":
        return cls(
            used_media_bytes=_optional_non_negative_int(data.get("used_media_bytes")),
            reserved_media_bytes=_optional_non_negative_int(
                data.get("reserved_media_bytes")
            ),
            projected_unique_bytes=_optional_non_negative_int(
                data.get("projected_unique_bytes")
            ),
            included_entitlement_bytes=_optional_non_negative_int(
                data.get("included_entitlement_bytes")
            ),
            legacy_credit_bytes=_optional_non_negative_int(data.get("legacy_credit_bytes")),
            allocated_paid_blocks=_optional_non_negative_int(
                data.get("allocated_paid_blocks")
            ),
            required_paid_blocks=_optional_non_negative_int(
                data.get("required_paid_blocks")
            ),
            projected_new_paid_blocks=_optional_non_negative_int(
                data.get("projected_new_paid_blocks")
            ),
            storage_auto_expand_enabled=_optional_bool(
                data.get("storage_auto_expand_enabled")
            ),
            payment_eligible=_optional_bool(data.get("payment_eligible")),
        )


@dataclass(frozen=True)
class NotebookSaveSession:
    """An active or replayed notebook save session."""

    save_session_id: str
    notebook_id: str
    state: str
    expires_at: str
    created: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookSaveSession":
        return cls(
            save_session_id=_required_text(data, "save_session_id"),
            notebook_id=_required_text(data, "notebook_id"),
            state=_required_text(data, "state"),
            expires_at=_required_text(data, "expires_at"),
            created=_optional_bool(data.get("created")),
        )


@dataclass(frozen=True)
class NotebookStagedUpload:
    """Status returned for one upload in a save session."""

    upload_id: str
    state: str
    expires_at: str
    save_session_id: Optional[str] = None
    notebook_id: Optional[str] = None
    filename: Optional[str] = None
    media_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    reused_existing_blob: Optional[bool] = None
    reserved_bytes: Optional[int] = None
    admission: Optional[NotebookStorageAdmission] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookStagedUpload":
        admission = data.get("admission")
        return cls(
            upload_id=_required_text(data, "upload_id"),
            state=_required_text(data, "state"),
            expires_at=_required_text(data, "expires_at"),
            save_session_id=_optional_text(data.get("save_session_id")),
            notebook_id=_optional_text(data.get("notebook_id")),
            filename=_optional_text(data.get("filename")),
            media_type=_optional_text(data.get("media_type")),
            file_size_bytes=_optional_non_negative_int(data.get("file_size_bytes")),
            reused_existing_blob=_optional_bool(data.get("reused_existing_blob")),
            reserved_bytes=_optional_non_negative_int(data.get("reserved_bytes")),
            admission=(
                NotebookStorageAdmission.from_dict(admission)
                if isinstance(admission, Mapping)
                else None
            ),
        )


@dataclass(frozen=True)
class NotebookSaveSessionStatus:
    """A save session and all uploads currently associated with it."""

    save_session_id: str
    notebook_id: str
    state: str
    expires_at: str
    uploads: Sequence[NotebookStagedUpload] = field(default_factory=tuple)
    created: Optional[bool] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookSaveSessionStatus":
        uploads = data.get("uploads") or []
        return cls(
            save_session_id=_required_text(data, "save_session_id"),
            notebook_id=_required_text(data, "notebook_id"),
            state=_required_text(data, "state"),
            expires_at=_required_text(data, "expires_at"),
            uploads=tuple(
                NotebookStagedUpload.from_dict(item)
                for item in uploads
                if isinstance(item, Mapping)
            ),
            created=_optional_bool(data.get("created")),
        )


@dataclass(frozen=True)
class NotebookSaveSessionCancellation:
    """Result of cancelling a notebook save session."""

    save_session_id: str
    state: str
    released_bytes: int
    idempotent: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookSaveSessionCancellation":
        return cls(
            save_session_id=_required_text(data, "save_session_id"),
            state=_required_text(data, "state"),
            released_bytes=_required_non_negative_int(data, "released_bytes"),
            idempotent=_required_bool(data, "idempotent"),
        )


@dataclass(frozen=True)
class NotebookCommitMedia:
    """One current media item returned by a successful commit."""

    id: str
    filename: str
    media_type: str
    file_size_bytes: int
    display_order: int

    @property
    def file_size(self) -> int:
        """Backward-compatible alias for ``file_size_bytes``."""

        return self.file_size_bytes

    @property
    def content_type(self) -> str:
        """Backward-compatible alias for ``media_type``."""

        return self.media_type

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookCommitMedia":
        return cls(
            id=_required_text(data, "id"),
            filename=_required_text(data, "filename"),
            media_type=_required_text(data, "media_type"),
            file_size_bytes=_required_non_negative_int(data, "file_size_bytes"),
            display_order=_required_non_negative_int(data, "display_order"),
        )


@dataclass(frozen=True)
class NotebookCommitResponse:
    """Result of an atomic desired-state commit."""

    notebook_id: str
    resulting_revision: int
    expected_revision: Optional[int] = None
    changed: bool = False
    state: Optional[str] = None
    save_batch_id: Optional[str] = None
    version_id: Optional[str] = None
    version_sequence: Optional[int] = None
    replayed: bool = False
    media: Sequence[NotebookCommitMedia] = field(default_factory=tuple)
    storage: Optional[NotebookStorageAdmission] = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NotebookCommitResponse":
        media = data.get("media") or []
        storage = data.get("storage")
        return cls(
            notebook_id=_required_text(data, "notebook_id"),
            resulting_revision=_required_non_negative_int(data, "resulting_revision"),
            expected_revision=_optional_non_negative_int(data.get("expected_revision")),
            changed=_effective_bool(data.get("changed")),
            state=_optional_text(data.get("state")),
            save_batch_id=_optional_text(data.get("save_batch_id")),
            version_id=_optional_text(data.get("version_id")),
            version_sequence=_optional_non_negative_int(data.get("version_sequence")),
            replayed=_effective_bool(data.get("replayed")),
            media=tuple(
                NotebookCommitMedia.from_dict(item)
                for item in media
                if isinstance(item, Mapping)
            ),
            storage=(
                NotebookStorageAdmission.from_dict(storage)
                if isinstance(storage, Mapping)
                else None
            ),
        )


__all__ = [
    "NotebookSettingOverrides",
    "NotebookEffectiveSettings",
    "NotebookSettingsResponse",
    "NotebookDesiredMedia",
    "NotebookDesiredState",
    "NotebookStorageAdmission",
    "NotebookSaveSession",
    "NotebookStagedUpload",
    "NotebookSaveSessionStatus",
    "NotebookSaveSessionCancellation",
    "NotebookCommitMedia",
    "NotebookCommitResponse",
]
