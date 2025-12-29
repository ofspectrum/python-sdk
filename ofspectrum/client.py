"""
OfSpectrum API Client

Main entry point for the SDK.
"""

from typing import Optional, Dict, Any
import httpx

from .resources import (
    TokensResource,
    NotebooksResource,
    AudioResource,
    QuotasResource,
    # WebhooksResource,  # Not yet available
)
from .exceptions import (
    OfSpectrumError,
    AuthenticationError,
    NetworkError,
    raise_for_error,
)


class OfSpectrum:
    """
    Synchronous OfSpectrum API client.

    Example:
        from ofspectrum import OfSpectrum

        client = OfSpectrum(api_key="your_api_key")

        # List tokens
        tokens = client.tokens.list()

        # Encode watermark
        result = client.audio.encode(
            audio="input.mp3",
            token_id=tokens[0].id,
            output_path="watermarked.mp3"
        )

        # Check quota
        quota = client.quotas.get_encode_quota()
        print(f"Remaining: {quota.remaining}")
    """

    DEFAULT_BASE_URL = "https://api.ofspectrum.com/api/v1"
    DEFAULT_TIMEOUT = 120.0

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize the OfSpectrum client.

        Args:
            api_key: Your OfSpectrum API key (64-character hex string)
            base_url: Optional custom API base URL
            timeout: Request timeout in seconds (default 120)
        """
        if not api_key:
            raise ValueError("api_key is required")

        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

        # Initialize HTTP client
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            headers=self._default_headers(),
        )

        # Initialize resources
        self.tokens = TokensResource(self)
        self.notebooks = NotebooksResource(self)
        self.audio = AudioResource(self)
        self.quotas = QuotasResource(self)
        # self.webhooks = WebhooksResource(self)  # Not yet available

    def _default_headers(self) -> Dict[str, str]:
        """Get default request headers"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "OfSpectrum-Python-SDK/1.0.0",
            "Accept": "application/json",
        }

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
        Make an HTTP request to the API.

        Args:
            method: HTTP method
            path: API path
            params: Query parameters
            json: JSON body
            data: Form data
            files: Files to upload
            timeout: Optional request timeout

        Returns:
            httpx.Response

        Raises:
            AuthenticationError: If API key is invalid
            NetworkError: If network error occurs
            OfSpectrumError: For other API errors
        """
        url = path if path.startswith("/") else f"/{path}"

        request_kwargs = {
            "method": method,
            "url": url,
        }

        if params:
            request_kwargs["params"] = params

        if json:
            request_kwargs["json"] = json

        if data:
            request_kwargs["data"] = data

        if files:
            request_kwargs["files"] = files

        if timeout:
            request_kwargs["timeout"] = timeout

        try:
            response = self._client.request(**request_kwargs)

            # Check for authentication errors
            if response.status_code == 401:
                raise AuthenticationError(
                    message="Invalid or expired API key",
                    status_code=401,
                )

            return response

        except httpx.TimeoutException as e:
            raise NetworkError(f"Request timed out: {e}")
        except httpx.ConnectError as e:
            raise NetworkError(f"Connection failed: {e}")
        except httpx.RequestError as e:
            raise NetworkError(f"Network error: {e}")

    def close(self):
        """Close the HTTP client"""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class AsyncOfSpectrum:
    """
    Asynchronous OfSpectrum API client.

    Example:
        from ofspectrum import AsyncOfSpectrum

        async with AsyncOfSpectrum(api_key="your_api_key") as client:
            tokens = await client.tokens.list()
    """

    DEFAULT_BASE_URL = "https://api.ofspectrum.com/api/v1"
    DEFAULT_TIMEOUT = 120.0

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize the async OfSpectrum client.

        Args:
            api_key: Your OfSpectrum API key
            base_url: Optional custom API base URL
            timeout: Request timeout in seconds
        """
        if not api_key:
            raise ValueError("api_key is required")

        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

        # Resources will be initialized when client is opened
        self.tokens: Optional[TokensResource] = None
        self.notebooks: Optional[NotebooksResource] = None
        self.audio: Optional[AudioResource] = None
        self.quotas: Optional[QuotasResource] = None
        # self.webhooks: Optional[WebhooksResource] = None  # Not yet available

    def _default_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "OfSpectrum-Python-SDK/1.0.0",
            "Accept": "application/json",
        }

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout),
            headers=self._default_headers(),
        )

        # Create a sync client wrapper for resources
        # Note: For true async, resources would need async versions
        self.tokens = TokensResource(self)
        self.notebooks = NotebooksResource(self)
        self.audio = AudioResource(self)
        self.quotas = QuotasResource(self)
        # self.webhooks = WebhooksResource(self)  # Not yet available

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def _request(
        self,
        method: str,
        path: str,
        **kwargs
    ) -> httpx.Response:
        """
        Sync request wrapper for resource compatibility.
        For truly async operations, use the async client methods directly.
        """
        # For now, use a sync approach within async context
        # A full async implementation would require async resource methods
        import asyncio

        async def _async_request():
            if not self._client:
                raise RuntimeError("Client not initialized. Use 'async with' context.")

            url = path if path.startswith("/") else f"/{path}"
            kwargs["url"] = url
            kwargs["method"] = method

            try:
                response = await self._client.request(**kwargs)
                if response.status_code == 401:
                    raise AuthenticationError(
                        message="Invalid or expired API key",
                        status_code=401,
                    )
                return response
            except httpx.TimeoutException as e:
                raise NetworkError(f"Request timed out: {e}")
            except httpx.RequestError as e:
                raise NetworkError(f"Network error: {e}")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, can't use run_until_complete
                # Fall back to sync client for now
                import warnings
                warnings.warn(
                    "AsyncOfSpectrum resource methods are currently sync. "
                    "Use await client._async_request() for true async."
                )
                with httpx.Client(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(self._timeout),
                    headers=self._default_headers(),
                ) as sync_client:
                    url = path if path.startswith("/") else f"/{path}"
                    kwargs["url"] = url
                    kwargs["method"] = method
                    return sync_client.request(**kwargs)
            else:
                return loop.run_until_complete(_async_request())
        except RuntimeError:
            # No event loop, use sync
            with httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                headers=self._default_headers(),
            ) as sync_client:
                url = path if path.startswith("/") else f"/{path}"
                kwargs["url"] = url
                kwargs["method"] = method
                return sync_client.request(**kwargs)
