"""
OfSpectrum Python SDK

Audio watermarking and AI detection API client.

Example:
    from ofspectrum import OfSpectrum

    client = OfSpectrum(api_key="your_api_key")

    # Create a token
    token = client.tokens.create(name="My Token", token_type="creator")

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
    print(f"Remaining: {quota.remaining}/{quota.quota_limit}")
"""

__version__ = "1.1.3"
__author__ = "OfSpectrum"

from .client import OfSpectrum, AsyncOfSpectrum
from .exceptions import (
    OfSpectrumError,
    AuthenticationError,
    RateLimitError,
    QuotaExceededError,
    ResourceNotFoundError,
    ValidationError,
    WatermarkExistsError,
    TimeoutError,
    ServiceUnavailableError,
    NetworkError,
)
from .models import (
    Token,
    TokenCreateParams,
    TokenUpdateParams,
    Notebook,
    NotebookMedia,
    NotebookCreateParams,
    EncodeResult,
    DecodeResult,
    Quota,
    QuotaList,
)
from .utils import RetryConfig, with_retry

__all__ = [
    # Client
    "OfSpectrum",
    "AsyncOfSpectrum",
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
    # Models
    "Token",
    "TokenCreateParams",
    "TokenUpdateParams",
    "Notebook",
    "NotebookMedia",
    "NotebookCreateParams",
    "EncodeResult",
    "DecodeResult",
    "Quota",
    "QuotaList",
    # Utils
    "RetryConfig",
    "with_retry",
]
