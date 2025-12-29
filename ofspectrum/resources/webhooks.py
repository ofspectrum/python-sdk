"""
Webhooks resource for managing webhook configurations
"""

from typing import List, Optional
from dataclasses import dataclass
from .base import BaseResource
from ..exceptions import raise_for_error


@dataclass
class Webhook:
    """Represents a webhook configuration"""

    id: str
    url: str
    events: List[str]
    is_active: bool
    description: Optional[str] = None
    secret: Optional[str] = None  # Only returned on creation
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_triggered_at: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Webhook":
        return cls(
            id=data["id"],
            url=data["url"],
            events=data.get("events", []),
            is_active=data.get("is_active", True),
            description=data.get("description"),
            secret=data.get("secret"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            last_triggered_at=data.get("last_triggered_at"),
        )


@dataclass
class WebhookTestResult:
    """Result of a webhook test"""

    success: bool
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None


class WebhooksResource(BaseResource):
    """Resource for managing webhooks"""

    # List of supported events
    SUPPORTED_EVENTS = [
        "encode.completed",
        "decode.completed",
        "quota.warning",
        "quota.exceeded",
        "token.created",
        "token.deleted",
    ]

    def list(self) -> List[Webhook]:
        """
        List all webhooks for the current user.

        Returns:
            List of Webhook objects
        """
        response = self._get("/webhooks")
        data = response.json()
        raise_for_error(data, response.status_code)

        webhooks_data = data.get("data", {}).get("webhooks", [])
        return [Webhook.from_dict(w) for w in webhooks_data]

    def get(self, webhook_id: str) -> Webhook:
        """
        Get a specific webhook by ID.

        Args:
            webhook_id: The webhook UUID

        Returns:
            Webhook object
        """
        response = self._get(f"/webhooks/{webhook_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return Webhook.from_dict(data.get("data", {}))

    def create(
        self,
        url: str,
        events: List[str],
        description: Optional[str] = None,
    ) -> Webhook:
        """
        Create a new webhook.

        Args:
            url: HTTPS endpoint URL
            events: List of events to subscribe to
            description: Optional description

        Returns:
            Newly created Webhook with secret (save this!)

        Example:
            webhook = client.webhooks.create(
                url="https://myapp.com/webhook",
                events=["encode.completed", "decode.completed"]
            )
            print(f"Secret: {webhook.secret}")  # Save this!
        """
        response = self._post(
            "/webhooks",
            json={
                "url": url,
                "events": events,
                "description": description,
            },
        )
        data = response.json()
        raise_for_error(data, response.status_code)

        return Webhook.from_dict(data.get("data", {}))

    def update(
        self,
        webhook_id: str,
        url: Optional[str] = None,
        events: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
        description: Optional[str] = None,
    ) -> Webhook:
        """
        Update a webhook.

        Args:
            webhook_id: The webhook UUID
            url: New URL (optional)
            events: New events list (optional)
            is_active: Enable/disable (optional)
            description: New description (optional)

        Returns:
            Updated Webhook object
        """
        update_data = {}
        if url is not None:
            update_data["url"] = url
        if events is not None:
            update_data["events"] = events
        if is_active is not None:
            update_data["is_active"] = is_active
        if description is not None:
            update_data["description"] = description

        response = self._patch(f"/webhooks/{webhook_id}", json=update_data)
        data = response.json()
        raise_for_error(data, response.status_code)

        return Webhook.from_dict(data.get("data", {}))

    def delete(self, webhook_id: str) -> bool:
        """
        Delete a webhook.

        Args:
            webhook_id: The webhook UUID

        Returns:
            True if deleted successfully
        """
        response = self._delete(f"/webhooks/{webhook_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        return True

    def test(self, webhook_id: str) -> WebhookTestResult:
        """
        Send a test event to a webhook.

        Args:
            webhook_id: The webhook UUID

        Returns:
            WebhookTestResult with delivery status
        """
        response = self._post(f"/webhooks/{webhook_id}/test")
        data = response.json()
        raise_for_error(data, response.status_code)

        result_data = data.get("data", {})
        return WebhookTestResult(
            success=result_data.get("success", False),
            status_code=result_data.get("status_code"),
            response_body=result_data.get("response_body"),
            error=result_data.get("error"),
        )

    def rotate_secret(self, webhook_id: str) -> str:
        """
        Rotate the webhook secret.

        Args:
            webhook_id: The webhook UUID

        Returns:
            New secret (save this!)
        """
        response = self._post(f"/webhooks/{webhook_id}/rotate-secret")
        data = response.json()
        raise_for_error(data, response.status_code)

        return data.get("data", {}).get("secret", "")

    def get_supported_events(self) -> List[dict]:
        """
        Get list of supported webhook events.

        Returns:
            List of event definitions with name and description
        """
        response = self._get("/webhooks/events/supported")
        data = response.json()
        raise_for_error(data, response.status_code)

        return data.get("data", {}).get("events", [])
