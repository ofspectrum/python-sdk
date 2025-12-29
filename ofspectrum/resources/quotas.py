"""
Quotas resource for checking service usage
"""

from typing import Optional
from .base import BaseResource
from ..models.quota import Quota, QuotaList
from ..exceptions import raise_for_error


class QuotasResource(BaseResource):
    """Resource for checking service quotas"""

    def get(self, service_name: str) -> Quota:
        """
        Get quota for a specific service.

        Args:
            service_name: Service name (e.g., "AudioWatermarkEncode")

        Returns:
            Quota object

        Example:
            quota = client.quotas.get("AudioWatermarkEncode")
            print(f"Remaining: {quota.remaining}/{quota.quota_limit}")
        """
        response = self._get(f"/usage/quota?serviceName={service_name}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns quota data directly
        quota_data = data if isinstance(data, dict) and "quotaLimit" in data else data.get("data", {})
        return Quota.from_dict(quota_data)

    def get_all(self) -> QuotaList:
        """
        Get all quotas for the current user.

        Returns:
            QuotaList with all service quotas

        Example:
            quotas = client.quotas.get_all()
            for quota in quotas:
                print(f"{quota.service_name}: {quota.remaining} remaining")
        """
        response = self._get("/usage/quotas/all")
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns a list of quotas directly
        quotas_data = data if isinstance(data, list) else data.get("data", {}).get("quotas", [])
        return QuotaList.from_list(quotas_data)

    def get_encode_quota(self) -> Quota:
        """
        Shortcut to get AudioWatermarkEncode quota.

        Returns:
            Quota for encoding service
        """
        return self.get("AudioWatermarkEncode")

    def get_decode_quota(self) -> Quota:
        """
        Shortcut to get AudioWatermarkDecode quota.

        Returns:
            Quota for decoding service
        """
        return self.get("AudioWatermarkDecode")

    def check_encode_available(self, duration_seconds: int) -> bool:
        """
        Check if there's enough quota for encoding a given duration.

        Args:
            duration_seconds: Duration of audio to encode

        Returns:
            True if quota is available
        """
        quota = self.get_encode_quota()
        return quota.remaining >= duration_seconds

    def check_decode_available(self, duration_seconds: int) -> bool:
        """
        Check if there's enough quota for decoding a given duration.

        Args:
            duration_seconds: Duration of audio to decode

        Returns:
            True if quota is available
        """
        quota = self.get_decode_quota()
        return quota.remaining >= duration_seconds
