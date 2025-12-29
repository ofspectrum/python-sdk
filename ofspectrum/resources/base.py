"""
Base resource class for API resources
"""

from typing import TYPE_CHECKING, Optional, Dict, Any
import httpx

if TYPE_CHECKING:
    from ..client import OfSpectrum


class BaseResource:
    """Base class for API resources"""

    def __init__(self, client: "OfSpectrum"):
        self._client = client

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """
        Make an HTTP request.

        Args:
            method: HTTP method
            path: API path (will be joined with base_url)
            params: Query parameters
            json: JSON body
            data: Form data
            files: Files to upload
            timeout: Request timeout

        Returns:
            httpx.Response object
        """
        return self._client._request(
            method=method,
            path=path,
            params=params,
            json=json,
            data=data,
            files=files,
            timeout=timeout,
        )

    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> httpx.Response:
        """Make a GET request"""
        return self._request("GET", path, params=params, **kwargs)

    def _post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> httpx.Response:
        """Make a POST request"""
        return self._request("POST", path, json=json, data=data, files=files, **kwargs)

    def _patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> httpx.Response:
        """Make a PATCH request"""
        return self._request("PATCH", path, json=json, **kwargs)

    def _delete(
        self,
        path: str,
        **kwargs
    ) -> httpx.Response:
        """Make a DELETE request"""
        return self._request("DELETE", path, **kwargs)
