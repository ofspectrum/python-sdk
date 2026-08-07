"""
Notebook models for watermark token notes
"""

from dataclasses import dataclass
from typing import List, Optional


def _preferred_value(data: dict, current_key: str, legacy_key: str):
    """Prefer an explicitly present current field, including empty values."""

    return data.get(current_key) if current_key in data else data.get(legacy_key)


@dataclass
class NotebookMedia:
    """Represents a media file attached to a notebook"""

    id: str
    filename: str
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    created_at: Optional[str] = None
    display_order: Optional[int] = None
    updated_at: Optional[str] = None

    @property
    def file_size_bytes(self) -> Optional[int]:
        """Current API name for the media size, preserving ``file_size`` compatibility."""

        return self.file_size

    @property
    def media_type(self) -> Optional[str]:
        """Current API name for the detected type, preserving ``content_type`` compatibility."""

        return self.content_type

    @classmethod
    def from_dict(cls, data: dict) -> "NotebookMedia":
        """Create NotebookMedia from API response dict"""
        return cls(
            id=data["id"],
            filename=data.get("filename", ""),
            file_url=data.get("file_url") or data.get("media_public"),
            file_size=_preferred_value(data, "file_size_bytes", "file_size"),
            content_type=_preferred_value(data, "media_type", "content_type"),
            created_at=data.get("created_at"),
            display_order=data.get("display_order"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class Notebook:
    """Represents a notebook (note) attached to a token"""

    id: str
    token_id: str
    note_name: str  # Backend uses note_name instead of title
    text_content: Optional[str] = None  # Backend uses text_content instead of content
    is_public: bool = False
    credential_val: Optional[str] = None  # Credential for private notes
    media: Optional[List[NotebookMedia]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    revision: Optional[int] = None

    # Alias properties for backward compatibility
    @property
    def title(self) -> str:
        return self.note_name

    @property
    def content(self) -> Optional[str]:
        return self.text_content

    @classmethod
    def from_dict(cls, data: dict) -> "Notebook":
        """Create Notebook from API response dict"""
        media_data = data.get("media")
        media = (
            [NotebookMedia.from_dict(item) for item in media_data]
            if isinstance(media_data, list)
            else None
        )
        if media is not None:
            media.sort(
                key=lambda item: (
                    item.display_order is None,
                    item.display_order if item.display_order is not None else 0,
                )
            )
        return cls(
            id=data["id"],
            token_id=data.get("token_id", ""),
            note_name=_preferred_value(data, "note_name", "title") or "",
            text_content=_preferred_value(data, "text_content", "content"),
            is_public=data.get("is_public", False),
            credential_val=data.get("credential_val"),
            media=media,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            revision=data.get("revision"),
        )


@dataclass
class NotebookCreateParams:
    """Parameters for creating a new notebook"""

    token_id: str
    note_name: str  # Backend uses note_name
    text_content: Optional[str] = None  # Backend uses text_content
    is_public: bool = True  # Default to public per backend
    credential_val: Optional[str] = None  # Credential for private notes

    def to_dict(self) -> dict:
        """Convert to API request dict (Form data format)"""
        data = {
            "token_id": self.token_id,
            "note_name": self.note_name,
            "is_public": str(self.is_public).lower(),  # Form data needs string
        }
        if self.text_content:
            data["text_content"] = self.text_content
        if self.credential_val:
            data["credential_val"] = self.credential_val
        return data


@dataclass
class NotebookUpdateParams:
    """Parameters for updating a notebook"""

    note_name: Optional[str] = None
    text_content: Optional[str] = None
    credential_val: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to API request dict (Form data format, only non-None fields)"""
        data = {}
        if self.note_name is not None:
            data["note_name"] = self.note_name
        if self.text_content is not None:
            data["text_content"] = self.text_content
        if self.credential_val is not None:
            data["credential_val"] = self.credential_val
        return data
