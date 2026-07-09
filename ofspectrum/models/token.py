"""
Token models for watermark tokens
"""

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional


UNSET = object()


@dataclass
class AiAuthTag:
    """Reusable AI authorization tag owned by the current account."""

    id: str
    tag: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "AiAuthTag":
        return cls(
            id=data["id"],
            tag=data.get("tag", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class Token:
    """Represents a watermark token."""

    id: str
    name: str
    token_type: Literal["standard", "pro", "enterprise"]
    public_key: Optional[int] = None
    enterprise_verification: bool = False
    max_private_notes: Optional[int] = None
    ai_auth_enabled: bool = False
    ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None
    ai_auth_price: Optional[float] = None
    ai_auth_other_instructions: Optional[str] = None
    ai_auth_tags: List[str] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Token":
        """Create Token from API response dict"""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            token_type=data.get("token_type", "standard"),
            public_key=data.get("public_key"),
            enterprise_verification=data.get("enterprise_verification", False),
            max_private_notes=None
            if data.get("max_private_notes") is None or int(data.get("max_private_notes", 0)) < 0
            else int(data.get("max_private_notes", 0)),
            ai_auth_enabled=data.get("ai_auth_enabled", False),
            ai_auth_access_type=data.get("ai_auth_access_type") or None,
            ai_auth_price=data.get("ai_auth_price"),
            ai_auth_other_instructions=data.get("ai_auth_other_instructions") or None,
            ai_auth_tags=list(data.get("ai_auth_tags") or []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class TokenCreateParams:
    """Parameters for creating a new token"""

    name: str
    token_type: Literal["standard", "pro"] = "standard"
    public_key: Optional[int] = None
    ai_auth_enabled: bool = False
    ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None
    ai_auth_price: Optional[float] = None
    ai_auth_other_instructions: Optional[str] = None
    ai_auth_tags: Optional[List[str]] = None

    def to_dict(self) -> dict:
        """Convert to API request dict"""
        data = {
            "name": self.name,
            "token_type": self.token_type,
        }
        if self.public_key is not None:
            data["public_key"] = self.public_key
        if self.ai_auth_enabled:
            data["ai_auth_enabled"] = True
        if self.ai_auth_access_type is not None:
            data["ai_auth_access_type"] = self.ai_auth_access_type
        if self.ai_auth_price is not None:
            data["ai_auth_price"] = self.ai_auth_price
        if self.ai_auth_other_instructions is not None:
            data["ai_auth_other_instructions"] = self.ai_auth_other_instructions
        if self.ai_auth_tags is not None:
            data["ai_auth_tags"] = self.ai_auth_tags
        return data


@dataclass
class TokenUpdateParams:
    """Parameters for updating a token"""

    name: Optional[str] = None
    public_key: Optional[int] = None
    token_type: Optional[Literal["standard", "pro", "enterprise"]] = None
    enterprise_verification: Optional[bool] = None
    ai_auth_enabled: Optional[bool] = None
    ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None
    ai_auth_price: Any = UNSET
    ai_auth_other_instructions: Optional[str] = None
    ai_auth_tags: Optional[List[str]] = None

    def to_dict(self) -> dict:
        """Convert to API request dict (only non-None fields)"""
        data = {}
        if self.name is not None:
            data["name"] = self.name
        if self.public_key is not None:
            data["public_key"] = self.public_key
        if self.token_type is not None:
            data["token_type"] = self.token_type
        if self.enterprise_verification is not None:
            data["enterprise_verification"] = self.enterprise_verification
        if self.ai_auth_enabled is not None:
            data["ai_auth_enabled"] = self.ai_auth_enabled
        if self.ai_auth_access_type is not None:
            data["ai_auth_access_type"] = self.ai_auth_access_type
        if self.ai_auth_price is not UNSET:
            data["ai_auth_price"] = self.ai_auth_price
        if self.ai_auth_other_instructions is not None:
            data["ai_auth_other_instructions"] = self.ai_auth_other_instructions
        if self.ai_auth_tags is not None:
            data["ai_auth_tags"] = self.ai_auth_tags
        return data
