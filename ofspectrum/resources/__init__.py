"""
OfSpectrum SDK API Resources
"""

from .tokens import TokensResource
from .notebooks import NotebooksResource
from .audio import AudioResource
from .quotas import QuotasResource
# from .webhooks import WebhooksResource  # Not yet available

__all__ = [
    "TokensResource",
    "NotebooksResource",
    "AudioResource",
    "QuotasResource",
    # "WebhooksResource",  # Not yet available
]
