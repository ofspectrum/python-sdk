"""
OfSpectrum SDK Exceptions

All exceptions inherit from OfSpectrumError for easy catching.
"""

from typing import Optional, Dict, Any


class OfSpectrumError(Exception):
    """Base exception for all OfSpectrum SDK errors"""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:
        if self.code:
            return f"[{self.code}] {self.message}"
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, code={self.code!r})"


class AuthenticationError(OfSpectrumError):
    """Raised when authentication fails (invalid API key, expired token, etc.)"""

    def __init__(self, message: str = "Authentication failed", **kwargs):
        super().__init__(message, **kwargs)


class RateLimitError(OfSpectrumError):
    """Raised when rate limit is exceeded"""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[int] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after

    def __str__(self) -> str:
        base = super().__str__()
        if self.retry_after:
            return f"{base} (retry after {self.retry_after}s)"
        return base


class QuotaExceededError(OfSpectrumError):
    """Raised when service quota is exceeded"""

    def __init__(
        self,
        message: str = "Quota exceeded",
        service: Optional[str] = None,
        remaining: int = 0,
        reset_at: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.service = service
        self.remaining = remaining
        self.reset_at = reset_at


class ResourceNotFoundError(OfSpectrumError):
    """Raised when a requested resource is not found"""

    def __init__(
        self,
        message: str = "Resource not found",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.resource_type = resource_type
        self.resource_id = resource_id


class ValidationError(OfSpectrumError):
    """Raised when request validation fails"""

    def __init__(
        self,
        message: str = "Validation error",
        field: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.field = field


class WatermarkExistsError(OfSpectrumError):
    """Raised when trying to encode a watermark on already watermarked audio"""

    def __init__(self, message: str = "Audio already contains watermark", **kwargs):
        super().__init__(message, **kwargs)


class TimeoutError(OfSpectrumError):
    """Raised when a request times out"""

    def __init__(self, message: str = "Request timed out", **kwargs):
        super().__init__(message, **kwargs)


class ServiceUnavailableError(OfSpectrumError):
    """Raised when the service is temporarily unavailable"""

    def __init__(
        self,
        message: str = "Service temporarily unavailable",
        retry_after: Optional[int] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class NetworkError(OfSpectrumError):
    """Raised when a network error occurs"""

    def __init__(self, message: str = "Network error", **kwargs):
        super().__init__(message, **kwargs)


# Mapping from API error codes to exception classes
ERROR_CODE_MAP = {
    "AUTH_1001": AuthenticationError,
    "AUTH_1002": AuthenticationError,
    "AUTH_1003": AuthenticationError,
    "AUTH_1004": AuthenticationError,
    "AUTH_1005": RateLimitError,
    "AUTH_1006": AuthenticationError,
    "AUTH_1007": AuthenticationError,
    "RES_2001": ResourceNotFoundError,
    "RES_2002": OfSpectrumError,  # Forbidden
    "RES_2003": OfSpectrumError,  # Conflict
    "RES_2004": OfSpectrumError,  # Already exists
    "QUOTA_3001": QuotaExceededError,
    "QUOTA_3002": QuotaExceededError,
    "QUOTA_3003": QuotaExceededError,
    "QUOTA_3004": QuotaExceededError,
    "PROC_4001": TimeoutError,
    "PROC_4002": ValidationError,
    "PROC_4003": WatermarkExistsError,
    "PROC_4004": ServiceUnavailableError,
    "PROC_4005": ValidationError,
    "PROC_4006": ValidationError,
    "SYS_5001": OfSpectrumError,
    "SYS_5002": OfSpectrumError,
    "SYS_5003": OfSpectrumError,
    "SYS_5004": ServiceUnavailableError,
}


def _raise_direct_error(
    error_code: str,
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
):
    """Raise SDK exceptions for legacy/direct API error payloads."""
    details = details or {}

    # Map common legacy error codes used by tokens_router and other endpoints.
    if error_code == "QuotaExceeded":
        raise QuotaExceededError(
            message="Token quota exceeded. Please upgrade your plan or contact support.",
            code=error_code,
            status_code=status_code or 429,
            details={},
        )
    elif error_code in ("QuotaMissing", "QuotaCheckFailed"):
        raise QuotaExceededError(
            message="Token quota is temporarily unavailable. Please try again later or contact support.",
            code=error_code,
            status_code=status_code or 500,
            details={},
        )
    elif error_code in ("InsufficientBalance", "insufficient_balance") or status_code == 402:
        raise QuotaExceededError(
            message="Insufficient balance. Please add funds or choose a subscription.",
            code=error_code,
            status_code=status_code or 402,
            details={},
        )
    elif error_code == "Unauthorized":
        raise AuthenticationError(message=message, code=error_code, status_code=status_code or 403, details=details)
    elif error_code in ("DuplicateName", "ValidationError"):
        raise ValidationError(message=message, code=error_code, status_code=status_code or 400, details=details)
    elif error_code == "Missing required fields" or error_code == "InvalidField":
        raise ValidationError(message=message, code=error_code, status_code=status_code or 400, details=details)
    elif error_code == "UnableToGenerate":
        raise OfSpectrumError(message=message, code=error_code, status_code=status_code or 500, details=details)
    else:
        raise OfSpectrumError(message=message, code=error_code, status_code=status_code or 500, details=details)


def _raise_detail_error(message: str, status_code: int):
    """Raise sanitized SDK exceptions for FastAPI detail strings."""
    if message == "Only one public notebook allowed per token":
        raise ValidationError(
            message="This token already has a public notebook. Each token supports one public notebook.",
            code="NotebookLimit",
            status_code=status_code or 400,
            details={},
        )
    if message == "Private notebook limit reached for this token":
        raise ValidationError(
            message=(
                "Private notebook limit reached for this token. Standard tokens do not support "
                "private notebooks; Pro tokens support one private notebook."
            ),
            code="NotebookLimit",
            status_code=status_code or 400,
            details={},
        )
    raise OfSpectrumError(message=message, status_code=status_code)


def raise_for_error(response_data, status_code: int):
    """
    Parse API error response and raise appropriate exception.

    Args:
        response_data: The JSON response from the API (dict or list)
        status_code: HTTP status code

    Raises:
        OfSpectrumError: Appropriate exception based on error code
    """
    # If response is a list (e.g., tokens.list returns a list), it's not an error
    if not isinstance(response_data, dict):
        return

    # Check for direct error format: {"error": "ErrorCode", "message": "..."}
    # This is used by tokens_router and other legacy endpoints
    if "error" in response_data and isinstance(response_data.get("error"), str):
        error_code = response_data.get("error")
        message = response_data.get("message", error_code)
        _raise_direct_error(error_code, message, status_code, response_data)

    if response_data.get("status") != "error":
        # Also check for FastAPI validation errors (detail field)
        if "detail" in response_data and status_code >= 400:
            detail = response_data.get("detail")
            if isinstance(detail, str):
                _raise_detail_error(detail, status_code)
            elif isinstance(detail, dict):
                error_code = detail.get("error") or detail.get("code")
                message = detail.get("message") or detail.get("detail") or error_code or "API request failed"
                if isinstance(error_code, str):
                    _raise_direct_error(error_code, message, status_code, detail)
                raise OfSpectrumError(message=str(message), status_code=status_code, details=detail)
            elif isinstance(detail, list):
                # FastAPI validation error format
                messages = [f"{d.get('loc', ['?'])[-1]}: {d.get('msg', '?')}" for d in detail]
                raise ValidationError(message="; ".join(messages), status_code=status_code)
        return

    error = response_data.get("error", {})
    code = error.get("code")
    message = error.get("message", "Unknown error")
    details = error.get("details", {})

    # Get appropriate exception class
    exc_class = ERROR_CODE_MAP.get(code, OfSpectrumError)

    # Build kwargs based on exception type
    kwargs = {
        "message": message,
        "code": code,
        "status_code": status_code,
        "details": details,
    }

    if exc_class == RateLimitError:
        kwargs["retry_after"] = details.get("retry_after")
    elif exc_class == QuotaExceededError:
        kwargs["service"] = details.get("service")
        kwargs["remaining"] = details.get("remaining", 0)
        kwargs["reset_at"] = details.get("reset_at")
    elif exc_class == ResourceNotFoundError:
        kwargs["resource_type"] = details.get("resource_type")
        kwargs["resource_id"] = details.get("resource_id")
    elif exc_class == ValidationError:
        kwargs["field"] = details.get("field")

    raise exc_class(**kwargs)
