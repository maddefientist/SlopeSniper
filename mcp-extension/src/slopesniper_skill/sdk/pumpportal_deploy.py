"""
PumpPortal Token Deployment Client.

Provides token creation on Pump.fun via PumpPortal API:
- Auto-generate API key and linked wallet
- Upload metadata to IPFS
- Create tokens with initial dev buy
- Support for Lightning and Local transaction modes

API Docs: https://pumpportal.fun/creation/
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from solders.keypair import Keypair

from .utils import Utils


@dataclass
class TokenMetadata:
    """Token metadata for creation."""
    name: str
    symbol: str
    description: str
    image_path: str | None = None
    image_url: str | None = None
    image_base64: str | None = None
    twitter: str | None = None
    telegram: str | None = None
    website: str | None = None
    show_name: bool = True


@dataclass
class DeployResult:
    """Result of token deployment."""
    success: bool
    mint: str | None = None
    signature: str | None = None
    error: str | None = None
    explorer_url: str | None = None
    pump_url: str | None = None


class PumpPortalDeployClient:
    """
    Client for deploying tokens on Pump.fun via PumpPortal.

    Supports two modes:
    1. Lightning API (recommended): Server signs transactions
    2. Local API: Client-side signing with user's keypair

    Usage:
        client = PumpPortalDeployClient()

        # Auto-setup (creates wallet and API key if needed)
        await client.ensure_setup()

        # Deploy token
        result = await client.deploy_token(
            metadata=TokenMetadata(
                name="My Token",
                symbol="MYTKN",
                description="A cool token",
                image_path="/path/to/image.png"
            ),
            dev_buy_sol=1.0
        )
    """

    BASE_URL = "https://pumpportal.fun"
    IPFS_URL = "https://pump.fun/api/ipfs"
    CREATE_WALLET_URL = f"{BASE_URL}/api/create-wallet"
    TRADE_URL = f"{BASE_URL}/api/trade"
    TRADE_LOCAL_URL = f"{BASE_URL}/api/trade-local"

    def __init__(self, api_key: str | None = None) -> None:
        """
        Initialize PumpPortal deploy client.

        Args:
            api_key: Optional API key. If not provided, will try to load
                     from config or auto-generate.
        """
        self.logger = Utils.setup_logger("PumpPortalDeploy")
        self._api_key = api_key
        self._linked_wallet: str | None = None
        self._linked_private_key: str | None = None

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

        # Try environment
        env_key = os.environ.get("PUMPPORTAL_API_KEY")
        if env_key:
            return env_key

        # Try config
        try:
            from ..tools.config import get_pumpportal_api_key
            return get_pumpportal_api_key()
        except Exception:
            return None

    async def create_wallet_and_key(self) -> dict:
        """
        Create a new wallet and API key via PumpPortal.

        This generates a new wallet that is linked to a PumpPortal API key.
        The linked wallet must be funded with 0.02+ SOL for data API access.

        Returns:
            Dict with:
            - api_key: The new API key
            - wallet_public_key: Public key of linked wallet
            - wallet_private_key: Private key of linked wallet (SAVE THIS!)
        """
        self.logger.info("[create_wallet_and_key] Generating new wallet and API key...")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.CREATE_WALLET_URL,
                headers={"User-Agent": f"SlopeSniper/{self._get_version()}"},
                timeout=30.0
            )

            if response.status_code != 200:
                self.logger.error(f"[create_wallet_and_key] Failed: {response.status_code}")
                raise ValueError(f"Failed to create wallet: {response.text}")

            data = response.json()

            self.logger.info(f"[create_wallet_and_key] Created wallet: {data.get('walletPublicKey', 'unknown')[:8]}...")

            return {
                "api_key": data.get("apiKey"),
                "wallet_public_key": data.get("walletPublicKey"),
                "wallet_private_key": data.get("walletPrivateKey"),
            }

    async def ensure_setup(self, save_to_config: bool = True) -> dict:
        """
        Ensure PumpPortal is configured with API key.

        If no API key exists, creates a new wallet and key.

        Args:
            save_to_config: Whether to save new key to SlopeSniper config

        Returns:
            Dict with setup status
        """
        if self.api_key:
            self.logger.debug("[ensure_setup] API key already configured")
            return {
                "status": "ready",
                "api_key_configured": True,
                "api_key_preview": f"{self.api_key[:8]}...",
            }

        # Create new wallet and key
        self.logger.info("[ensure_setup] No API key found, creating new wallet...")
        wallet_data = await self.create_wallet_and_key()

        self._api_key = wallet_data["api_key"]
        self._linked_wallet = wallet_data["wallet_public_key"]
        self._linked_private_key = wallet_data["wallet_private_key"]

        # Save to config if requested
        if save_to_config:
            try:
                from ..tools.config import set_pumpportal_api_key
                set_pumpportal_api_key(
                    api_key=self._api_key,
                    linked_wallet=self._linked_wallet
                )
                self.logger.info("[ensure_setup] API key saved to config")
            except Exception as e:
                self.logger.warning(f"[ensure_setup] Could not save to config: {e}")

        return {
            "status": "created",
            "api_key_configured": True,
            "api_key_preview": f"{self._api_key[:8]}...",
            "linked_wallet": self._linked_wallet,
            "linked_private_key": self._linked_private_key,
            "important": "Fund linked wallet with 0.02+ SOL for full API access!",
        }

    async def upload_metadata(self, metadata: TokenMetadata) -> str:
        """
        Upload token metadata and image to IPFS via Pump.fun.

        Args:
            metadata: Token metadata including image

        Returns:
            IPFS metadata URI
        """
        self.logger.info(f"[upload_metadata] Uploading metadata for {metadata.symbol}...")

        # Prepare form data
        form_data = {
            "name": metadata.name,
            "symbol": metadata.symbol,
            "description": metadata.description,
            "showName": "true" if metadata.show_name else "false",
        }

        if metadata.twitter:
            form_data["twitter"] = metadata.twitter
        if metadata.telegram:
            form_data["telegram"] = metadata.telegram
        if metadata.website:
            form_data["website"] = metadata.website

        # Prepare image
        files = {}
        if metadata.image_path:
            image_path = Path(metadata.image_path)
            if not image_path.exists():
                raise ValueError(f"Image file not found: {metadata.image_path}")

            # Determine content type
            suffix = image_path.suffix.lower()
            content_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            content_type = content_types.get(suffix, "image/png")

            files["file"] = (image_path.name, image_path.read_bytes(), content_type)

        elif metadata.image_base64:
            # Decode base64 image
            image_data = base64.b64decode(metadata.image_base64)
            files["file"] = ("image.png", image_data, "image/png")

        elif metadata.image_url:
            # Download image from URL first
            async with httpx.AsyncClient() as client:
                img_response = await client.get(metadata.image_url, timeout=30.0)
                if img_response.status_code != 200:
                    raise ValueError(f"Failed to download image: {metadata.image_url}")
                files["file"] = ("image.png", img_response.content, "image/png")
        else:
            raise ValueError("Must provide image_path, image_url, or image_base64")

        # Upload to IPFS
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.IPFS_URL,
                data=form_data,
                files=files,
                headers={"User-Agent": f"SlopeSniper/{self._get_version()}"},
                timeout=60.0
            )

            if response.status_code != 200:
                self.logger.error(f"[upload_metadata] IPFS upload failed: {response.text}")
                raise ValueError(f"IPFS upload failed: {response.text}")

            data = response.json()
            metadata_uri = data.get("metadataUri")

            if not metadata_uri:
                raise ValueError(f"No metadataUri in response: {data}")

            self.logger.info(f"[upload_metadata] Uploaded to IPFS: {metadata_uri}")
            return metadata_uri

    async def deploy_token(
        self,
        metadata: TokenMetadata,
        dev_buy_sol: float = 0.0,
        slippage: int = 10,
        priority_fee: float = 0.0005,
        pool: str = "pump",
    ) -> DeployResult:
        """
        Deploy a new token on Pump.fun using Lightning API.

        This uses PumpPortal's Lightning API which handles transaction
        signing server-side. Faster and simpler than local signing.

        Args:
            metadata: Token metadata (name, symbol, description, image)
            dev_buy_sol: Initial dev buy in SOL (0 for no dev buy)
            slippage: Slippage tolerance in percent (default 10%)
            priority_fee: Priority fee in SOL (default 0.0005)
            pool: "pump" or "bonk"

        Returns:
            DeployResult with mint address and signature
        """
        # Ensure we have API key
        setup = await self.ensure_setup()
        if not self.api_key:
            return DeployResult(
                success=False,
                error="No API key configured. Run ensure_setup() first."
            )

        self.logger.info(f"[deploy_token] Deploying {metadata.symbol} with {dev_buy_sol} SOL dev buy...")

        try:
            # Upload metadata to IPFS
            metadata_uri = await self.upload_metadata(metadata)

            # Generate mint keypair
            mint_keypair = Keypair()

            # Prepare token metadata for API
            token_metadata = {
                "name": metadata.name,
                "symbol": metadata.symbol,
                "uri": metadata_uri,
            }

            # Prepare request
            payload = {
                "action": "create",
                "tokenMetadata": token_metadata,
                "mint": str(mint_keypair),  # Full keypair for Lightning API
                "denominatedInSol": "true",
                "amount": dev_buy_sol,
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": pool,
            }

            # Send to Lightning API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.TRADE_URL}?api-key={self.api_key}",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f"SlopeSniper/{self._get_version()}",
                    },
                    timeout=60.0
                )

                if response.status_code != 200:
                    error_text = response.text
                    self.logger.error(f"[deploy_token] Failed: {error_text}")
                    return DeployResult(
                        success=False,
                        error=f"Deploy failed: {error_text}"
                    )

                data = response.json()
                signature = data.get("signature")
                mint_address = str(mint_keypair.pubkey())

                self.logger.info(f"[deploy_token] Success! Mint: {mint_address}")

                return DeployResult(
                    success=True,
                    mint=mint_address,
                    signature=signature,
                    explorer_url=f"https://solscan.io/tx/{signature}" if signature else None,
                    pump_url=f"https://pump.fun/{mint_address}",
                )

        except Exception as e:
            self.logger.error(f"[deploy_token] Error: {e}")
            return DeployResult(
                success=False,
                error=str(e)
            )

    async def deploy_token_local(
        self,
        metadata: TokenMetadata,
        signer_keypair: Keypair,
        dev_buy_sol: float = 0.0,
        slippage: int = 10,
        priority_fee: float = 0.0005,
        pool: str = "pump",
        rpc_url: str | None = None,
    ) -> DeployResult:
        """
        Deploy a new token using Local API (client-side signing).

        This uses your own keypair for signing, giving you full control.
        Requires manual transaction submission to RPC.

        Args:
            metadata: Token metadata
            signer_keypair: Your Solana keypair for signing
            dev_buy_sol: Initial dev buy in SOL
            slippage: Slippage tolerance in percent
            priority_fee: Priority fee in SOL
            pool: "pump" or "bonk"
            rpc_url: Optional RPC URL for submission

        Returns:
            DeployResult with mint address and signature
        """
        from solders.transaction import VersionedTransaction

        self.logger.info(f"[deploy_token_local] Deploying {metadata.symbol} (local signing)...")

        try:
            # Upload metadata
            metadata_uri = await self.upload_metadata(metadata)

            # Generate mint keypair
            mint_keypair = Keypair()

            # Get RPC URL
            if not rpc_url:
                try:
                    from ..tools.config import get_rpc_url
                    rpc_url = get_rpc_url()
                except Exception:
                    rpc_url = "https://api.mainnet-beta.solana.com"

            # Prepare request for local API
            payload = {
                "publicKey": str(signer_keypair.pubkey()),
                "action": "create",
                "tokenMetadata": {
                    "name": metadata.name,
                    "symbol": metadata.symbol,
                    "uri": metadata_uri,
                },
                "mint": str(mint_keypair.pubkey()),
                "denominatedInSol": "true",
                "amount": dev_buy_sol,
                "slippage": slippage,
                "priorityFee": priority_fee,
                "pool": pool,
            }

            # Get unsigned transaction
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.TRADE_LOCAL_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f"SlopeSniper/{self._get_version()}",
                    },
                    timeout=60.0
                )

                if response.status_code != 200:
                    return DeployResult(
                        success=False,
                        error=f"Failed to get transaction: {response.text}"
                    )

                # Deserialize and sign transaction
                tx_bytes = response.content
                tx = VersionedTransaction.from_bytes(tx_bytes)

                # Sign with both mint and signer keypairs
                tx.sign([mint_keypair, signer_keypair])

                # Submit to RPC using Utils helper (avoids solana package dependency)
                signature = await Utils.send_transaction(tx, rpc_url)
                mint_address = str(mint_keypair.pubkey())

                self.logger.info(f"[deploy_token_local] Success! Mint: {mint_address}")

                return DeployResult(
                    success=True,
                    mint=mint_address,
                    signature=signature,
                    explorer_url=f"https://solscan.io/tx/{signature}",
                    pump_url=f"https://pump.fun/{mint_address}",
                )

        except Exception as e:
            self.logger.error(f"[deploy_token_local] Error: {e}")
            return DeployResult(
                success=False,
                error=str(e)
            )


# Convenience alias
PumpDeployClient = PumpPortalDeployClient
