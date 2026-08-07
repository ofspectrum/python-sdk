"""
Quotas resource for checking service usage
"""

from ..exceptions import raise_for_error
from ..models.quota import Quota, QuotaList
from .base import BaseResource


class QuotasResource(BaseResource):
    """Resource for checking service quotas"""

    def _get_quota(self, service: str) -> Quota:
        """Get quota for an OfSpectrum service."""
        response = self._get(f"/usage/quota?serviceName={service}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns quota data directly
        quota_data = data if isinstance(data, dict) and "quotaLimit" in data else data.get("data", {})
        return Quota.from_dict(quota_data)

    def _get_all_quotas(self) -> QuotaList:
        """Get all quotas for the current user."""
        response = self._get("/usage/quotas/all")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns a list of quotas directly
        quotas_data = data if isinstance(data, list) else data.get("data", {}).get("quotas", [])
        return QuotaList.from_list(quotas_data)

    def get_encode_quota(self) -> Quota:
        """
        Shortcut to get AudioWatermarkEncode quota.

        Returns:
            Quota for encoding service
        """
        return self._get_quota("AudioWatermarkEncode")

    def get_decode_quota(self) -> Quota:
        """
        Shortcut to get AudioWatermarkDecode quota.

        Returns:
            Quota for decoding service
        """
        return self._get_quota("AudioWatermarkDecode")

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
