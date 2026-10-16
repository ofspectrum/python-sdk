"""
Audio processing result models
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Literal, Optional


@dataclass
class EncodeResult:
    """Result of watermark encoding operation"""

    success: bool
    download_url: Optional[str] = None
    audio_duration: Optional[float] = None
    token_id: Optional[str] = None
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    expires_in: int = 3600
    audio_bytes: Optional[bytes] = None  # Used for stream mode
    quality_warning: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "EncodeResult":
        """Create EncodeResult from API response dict"""
        raw_duration = data.get("audio_duration")
        if raw_duration is None:
            audio_duration = None
        else:
            try:
                audio_duration = float(raw_duration)
            except (TypeError, ValueError) as exc:
                raise ValueError("audio_duration must be a finite number") from exc
            if not math.isfinite(audio_duration):
                raise ValueError("audio_duration must be a finite number")
        return cls(
            success=True,
            download_url=data.get("download_url"),
            audio_duration=audio_duration,
            token_id=data.get("token_id"),
            file_name=data.get("file_name"),
            content_type=data.get("content_type"),
            expires_in=data.get("expires_in", 3600),
            quality_warning=bool(data.get("quality_warning", False)),
        )

    @classmethod
    def from_bytes(
        cls,
        audio_bytes: bytes,
        audio_duration: float,
        token_id: str,
        file_name: str,
        content_type: str,
        quality_warning: bool = False,
    ) -> "EncodeResult":
        """Create EncodeResult from audio bytes (stream mode)"""
        return cls(
            success=True,
            audio_bytes=audio_bytes,
            audio_duration=audio_duration,
            token_id=token_id,
            file_name=file_name,
            content_type=content_type,
            quality_warning=quality_warning,
        )

    def save(self, path: str) -> None:
        """
        Save encoded audio to file.

        Args:
            path: File path to save to

        Raises:
            ValueError: If no audio data available
        """
        if self.audio_bytes:
            with open(path, "wb") as f:
                f.write(self.audio_bytes)
        elif self.download_url:
            import httpx
            with httpx.Client() as client:
                response = client.get(self.download_url)
                response.raise_for_status()
                with open(path, "wb") as f:
                    f.write(response.content)
        else:
            raise ValueError("No audio data available to save")


@dataclass
class DecodeMatch:
    """One authorized product-level watermark match."""

    watermarked: bool
    token_id: Optional[str] = None
    access: Optional[Literal["owner", "public", "retired"]] = None
    token_type: Optional[str] = None
    enterprise_verification: Optional[bool] = None
    public_key_match: Optional[bool] = None
    requires_private_key: Optional[bool] = None
    token_retired: Optional[bool] = None
    ai_auth: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: dict) -> "DecodeMatch":
        access = data.get("access")
        safe_access = access if access in ("owner", "public", "retired") else None
        raw_ai_auth = data.get("ai_auth")
        allowed_ai_auth = {
            "ai_auth_enabled",
            "ai_auth_access_type",
            "ai_auth_price",
            "ai_auth_other_instructions",
            "ai_auth_tags",
        }
        safe_ai_auth = {
            key: value
            for source in (raw_ai_auth if isinstance(raw_ai_auth, dict) else {}, data)
            for key, value in source.items()
            if key in allowed_ai_auth
        }
        return cls(
            watermarked=data.get("watermarked", 0) == 1,
            token_id=data.get("token_id") if isinstance(data.get("token_id"), str) else None,
            access=safe_access,
            token_type=data.get("token_type") if isinstance(data.get("token_type"), str) else None,
            enterprise_verification=data.get("enterprise_verification")
            if isinstance(data.get("enterprise_verification"), bool) else None,
            public_key_match=data.get("public_key_match")
            if isinstance(data.get("public_key_match"), bool) else None,
            requires_private_key=data.get("requires_private_key")
            if isinstance(data.get("requires_private_key"), bool) else None,
            token_retired=data.get("token_retired")
            if isinstance(data.get("token_retired"), bool) else None,
            ai_auth=safe_ai_auth or None,
        )


@dataclass
class DecodeResult:
    """
    Result of watermark decoding operation.

    The API returns a simplified response for SDK/API calls:
    - watermarked: Whether a watermark was detected (True/False)
    - token_id: The token ID if watermark was detected, None otherwise
    """

    watermarked: bool
    token_id: Optional[str] = None
    access: Optional[Literal["owner", "public", "retired"]] = None
    token_type: Optional[str] = None
    enterprise_verification: Optional[bool] = None
    public_key_match: Optional[bool] = None
    requires_private_key: Optional[bool] = None
    token_retired: Optional[bool] = None
    ai_auth: Optional[Dict[str, Any]] = None
    results: List[DecodeMatch] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "DecodeResult":
        """Create DecodeResult from API response dict"""
        primary = DecodeMatch.from_dict(data)
        raw_results = data.get("results")
        results = [DecodeMatch.from_dict(item) for item in raw_results if isinstance(item, dict)] \
            if isinstance(raw_results, list) else []
        return cls(
            watermarked=primary.watermarked,
            token_id=primary.token_id,
            access=primary.access,
            token_type=primary.token_type,
            enterprise_verification=primary.enterprise_verification,
            public_key_match=primary.public_key_match,
            requires_private_key=primary.requires_private_key,
            token_retired=primary.token_retired,
            ai_auth=primary.ai_auth,
            results=results,
        )

    @property
    def is_watermarked(self) -> bool:
        """Alias for watermarked property"""
        return self.watermarked


@dataclass
class StreamingEncodeResult:
    """Result of a streaming PCM watermark encode operation."""

    encoded_pcm: bytes
    token_id: str
    sample_rate: int = 48000
    channels: int = 1
    events: Optional[List[Dict[str, Any]]] = None
    quality_warning: bool = False

    @property
    def audio_duration(self) -> float:
        if self.sample_rate <= 0 or self.channels <= 0:
            return 0.0
        return len(self.encoded_pcm) / float(4 * self.sample_rate * self.channels)
