"""
OfSpectrum SDK Exceptions

All exceptions inherit from OfSpectrumError for easy catching.
"""

from typing import Any, Dict, Optional, Type


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


class PaymentRequiredError(QuotaExceededError):
    """Raised when an operation requires an authorized payment path."""

    def __init__(self, message: str = "Payment required", **kwargs):
        super().__init__(message, **kwargs)


class ConflictError(OfSpectrumError):
    """Raised when revision, session, or idempotency state conflicts."""

    def __init__(self, message: str = "Request conflicts with current state", **kwargs):
        super().__init__(message, **kwargs)


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
    "DuplicateName": ValidationError,
    "NotFound": ResourceNotFoundError,
    "ValidationError": ValidationError,
}

NOTEBOOK_ERROR_CODE_MAP = {
    "AuthenticationRequired": AuthenticationError,
    "InvalidApiKey": AuthenticationError,
    "InvalidApiKeyActor": AuthenticationError,
    "NotebookNotFound": ResourceNotFoundError,
    "NotebookStoragePaymentRequired": PaymentRequiredError,
    "NotebookStorageAutoExpandDisabled": PaymentRequiredError,
    "NotebookStorageCapacityExceeded": PaymentRequiredError,
    "StorageChargeAuthorizationRequired": PaymentRequiredError,
    "NotebookStorageChargeAuthorizationRequired": PaymentRequiredError,
    "NotebookRevisionConflict": ConflictError,
    "NotebookCommitIdempotencyConflict": ConflictError,
    "NotebookStorageIdempotencyConflict": ConflictError,
    "NotebookIdempotencyConflict": ConflictError,
    "NotebookStagedReferenceConflict": ConflictError,
    "NotebookCommitConflict": ConflictError,
    "NotebookSaveSessionConflict": ConflictError,
    "NotebookSaveSessionRequired": ConflictError,
    "NotebookMediaTooLarge": ValidationError,
    "NotebookMediaFileLimitExceeded": ValidationError,
    "NotebookMediaFileLimit": ValidationError,
    "NotebookTextTooLarge": ValidationError,
    "UnsupportedNotebookMedia": ValidationError,
    "NotebookMediaHashMismatch": ValidationError,
    "NotebookCommitValidationError": ValidationError,
    "NotebookCommitPayloadTooLarge": ValidationError,
    "NotebookStorageAdmissionRejected": ValidationError,
    "InvalidNotebookStorageRequest": ValidationError,
    "InvalidNotebookIdempotencyKey": ValidationError,
    "InvalidNotebookCommitRequest": ValidationError,
    "NotebookStorageAccountNotEligible": ValidationError,
    "NotebookVersionRateLimitExceeded": RateLimitError,
    "NotebookStorageUnavailable": ServiceUnavailableError,
    "NotebookCommitUnavailable": ServiceUnavailableError,
    "NotebookStorageOperationFailed": ServiceUnavailableError,
    "NotebookObjectUploadFailed": ServiceUnavailableError,
    "NotebookObjectUploadUncertain": ServiceUnavailableError,
}

ERROR_CODE_MAP.update(NOTEBOOK_ERROR_CODE_MAP)


def _exception_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    normalized = dict(details)
    nested = details.get("details")
    if isinstance(nested, dict):
        normalized.update(nested)
    return normalized


def _raise_mapped_error(
    exc_class: Type[OfSpectrumError],
    *,
    error_code: Optional[str],
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
):
    normalized_details = _exception_details(details)
    kwargs = {
        "message": message,
        "code": error_code,
        "status_code": status_code,
        "details": normalized_details,
    }

    if issubclass(exc_class, RateLimitError):
        kwargs["retry_after"] = normalized_details.get("retry_after")
    elif issubclass(exc_class, ServiceUnavailableError):
        kwargs["retry_after"] = normalized_details.get("retry_after")
    elif issubclass(exc_class, QuotaExceededError):
        kwargs["service"] = normalized_details.get("service")
        kwargs["remaining"] = normalized_details.get("remaining", 0)
        kwargs["reset_at"] = normalized_details.get("reset_at")
    elif issubclass(exc_class, ResourceNotFoundError):
        kwargs["resource_type"] = normalized_details.get("resource_type")
        kwargs["resource_id"] = normalized_details.get("resource_id")
    elif issubclass(exc_class, ValidationError):
        kwargs["field"] = normalized_details.get("field")

    raise exc_class(**kwargs)


