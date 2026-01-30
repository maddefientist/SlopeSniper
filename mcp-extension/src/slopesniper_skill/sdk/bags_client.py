"""
Bags.fm Token Deployment Client.

Provides token creation on Bags.fm launchpad:
- Create token info and metadata (IPFS upload)
- Create and submit launch transactions
- Fee sharing configuration

API Docs: https://docs.bags.fm/
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from .utils import Utils


@dataclass
class BagsTokenMetadata:
    """Token metadata for Bags.fm launch."""
    name: str  # Max 32 chars
    symbol: str  # Max 10 chars, auto-uppercased
    description: str  # Max 1000 chars
    image_path: str | None = None
    image_url: str | None = None
    image_base64: str | None = None
    twitter: str | None = None
    telegram: str | None = None
    website: str | None = None


@dataclass
class BagsDeployResult:
    """Result of Bags.fm token deployment."""
    success: bool
    mint: str | None = None
    signature: str | None = None
    error: str | None = None
    explorer_url: str | None = None
    bags_url: str | None = None
    metadata_url: str | None = None


class BagsClient:
    """
    Client for deploying tokens on Bags.fm launchpad.

    Bags.fm provides a Solana launchpad with built-in fee sharing
    and creator monetization features.

    Usage:
        client = BagsClient()

        # Deploy token
        result = await client.deploy_token(
            metadata=BagsTokenMetadata(
                name="My Token",
                symbol="MYTKN",
                description="A cool token",
                image_path="/path/to/image.png"
            ),
            initial_buy_sol=1.0,
            wallet_keypair=my_keypair
        )
    """

    BASE_URL = "https://public-api-v2.bags.fm/api/v1"

    def __init__(
        self,
        api_key: str | None = None,
        partner_key: str | None = None,
    ) -> None:
        """
        Initialize Bags.fm client.

        Args:
            api_key: Bags.fm API key (from dev.bags.fm)
            partner_key: Optional partner key for fee sharing
        """
        self.logger = Utils.setup_logger("BagsClient")
        self._api_key = api_key
        self._partner_key = partner_key

    def _get_version(self) -> str:
        """Get package version for user agent."""
        try:
            from .. import __version__
            return __version__
        except Exception:
            return "unknown"

    @property
    def api_key(self) -> str | None:
        """Get API key from instance, config, or environment."""
        if self._api_key:
            return self._api_key

        env_key = os.environ.get("BAGS_API_KEY")
        if env_key:
            return env_key

        try:
            from ..tools.config import get_bags_api_key
            return get_bags_api_key()
        except Exception:
            return None

    @property
    def partner_key(self) -> str | None:
        """Get partner key from instance, config, or environment."""
        if self._partner_key:
            return self._partner_key

        env_key = os.environ.get("BAGS_PARTNER_KEY")
        if env_key:
            return env_key

        try:
            from ..tools.config import get_bags_partner_key
            return get_bags_partner_key()
        except Exception:
            return None

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        if not self.api_key:
            raise ValueError("Bags.fm API key not configured")

        return {
            "x-api-key": self.api_key,
            "User-Agent": f"SlopeSniper/{self._get_version()}",
        }

    async def create_token_info(
        self,
        metadata: BagsTokenMetadata,
    ) -> dict:
        """
        Create token info and upload metadata to IPFS.

        This step prepares the token metadata and returns
        the token mint address and IPFS URL.

        Args:
            metadata: Token metadata including image

        Returns:
            Dict with tokenMint, tokenMetadata (IPFS URL), tokenLaunch info
        """
        self.logger.info(f"[create_token_info] Creating token info for {metadata.symbol}...")

        # Build multipart form data
        form_data = {
            "name": metadata.name[:32],  # Max 32 chars
            "symbol": metadata.symbol[:10].upper(),  # Max 10 chars, uppercase
            "description": metadata.description[:1000],  # Max 1000 chars
        }

        if metadata.twitter:
            form_data["twitter"] = metadata.twitter
        if metadata.telegram:
            form_data["telegram"] = metadata.telegram
        if metadata.website:
            form_data["website"] = metadata.website

        # Prepare files
        files = {}

        if metadata.image_path:
            image_path = Path(metadata.image_path)
            if not image_path.exists():
                raise ValueError(f"Image file not found: {metadata.image_path}")

            suffix = image_path.suffix.lower()
            content_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            content_type = content_types.get(suffix, "image/png")
            files["image"] = (image_path.name, image_path.read_bytes(), content_type)

        elif metadata.image_base64:
            image_data = base64.b64decode(metadata.image_base64)
            files["image"] = ("image.png", image_data, "image/png")

        elif metadata.image_url:
            # Use imageUrl parameter instead of file upload
            form_data["imageUrl"] = metadata.image_url

        else:
            raise ValueError("Must provide image_path, image_url, or image_base64")

        # Make request
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/token-launch/create-token-info",
                data=form_data,
                files=files if files else None,
                headers=self._get_headers(),
                timeout=60.0
            )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"error": response.text}
                self.logger.error(f"[create_token_info] Failed: {error_data}")
                raise ValueError(f"Failed to create token info: {error_data.get('error', response.text)}")

            data = response.json()

            if not data.get("success"):
                raise ValueError(f"API returned error: {data.get('error', 'Unknown error')}")

            result = data.get("response", {})
            self.logger.info(f"[create_token_info] Created token: {result.get('tokenMint', 'unknown')[:8]}...")

            return result

    async def create_launch_transaction(
        self,
        token_mint: str,
        ipfs_url: str,
        wallet_address: str,
        initial_buy_lamports: int,
        config_key: str | None = None,
        tip_wallet: str | None = None,
        tip_lamports: int | None = None,
    ) -> bytes:
        """
        Create the token launch transaction.

        Args:
            token_mint: Token mint public key (from create_token_info)
            ipfs_url: IPFS metadata URL (from create_token_info)
            wallet_address: Creator wallet public key
            initial_buy_lamports: Initial buy amount in lamports (1 SOL = 1e9)
            config_key: Fee share config key (uses partner key if not provided)
            tip_wallet: Optional tip recipient wallet
            tip_lamports: Optional tip amount in lamports

        Returns:
            Base58 encoded serialized transaction (ready to sign and submit)
        """
        self.logger.info(f"[create_launch_transaction] Creating launch tx for {token_mint[:8]}...")

        # Use partner key as config key if not specified
        if not config_key:
            config_key = self.partner_key
            if not config_key:
                raise ValueError("No config_key or partner_key available for launch")

        payload = {
            "ipfs": ipfs_url,
            "tokenMint": token_mint,
            "wallet": wallet_address,
            "initialBuyLamports": initial_buy_lamports,
            "configKey": config_key,
        }

        if tip_wallet:
            payload["tipWallet"] = tip_wallet
        if tip_lamports:
            payload["tipLamports"] = tip_lamports

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.BASE_URL}/token-launch/create-launch-transaction",
                json=payload,
                headers={
                    **self._get_headers(),
                    "Content-Type": "application/json",
                },
                timeout=60.0
            )

            if response.status_code != 200:
                error_data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"error": response.text}
                self.logger.error(f"[create_launch_transaction] Failed: {error_data}")
                raise ValueError(f"Failed to create launch transaction: {error_data.get('error', response.text)}")

            data = response.json()

            if not data.get("success"):
                raise ValueError(f"API returned error: {data.get('error', 'Unknown error')}")

            # Response is Base58 encoded serialized transaction
            tx_base58 = data.get("response")
            if not tx_base58:
                raise ValueError("No transaction in response")

            self.logger.info("[create_launch_transaction] Transaction created successfully")

            # Return raw bytes for signing
            import base58
            return base58.b58decode(tx_base58)

    async def deploy_token(
        self,
        metadata: BagsTokenMetadata,
        wallet_keypair: Keypair,
        initial_buy_sol: float = 0.0,
        rpc_url: str | None = None,
    ) -> BagsDeployResult:
        """
        Deploy a new token on Bags.fm.

        Complete workflow:
        1. Create token info (uploads to IPFS)
        2. Create launch transaction
        3. Sign and submit transaction

        Args:
            metadata: Token metadata (name, symbol, description, image)
            wallet_keypair: Creator wallet keypair for signing
            initial_buy_sol: Initial dev buy in SOL (0 for no dev buy)
            rpc_url: Optional RPC URL for submission

        Returns:
            BagsDeployResult with mint address and signature
        """
        if not self.api_key:
            return BagsDeployResult(
                success=False,
                error="Bags.fm API key not configured. Get one at dev.bags.fm"
            )

        self.logger.info(f"[deploy_token] Deploying {metadata.symbol} with {initial_buy_sol} SOL initial buy...")

        try:
            # Step 1: Create token info
            token_info = await self.create_token_info(metadata)
            token_mint = token_info.get("tokenMint")
            metadata_url = token_info.get("tokenMetadata")

            if not token_mint or not metadata_url:
                return BagsDeployResult(
                    success=False,
                    error=f"Invalid token info response: {token_info}"
                )

            # Step 2: Create launch transaction
            initial_buy_lamports = int(initial_buy_sol * 1_000_000_000)
            tx_bytes = await self.create_launch_transaction(
                token_mint=token_mint,
                ipfs_url=metadata_url,
                wallet_address=str(wallet_keypair.pubkey()),
                initial_buy_lamports=initial_buy_lamports,
            )

            # Step 3: Sign and submit
            if not rpc_url:
                try:
                    from ..tools.config import get_rpc_url
                    rpc_url = get_rpc_url()
                except Exception:
                    rpc_url = "https://api.mainnet-beta.solana.com"

            # Deserialize transaction
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Sign with wallet
            tx.sign([wallet_keypair])

            # Submit using Utils helper (avoids solana package dependency)
            signature = await Utils.send_transaction(tx, rpc_url)
            self.logger.info(f"[deploy_token] Success! Mint: {token_mint}")

            return BagsDeployResult(
                success=True,
                mint=token_mint,
                signature=signature,
                explorer_url=f"https://solscan.io/tx/{signature}",
                bags_url=f"https://bags.fm/token/{token_mint}",
                metadata_url=metadata_url,
            )

        except Exception as e:
            self.logger.error(f"[deploy_token] Error: {e}")
            return BagsDeployResult(
                success=False,
                error=str(e)
            )

    async def get_token_info(self, mint: str) -> dict | None:
        """
        Get info about a token launched on Bags.fm.

        Args:
            mint: Token mint address

        Returns:
            Token info dict or None if not found
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.BASE_URL}/token/{mint}",
                    headers=self._get_headers(),
                    timeout=30.0
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        return data.get("response")
                return None

        except Exception as e:
            self.logger.warning(f"[get_token_info] Error: {e}")
            return None


# Convenience alias
BagsDeployClient = BagsClient
