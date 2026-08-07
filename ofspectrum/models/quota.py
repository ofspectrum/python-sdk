"""
Quota models for service usage tracking
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Quota:
    """Represents a service quota"""

    limit: int
    used: int
    reset_at: Optional[str] = None
    _service: str = field(default="", repr=False)
    _kind: str = field(default="", repr=False)

    @property
    def remaining(self) -> int:
        """Get remaining quota"""
        return max(0, self.limit - self.used)

    @property
    def used_percentage(self) -> float:
        """Get percentage of quota used"""
        if self.limit == 0:
            return 0.0
        return (self.used / self.limit) * 100

    @property
    def is_exceeded(self) -> bool:
        """Check if quota is exceeded"""
        return self.used >= self.limit

    @classmethod
    def from_dict(cls, data: dict) -> "Quota":
        """Create Quota from API response dict.

        Handles API response formats.
        """
        service = data.get("service_name") or data.get("serviceName", "")
        kind = data.get("quota_type") or data.get("quotaType", "request_limit")
        limit = data.get("quota_limit") or data.get("quotaLimit", 0)
        used = data.get("current_usage") or data.get("currentUsage", 0)
        reset_at = data.get("reset_at") or data.get("resetDate") or data.get("reset_date")

        return cls(
            limit=int(limit) if limit else 0,
            used=int(used) if used else 0,
            reset_at=reset_at,
            _service=service,
            _kind=kind,
        )

    def __str__(self) -> str:
        return f"remaining: {self.remaining}"


@dataclass
class QuotaList:
    """Collection of quotas for a user"""

    quotas: List[Quota] = field(default_factory=list)

    def _get_by_service(self, service: str) -> Optional[Quota]:
        """Get quota for a specific service"""
        for quota in self.quotas:
            if quota._service == service:
                return quota
        return None

    def get_encode_quota(self) -> Optional[Quota]:
        """Get AudioWatermarkEncode quota"""
        return self._get_by_service("AudioWatermarkEncode")

    def get_decode_quota(self) -> Optional[Quota]:
        """Get AudioWatermarkDecode quota"""
        return self._get_by_service("AudioWatermarkDecode")

    @classmethod
    def from_list(cls, data: List[dict]) -> "QuotaList":
        """Create QuotaList from API response list"""
        return cls(quotas=[Quota.from_dict(q) for q in data])

    def __iter__(self):
        return iter(self.quotas)

    def __len__(self):
        return len(self.quotas)
