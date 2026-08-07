"""
Tokens resource for managing watermark tokens
"""

from typing import Any, List, Literal, Optional, overload

from ..exceptions import raise_for_error
from ..models.token import (
    UNSET,
    AiAuthTag,
    OptionalBoolArgument,
    Token,
    TokenCreateParams,
    TokenUpdateParams,
)
from .base import BaseResource


class TokensResource(BaseResource):
    """Resource for managing watermark tokens"""

    def list_ai_auth_tags(self) -> List[AiAuthTag]:
        """List reusable AI authorization tags for the current account."""
        response = self._get("/tokens/ai-auth-tags")
        data = response.json()
        raise_for_error(data, response.status_code)

        tags_data = data if isinstance(data, list) else data.get("data", {}).get("tags", [])
        return [AiAuthTag.from_dict(tag) for tag in tags_data]

    def create_ai_auth_tag(self, tag: str) -> AiAuthTag:
        """Create or retrieve a reusable AI authorization tag."""
        normalized_tag = tag.strip()
        if not normalized_tag:
            raise ValueError("tag must not be empty")

        response = self._post("/tokens/ai-auth-tags", json={"tag": normalized_tag})
        data = response.json()
        raise_for_error(data, response.status_code)

        tag_data = data if isinstance(data, dict) and "id" in data else data.get("data", {})
        return AiAuthTag.from_dict(tag_data)

    def list(self) -> List[Token]:
        """
        List all tokens for the current user.

        Returns:
            List of Token objects

        Example:
            tokens = client.tokens.list()
            for token in tokens:
                print(f"{token.name}: {token.id}")
        """
        response = self._get("/tokens/")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns a direct list
        tokens_data = data if isinstance(data, list) else data.get("data", {}).get("tokens", [])
        return [Token.from_dict(t) for t in tokens_data]

    def get(self, token_id: str) -> Token:
        """
        Get a specific token by ID.

        Args:
            token_id: The token UUID

        Returns:
            Token object

        Raises:
            ResourceNotFoundError: If token not found
        """
        response = self._get(f"/tokens/{token_id}")
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns a list with a single token
        if isinstance(data, list) and len(data) > 0:
            return Token.from_dict(data[0])
        return Token.from_dict(data.get("data", {}) if isinstance(data, dict) else {})

    @overload
    def create(
        self,
        name: str,
        token_type: Literal["pro"],
        public_key: int,
        ai_auth_enabled: bool = False,
        ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None,
        ai_auth_price: Optional[float] = None,
        ai_auth_other_instructions: Optional[str] = None,
        ai_auth_tags: Optional[List[str]] = None,
        version_control_override: OptionalBoolArgument = UNSET,
        storage_auto_expand_override: OptionalBoolArgument = UNSET,
    ) -> Token: ...

    @overload
    def create(
        self,
        name: str,
        token_type: Literal["standard"] = "standard",
        public_key: Optional[int] = None,
        ai_auth_enabled: bool = False,
        ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None,
        ai_auth_price: Optional[float] = None,
        ai_auth_other_instructions: Optional[str] = None,
        ai_auth_tags: Optional[List[str]] = None,
        version_control_override: OptionalBoolArgument = UNSET,
        storage_auto_expand_override: OptionalBoolArgument = UNSET,
    ) -> Token: ...

    def create(
        self,
        name: str,
        token_type: Literal["standard", "pro"] = "standard",
        public_key: Optional[int] = None,
        ai_auth_enabled: bool = False,
        ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None,
        ai_auth_price: Optional[float] = None,
        ai_auth_other_instructions: Optional[str] = None,
        ai_auth_tags: Optional[List[str]] = None,
        version_control_override: OptionalBoolArgument = UNSET,
        storage_auto_expand_override: OptionalBoolArgument = UNSET,
    ) -> Token:
        """
        Create a new watermark token.

        Args:
            name: Token name (for identification)
            token_type: "standard" (default) or "pro"
            public_key: Verification key, required for pro tokens
            ai_auth_enabled: Whether AI authorization is enabled
            ai_auth_access_type: "direct_use" or "premium_track" (optional)
            ai_auth_price: AI authorization price; must be at least 1 when set
            ai_auth_other_instructions: Additional AI authorization instructions
            ai_auth_tags: Searchable AI authorization tags
            version_control_override: True/False to override, None to inherit,
                                      or omit to use the API default
            storage_auto_expand_override: True/False to override, None to inherit,
                                          or omit to use the API default

        Returns:
            Newly created Token object

        Example:
            import os

            # Simple creation (recommended)
            token = client.tokens.create(name="My Token")

            # Pro token with a workflow-specific verification key
            verification_key = int(os.environ["OFSPECTRUM_PUBLIC_KEY"])
            token = client.tokens.create(
                name="Pro Token",
                token_type="pro",
                public_key=verification_key,
            )
        """
        if token_type not in ("standard", "pro"):
            raise ValueError("token_type must be 'standard' or 'pro'")

        params = TokenCreateParams(
            name=name,
            token_type=token_type,
            public_key=public_key,
            ai_auth_enabled=ai_auth_enabled,
            ai_auth_access_type=ai_auth_access_type,
            ai_auth_price=ai_auth_price,
            ai_auth_other_instructions=ai_auth_other_instructions,
            ai_auth_tags=ai_auth_tags,
            version_control_override=version_control_override,
            storage_auto_expand_override=storage_auto_expand_override,
        )

        response = self._post("/tokens/", json=params.to_dict())
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns the token directly
        if isinstance(data, dict) and "id" in data:
            return Token.from_dict(data)
        return Token.from_dict(data.get("data", {}))

    def update(
        self,
        token_id: str,
        name: Optional[str] = None,
        public_key: Optional[int] = None,
        token_type: Optional[Literal["standard", "pro", "enterprise"]] = None,
        enterprise_verification: Optional[bool] = None,
        ai_auth_enabled: Optional[bool] = None,
        ai_auth_access_type: Optional[Literal["direct_use", "premium_track"]] = None,
        ai_auth_price: Any = UNSET,
        ai_auth_other_instructions: Optional[str] = None,
        ai_auth_tags: Optional[List[str]] = None,
        version_control_override: OptionalBoolArgument = UNSET,
        storage_auto_expand_override: OptionalBoolArgument = UNSET,
    ) -> Token:
        """
        Update an existing token.

        Args:
            token_id: The token UUID
            name: New name (optional)
            public_key: New verification key when your token workflow supports it (optional)
            token_type: New token type. The API permits upgrades but rejects downgrades.
            enterprise_verification: Enterprise-only verification setting for eligible accounts (optional)
            ai_auth_enabled: Whether AI authorization is enabled
            ai_auth_access_type: "direct_use" or "premium_track" (optional)
            ai_auth_price: AI authorization price, or None to clear it
            ai_auth_other_instructions: Additional AI authorization instructions
            ai_auth_tags: Replacement list of AI authorization tags
            version_control_override: True/False to override, None to inherit,
                                      or omit to leave unchanged
            storage_auto_expand_override: True/False to override, None to inherit,
                                          or omit to leave unchanged

        Returns:
            Updated Token object
        """
        params = TokenUpdateParams(
            name=name,
            public_key=public_key,
            token_type=token_type,
            enterprise_verification=enterprise_verification,
            ai_auth_enabled=ai_auth_enabled,
            ai_auth_access_type=ai_auth_access_type,
            ai_auth_price=ai_auth_price,
            ai_auth_other_instructions=ai_auth_other_instructions,
            ai_auth_tags=ai_auth_tags,
            version_control_override=version_control_override,
            storage_auto_expand_override=storage_auto_expand_override,
        )

        update_data = params.to_dict()
        if not update_data:
            # Nothing to update, just return current token
            return self.get(token_id)

        response = self._patch(f"/tokens/{token_id}", json=update_data)
        data = response.json()
        raise_for_error(data, response.status_code)

        # API returns the token directly
        if isinstance(data, dict) and "id" in data:
            return Token.from_dict(data)
        return Token.from_dict(data.get("data", {}))

    # Note: Token deletion is not available via API. Tokens are consumable resources.
