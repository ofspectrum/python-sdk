"""
Token models for watermark tokens
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime


@dataclass
class Token:
    """Represents a watermark token"""

    id: str
    name: str
    token_type: Literal["standard", "creator", "enterprise"]
    public_key: int
    enterprise_verification: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Token":
        """Create Token from API response dict"""
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            token_type=data.get("token_type", "standard"),
            public_key=data.get("public_key", 258),
            enterprise_verification=data.get("enterprise_verification", False),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class TokenCreateParams:
    """Parameters for creating a new token"""

    name: str
    token_type: Literal["standard", "creator", "enterprise"] = "standard"
    public_key: Optional[int] = None
    enterprise_verification: bool = False

    def to_dict(self) -> dict:
        """Convert to API request dict"""
        data = {
            "name": self.name,
            "token_type": self.token_type,
            "enterprise_verification": self.enterprise_verification,
        }
        if self.public_key is not None:
            data["public_key"] = self.public_key
        return data


@dataclass
class TokenUpdateParams:
    """Parameters for updating a token"""

    name: Optional[str] = None
    public_key: Optional[int] = None
    enterprise_verification: Optional[bool] = None

    def to_dict(self) -> dict:
        """Convert to API request dict (only non-None fields)"""
        data = {}
        if self.name is not None:
            data["name"] = self.name
        if self.public_key is not None:
            data["public_key"] = self.public_key
        if self.enterprise_verification is not None:
            data["enterprise_verification"] = self.enterprise_verification
        return data
