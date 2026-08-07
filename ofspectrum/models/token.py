"""
Token models for watermark tokens
"""

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional, Union


class _UnsetType:
    """Sentinel type used to distinguish omission from an explicit ``None``."""

    __slots__ = ()


UNSET = _UnsetType()
OptionalBoolArgument = Union[bool, None, _UnsetType]


def _validate_optional_bool_argument(value: Any, field_name: str) -> None:
    if value is UNSET or value is None or isinstance(value, bool):
        return
    raise ValueError(f"{field_name} must be True, False, None, or omitted")


def _validate_public_key(value: Any, *, required: bool = False) -> None:
    if value is None:
        if required:
            raise ValueError("public_key is required for pro tokens")
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("public_key must be an integer")


def _optional_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _effective_bool(value: Any) -> bool:
    return value if isinstance(value, bool) else False


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized >= 0 else 0


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
    version_control_override: Optional[bool] = None
    storage_auto_expand_override: Optional[bool] = None
    version_control_enabled: bool = False
    storage_auto_expand_enabled: bool = False
    storage_entitlement_bytes: int = 0
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
            version_control_override=_optional_bool(
                data.get("version_control_override")
            ),
            storage_auto_expand_override=_optional_bool(
                data.get("storage_auto_expand_override")
            ),
            version_control_enabled=_effective_bool(
                data.get("version_control_enabled")
            ),
            storage_auto_expand_enabled=_effective_bool(
                data.get("storage_auto_expand_enabled")
            ),
            storage_entitlement_bytes=_non_negative_int(
                data.get("storage_entitlement_bytes")
            ),
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
    version_control_override: OptionalBoolArgument = UNSET
    storage_auto_expand_override: OptionalBoolArgument = UNSET

    def __post_init__(self) -> None:
        _validate_public_key(self.public_key, required=self.token_type == "pro")
        _validate_optional_bool_argument(
            self.version_control_override, "version_control_override"
        )
        _validate_optional_bool_argument(
            self.storage_auto_expand_override, "storage_auto_expand_override"
        )

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
        if self.version_control_override is not UNSET:
            data["version_control_override"] = self.version_control_override
        if self.storage_auto_expand_override is not UNSET:
            data["storage_auto_expand_override"] = self.storage_auto_expand_override
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
    version_control_override: OptionalBoolArgument = UNSET
    storage_auto_expand_override: OptionalBoolArgument = UNSET

    def __post_init__(self) -> None:
        _validate_public_key(self.public_key)
        _validate_optional_bool_argument(
            self.version_control_override, "version_control_override"
        )
        _validate_optional_bool_argument(
            self.storage_auto_expand_override, "storage_auto_expand_override"
        )

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
        if self.version_control_override is not UNSET:
            data["version_control_override"] = self.version_control_override
        if self.storage_auto_expand_override is not UNSET:
            data["storage_auto_expand_override"] = self.storage_auto_expand_override
        return data
