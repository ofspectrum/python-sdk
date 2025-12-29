"""
Tokens resource for managing watermark tokens
"""

from typing import List, Optional
from .base import BaseResource
from ..models.token import Token, TokenCreateParams, TokenUpdateParams
from ..exceptions import raise_for_error


class TokensResource(BaseResource):
    """Resource for managing watermark tokens"""

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

        # Backend returns a direct list
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

        # Backend returns a list with single token
        if isinstance(data, list) and len(data) > 0:
            return Token.from_dict(data[0])
        return Token.from_dict(data.get("data", {}) if isinstance(data, dict) else {})

    def create(
        self,
        name: str,
        token_type: str = "standard",
        public_key: Optional[int] = None,
        enterprise_verification: bool = False,
    ) -> Token:
        """
        Create a new watermark token.

        Args:
            name: Token name (for identification)
            token_type: "standard" (default), "creator", or "enterprise"
            public_key: Public key for watermark verification.
                        Defaults to 258 for creator/enterprise types.
                        Auto-generated for standard type if not provided.
            enterprise_verification: Whether to enable enterprise verification

        Returns:
            Newly created Token object

        Example:
            # Simple creation (recommended)
            token = client.tokens.create(name="My Token")

            # Creator type (uses default public_key=258)
            token = client.tokens.create(
                name="Creator Token",
                token_type="creator"
            )

            # Custom public_key
            token = client.tokens.create(
                name="Enterprise Token",
                token_type="enterprise",
                public_key=12345
            )
        """
        # Set default public_key for creator/enterprise types
        if token_type in ("creator", "enterprise") and public_key is None:
            public_key = 258  # Default public key, matches web interface
        params = TokenCreateParams(
            name=name,
            token_type=token_type,
            public_key=public_key,
            enterprise_verification=enterprise_verification,
        )

        response = self._post("/tokens/", json=params.to_dict())
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns the token directly
        if isinstance(data, dict) and "id" in data:
            return Token.from_dict(data)
        return Token.from_dict(data.get("data", {}))

    def update(
        self,
        token_id: str,
        name: Optional[str] = None,
        public_key: Optional[int] = None,
        enterprise_verification: Optional[bool] = None,
    ) -> Token:
        """
        Update an existing token.

        Args:
            token_id: The token UUID
            name: New name (optional)
            public_key: New public key (optional)
            enterprise_verification: New enterprise verification setting (optional)

        Returns:
            Updated Token object
        """
        params = TokenUpdateParams(
            name=name,
            public_key=public_key,
            enterprise_verification=enterprise_verification,
        )

        update_data = params.to_dict()
        if not update_data:
            # Nothing to update, just return current token
            return self.get(token_id)

        response = self._patch(f"/tokens/{token_id}", json=update_data)
        data = response.json()
        raise_for_error(data, response.status_code)

        # Backend returns the token directly
        if isinstance(data, dict) and "id" in data:
            return Token.from_dict(data)
        return Token.from_dict(data.get("data", {}))

    # Note: Token deletion is not available via API. Tokens are consumable resources.
