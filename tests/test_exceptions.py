import pytest

from ofspectrum.exceptions import (
    AuthenticationError,
    ConflictError,
    PaymentRequiredError,
    RateLimitError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    ValidationError,
    raise_for_error,
)


def test_private_notebook_limit_error_describes_standard_and_pro_limits():
    with pytest.raises(ValidationError) as exc:
        raise_for_error({"detail": "Private notebook limit reached for this token"}, 400)

    assert "Standard tokens do not allow new private notebooks" in str(exc.value)
    assert "grandfathered" in str(exc.value)
    assert "Pro tokens support five" in str(exc.value)
    assert "Enterprise tokens support ten" in str(exc.value)
    assert "no private notebook limit" not in str(exc.value)


@pytest.mark.parametrize(
    ("code", "status_code", "exception_type"),
    [
        ("NotebookNotFound", 404, ResourceNotFoundError),
        ("NotebookRevisionConflict", 409, ConflictError),
        ("NotebookSaveSessionRequired", 409, ConflictError),
        ("NotebookStoragePaymentRequired", 402, PaymentRequiredError),
        ("StorageChargeAuthorizationRequired", 402, PaymentRequiredError),
        ("NotebookMediaTooLarge", 413, ValidationError),
        ("NotebookCommitPayloadTooLarge", 413, ValidationError),
        ("NotebookVersionRateLimitExceeded", 429, RateLimitError),
        ("NotebookCommitUnavailable", 503, ServiceUnavailableError),
    ],
)
def test_notebook_direct_errors_map_to_typed_exceptions(
    code, status_code, exception_type
):
    with pytest.raises(exception_type) as exc:
        raise_for_error(
            {
                "error": code,
                "message": "Safe public message",
                "details": {"field": "media", "retry_after": 12},
            },
            status_code,
        )

    assert exc.value.code == code
    assert exc.value.status_code == status_code
    assert exc.value.details["field"] == "media"


def test_fastapi_detail_error_preserves_stable_code_and_safe_details():
    with pytest.raises(ConflictError) as exc:
        raise_for_error(
            {
                "detail": {
                    "error": "NotebookRevisionConflict",
                    "message": "Reload before saving.",
                    "details": {"current_revision": 4},
                }
            },
            409,
        )

    assert exc.value.code == "NotebookRevisionConflict"
    assert exc.value.details["current_revision"] == 4


@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (401, AuthenticationError),
        (402, PaymentRequiredError),
        (404, ResourceNotFoundError),
        (409, ConflictError),
        (422, ValidationError),
        (429, RateLimitError),
        (503, ServiceUnavailableError),
    ],
)
def test_unstructured_http_errors_use_status_fallback(status_code, exception_type):
    with pytest.raises(exception_type) as exc:
        raise_for_error(None, status_code)

    assert exc.value.status_code == status_code
