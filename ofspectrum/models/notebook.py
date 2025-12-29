"""
Notebook models for watermark token notes
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class NotebookMedia:
    """Represents a media file attached to a notebook"""

    id: str
    filename: str
    file_url: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "NotebookMedia":
        """Create NotebookMedia from API response dict"""
        return cls(
            id=data["id"],
            filename=data.get("filename", ""),
            file_url=data.get("file_url") or data.get("media_public"),
            file_size=data.get("file_size"),
            content_type=data.get("content_type"),
            created_at=data.get("created_at"),
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
    media: List[NotebookMedia] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

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
        media_list = data.get("media") or []
        return cls(
            id=data["id"],
            token_id=data.get("token_id", ""),
            note_name=data.get("note_name", "") or data.get("title", ""),
            text_content=data.get("text_content") or data.get("content"),
            is_public=data.get("is_public", False),
            credential_val=data.get("credential_val"),
            media=[NotebookMedia.from_dict(m) for m in media_list],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
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