def _exception_class_for_status(status_code: int) -> Type[OfSpectrumError]:
    if status_code == 401:
        return AuthenticationError
    if status_code == 402:
        return PaymentRequiredError
    if status_code == 404:
        return ResourceNotFoundError
    if status_code == 409:
        return ConflictError
    if status_code in (400, 413, 415, 422):
        return ValidationError
    if status_code == 429:
        return RateLimitError
    if status_code in (502, 503, 504):
        return ServiceUnavailableError
    return OfSpectrumError


def _raise_status_error(
    status_code: int,
    *,
    message: str = "API request failed",
    error_code: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
):
    _raise_mapped_error(
        _exception_class_for_status(status_code),
        error_code=error_code,
        message=message,
        status_code=status_code,
        details=details,
    )


def _raise_direct_error(
    error_code: str,
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
):
    """Raise SDK exceptions for legacy/direct API error payloads."""
    details = details or {}

    notebook_exception = NOTEBOOK_ERROR_CODE_MAP.get(error_code)
    if notebook_exception is not None:
        _raise_mapped_error(
            notebook_exception,
            error_code=error_code,
            message=message,
            status_code=status_code,
            details=details,
        )

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
    elif error_code in ("DuplicateName", "NotebookMediaFileLimit", "ValidationError"):
        raise ValidationError(message=message, code=error_code, status_code=status_code or 400, details=details)
    elif error_code == "Missing required fields" or error_code == "InvalidField":
        raise ValidationError(message=message, code=error_code, status_code=status_code or 400, details=details)
    elif error_code == "UnableToGenerate":
        raise OfSpectrumError(message=message, code=error_code, status_code=status_code or 500, details=details)
    else:
        _raise_status_error(
            status_code or 500,
            message=message,
            error_code=error_code,
            details=details,
        )


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
                "Private notebook limit reached for this token. Standard tokens do not allow new "
                "private notebooks; existing private notebooks are grandfathered. Pro tokens "
                "support five private notebooks, and Enterprise tokens support ten."
            ),
            code="NotebookLimit",
            status_code=status_code or 400,
            details={},
        )
    _raise_status_error(status_code, message=message)


def raise_for_error(response_data, status_code: int):
    """
    Parse API error response and raise appropriate exception.

    Args:
        response_data: The JSON response from the API (dict or list)
        status_code: HTTP status code

    Raises:
        OfSpectrumError: Appropriate exception based on error code
    """
    # Successful list responses (for example tokens.list) are not errors.
    if not isinstance(response_data, dict):
        if status_code >= 400:
            _raise_status_error(status_code)
        return

    # Check for direct error format: {"error": "ErrorCode", "message": "..."}
    # This is used by tokens_router and other legacy endpoints
    if "error" in response_data and isinstance(response_data.get("error"), str):
        error_code = response_data.get("error")
        message = response_data.get("message", error_code)
        _raise_direct_error(error_code, message, status_code, response_data)

    direct_error = response_data.get("error")
    if (
        status_code >= 400
        and response_data.get("status") != "error"
        and isinstance(direct_error, dict)
    ):
        error_code = direct_error.get("code") or direct_error.get("error")
        message = direct_error.get("message") or response_data.get("message")
        if isinstance(error_code, str):
            _raise_mapped_error(
                ERROR_CODE_MAP.get(
                    error_code, _exception_class_for_status(status_code)
                ),
                error_code=error_code,
                message=str(message or error_code),
                status_code=status_code,
                details=direct_error,
            )

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
                _raise_status_error(
                    status_code,
                    message=str(message),
                    details=detail,
                )
            elif isinstance(detail, list):
                # FastAPI validation error format
                messages = [f"{d.get('loc', ['?'])[-1]}: {d.get('msg', '?')}" for d in detail]
                raise ValidationError(message="; ".join(messages), status_code=status_code)
        if status_code >= 400:
            message = response_data.get("message")
            _raise_status_error(
                status_code,
                message=message if isinstance(message, str) else "API request failed",
            )
        return

    error = response_data.get("error", {})
    code = error.get("code")
    message = error.get("message", "Unknown error")
    details = error.get("details", {})

    # Get appropriate exception class
    exc_class = ERROR_CODE_MAP.get(code, _exception_class_for_status(status_code))
    _raise_mapped_error(
        exc_class,
        error_code=code,
        message=message,
        status_code=status_code,
        details=details,
    )
