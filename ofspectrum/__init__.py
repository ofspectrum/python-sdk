"""
OfSpectrum Python SDK

Audio watermarking API client.

Example:
    from ofspectrum import OfSpectrum

    client = OfSpectrum(api_key="your_api_key")

    # Create a token
    token = client.tokens.create(name="My Token")

    # Encode watermark
    result = client.audio.encode(
        audio="input.mp3",
        token_id=token.id,
        output_path="watermarked.mp3"
    )
    print(f"Encoded {result.audio_duration}s of audio")

    # Decode watermark
    decode = client.audio.decode("suspect.mp3")
    if decode.watermarked:
        print(f"Found watermark: {decode.token_id}")

    # Check quota
    quota = client.quotas.get_encode_quota()
    print(f"Remaining: {quota.remaining}/{quota.limit}")
"""

__version__ = "1.3.1"
__author__ = "OfSpectrum"

from .client import AsyncOfSpectrum, OfSpectrum
from .exceptions import (
    AuthenticationError,
    ConflictError,
    NetworkError,
    OfSpectrumError,
    PaymentRequiredError,
    QuotaExceededError,
    RateLimitError,
    ResourceNotFoundError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
    WatermarkExistsError,
)
from .models import (
    AiAuthTag,
    DecodeResult,
    EncodeResult,
    Notebook,
    NotebookCommitMedia,
    NotebookCommitResponse,
    NotebookCreateParams,
    NotebookDesiredMedia,
    NotebookDesiredState,
    NotebookEffectiveSettings,
    NotebookMedia,
    NotebookSaveSession,
    NotebookSaveSessionCancellation,
    NotebookSaveSessionStatus,
    NotebookSettingOverrides,
    NotebookSettingsResponse,
    NotebookStagedUpload,
    NotebookStorageAdmission,
    Quota,
    QuotaList,
    StreamingEncodeResult,
    Token,
    TokenCreateParams,
    TokenUpdateParams,
)
from .resources.audio import StreamEncodePool
from .utils import RetryConfig, with_retry

__all__ = [
    # Client
    "OfSpectrum",
    "AsyncOfSpectrum",
    "StreamEncodePool",
    # Exceptions
    "OfSpectrumError",
    "AuthenticationError",
    "RateLimitError",
    "QuotaExceededError",
    "ResourceNotFoundError",
    "ValidationError",
    "WatermarkExistsError",
    "TimeoutError",
    "ServiceUnavailableError",
    "NetworkError",
    "ConflictError",
    "PaymentRequiredError",
    # Models
    "Token",
    "AiAuthTag",
    "TokenCreateParams",
    "TokenUpdateParams",
    "Notebook",
    "NotebookMedia",
    "NotebookCreateParams",
    "EncodeResult",
    "DecodeResult",
    "StreamingEncodeResult",
    "Quota",
    "QuotaList",
    "NotebookSettingOverrides",
    "NotebookEffectiveSettings",
    "NotebookSettingsResponse",
    "NotebookDesiredMedia",
    "NotebookDesiredState",
    "NotebookStorageAdmission",
    "NotebookSaveSession",
    "NotebookStagedUpload",
    "NotebookSaveSessionStatus",
    "NotebookSaveSessionCancellation",
    "NotebookCommitMedia",
    "NotebookCommitResponse",
    # Utils
    "RetryConfig",
    "with_retry",
]
