"""
Audio processing result models
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EncodeResult:
    """Result of watermark encoding operation"""

    success: bool
    download_url: Optional[str] = None
    audio_duration: Optional[int] = None
    token_id: Optional[str] = None
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    expires_in: int = 3600
    audio_bytes: Optional[bytes] = None  # Used for stream mode

    @classmethod
    def from_dict(cls, data: dict) -> "EncodeResult":
        """Create EncodeResult from API response dict"""
        return cls(
            success=True,
            download_url=data.get("download_url"),
            audio_duration=data.get("audio_duration"),
            token_id=data.get("token_id"),
            file_name=data.get("file_name"),
            content_type=data.get("content_type"),
            expires_in=data.get("expires_in", 3600),
        )

    @classmethod
    def from_bytes(
        cls,
        audio_bytes: bytes,
        audio_duration: int,
        token_id: str,
        file_name: str,
        content_type: str,
    ) -> "EncodeResult":
        """Create EncodeResult from audio bytes (stream mode)"""
        return cls(
            success=True,
            audio_bytes=audio_bytes,
            audio_duration=audio_duration,
            token_id=token_id,
            file_name=file_name,
            content_type=content_type,
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
class DecodeResult:
    """
    Result of watermark decoding operation.

    The API returns a simplified response for SDK/API calls:
    - watermarked: Whether a watermark was detected (True/False)
    - token_id: The token ID if watermark was detected, None otherwise
    """

    watermarked: bool
    token_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "DecodeResult":
        """Create DecodeResult from API response dict"""
        return cls(
            watermarked=data.get("watermarked", 0) == 1,
            token_id=data.get("token_id"),
        )

    @property
    def is_watermarked(self) -> bool:
        """Alias for watermarked property"""
        return self.watermarked
