"""
Quota models for service usage tracking
"""

from dataclasses import dataclass, field
from typing import Optional, List, Literal


@dataclass
class Quota:
    """Represents a service quota"""

    service_name: str
    quota_type: Literal["request_limit", "duration_limit"]
    quota_limit: int
    current_usage: int
    reset_at: Optional[str] = None

    @property
    def remaining(self) -> int:
        """Get remaining quota"""
        return max(0, self.quota_limit - self.current_usage)

    @property
    def used_percentage(self) -> float:
        """Get percentage of quota used"""
        if self.quota_limit == 0:
            return 0.0
        return (self.current_usage / self.quota_limit) * 100

    @property
    def is_exceeded(self) -> bool:
        """Check if quota is exceeded"""
        return self.current_usage >= self.quota_limit

    @classmethod
    def from_dict(cls, data: dict) -> "Quota":
        """Create Quota from API response dict.

        Handles both snake_case (from /quotas/all) and camelCase (from /quota) formats.
        """
        # Handle both snake_case and camelCase field names
        service_name = data.get("service_name") or data.get("serviceName", "")
        quota_type = data.get("quota_type") or data.get("quotaType", "request_limit")
        quota_limit = data.get("quota_limit") or data.get("quotaLimit", 0)
        current_usage = data.get("current_usage") or data.get("currentUsage", 0)
        reset_at = data.get("reset_at") or data.get("resetDate") or data.get("reset_date")

        return cls(
            service_name=service_name,
            quota_type=quota_type,
            quota_limit=int(quota_limit) if quota_limit else 0,
            current_usage=int(current_usage) if current_usage else 0,
            reset_at=reset_at,
        )

    def __str__(self) -> str:
        return f"{self.service_name}: {self.current_usage}/{self.quota_limit} ({self.quota_type})"


@dataclass
class QuotaList:
    """Collection of quotas for a user"""

    quotas: List[Quota] = field(default_factory=list)

    def get(self, service_name: str) -> Optional[Quota]:
        """Get quota for a specific service"""
        for quota in self.quotas:
            if quota.service_name == service_name:
                return quota
        return None

    def get_encode_quota(self) -> Optional[Quota]:
        """Get AudioWatermarkEncode quota"""
        return self.get("AudioWatermarkEncode")

    def get_decode_quota(self) -> Optional[Quota]:
        """Get AudioWatermarkDecode quota"""
        return self.get("AudioWatermarkDecode")

    @classmethod
    def from_list(cls, data: List[dict]) -> "QuotaList":
        """Create QuotaList from API response list"""
        return cls(quotas=[Quota.from_dict(q) for q in data])

    def __iter__(self):
        return iter(self.quotas)

    def __len__(self):
        return len(self.quotas)
