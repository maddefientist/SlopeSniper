"""
Token Deployment Tools.

High-level functions for deploying tokens via NLP commands.
Supports Pump.fun (via PumpPortal) and Bags.fm launchpads.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .config import (
    get_bags_api_key,
    get_bags_partner_key,
    get_keypair,
    get_pumpportal_api_key,
    get_deploy_config_status,
    get_wallet_address,
    set_pumpportal_api_key,
)


@dataclass
class DeployConfig:
    """Configuration for token deployment."""
    name: str
    symbol: str
    description: str
    image_path: str | None = None
    image_url: str | None = None
    image_base64: str | None = None
    dev_buy_sol: float = 0.0
    twitter: str | None = None
    telegram: str | None = None
    website: str | None = None
    platform: Literal["pump", "bags", "auto"] = "auto"


async def deploy_token(
    name: str,
    symbol: str,
    description: str,
    image_path: str | None = None,
    image_url: str | None = None,
    image_base64: str | None = None,
    dev_buy_sol: float = 0.0,
    twitter: str | None = None,
    telegram: str | None = None,
    website: str | None = None,
    platform: Literal["pump", "bags", "auto"] = "auto",
) -> dict:
    """
    Deploy a new token on Solana.

    This is the main entry point for token deployment via NLP.
    Automatically selects platform based on configuration.

    Args:
        name: Token name (max 32 chars)
        symbol: Token symbol/ticker (max 10 chars, auto-uppercased)
        description: Token description
        image_path: Local path to token image
        image_url: URL to token image (alternative to image_path)
        image_base64: Base64 encoded image data (alternative)
        dev_buy_sol: Initial developer buy in SOL (default 0)
        twitter: Optional Twitter URL
        telegram: Optional Telegram URL
        website: Optional website URL
        platform: "pump" (Pump.fun), "bags" (Bags.fm), or "auto"

    Returns:
        Dict with deployment result:
        - success: bool
        - mint: Token mint address (if successful)
        - signature: Transaction signature
        - platform: Platform used
        - urls: Explorer and platform URLs
        - error: Error message (if failed)
    """
    # Validate inputs
    if not name or len(name) > 32:
        return {"success": False, "error": "Name required (max 32 characters)"}

    if not symbol or len(symbol) > 10:
        return {"success": False, "error": "Symbol required (max 10 characters)"}

    if not description:
        return {"success": False, "error": "Description required"}

    if not image_path and not image_url and not image_base64:
        return {"success": False, "error": "Image required (path, URL, or base64)"}

    # Check image path exists if provided
    if image_path and not Path(image_path).exists():
        return {"success": False, "error": f"Image file not found: {image_path}"}

    # Auto-select platform
    if platform == "auto":
        pump_key = get_pumpportal_api_key()
        bags_key = get_bags_api_key()

        if pump_key:
            platform = "pump"
        elif bags_key:
            platform = "bags"
        else:
            # Try to auto-generate PumpPortal key
            platform = "pump"

    # Deploy based on platform
    if platform == "pump":
        return await _deploy_on_pump(
            name=name,
            symbol=symbol,
            description=description,
            image_path=image_path,
            image_url=image_url,
            image_base64=image_base64,
            dev_buy_sol=dev_buy_sol,
            twitter=twitter,
            telegram=telegram,
            website=website,
        )
    elif platform == "bags":
        return await _deploy_on_bags(
            name=name,
            symbol=symbol,
            description=description,
            image_path=image_path,
            image_url=image_url,
            image_base64=image_base64,
            dev_buy_sol=dev_buy_sol,
            twitter=twitter,
            telegram=telegram,
            website=website,
        )
    else:
        return {"success": False, "error": f"Unknown platform: {platform}"}


async def _deploy_on_pump(
    name: str,
    symbol: str,
    description: str,
    image_path: str | None = None,
    image_url: str | None = None,
    image_base64: str | None = None,
    dev_buy_sol: float = 0.0,
    twitter: str | None = None,
    telegram: str | None = None,
    website: str | None = None,
) -> dict:
    """Deploy token on Pump.fun via PumpPortal."""
    from ..sdk.pumpportal_deploy import PumpPortalDeployClient, TokenMetadata

    client = PumpPortalDeployClient()

    # Ensure setup (auto-generates API key if needed)
    setup_result = await client.ensure_setup()

    if setup_result.get("status") == "created":
        # New wallet created - include funding reminder
        funding_info = {
            "new_wallet_created": True,
            "linked_wallet": setup_result.get("linked_wallet"),
            "linked_private_key": setup_result.get("linked_private_key"),
            "funding_required": "Fund linked wallet with 0.02+ SOL for data API access",
        }
    else:
        funding_info = None

    # Create metadata
    metadata = TokenMetadata(
        name=name,
        symbol=symbol.upper(),
        description=description,
        image_path=image_path,
        image_url=image_url,
        image_base64=image_base64,
        twitter=twitter,
        telegram=telegram,
        website=website,
    )

    # Deploy
    result = await client.deploy_token(
        metadata=metadata,
        dev_buy_sol=dev_buy_sol,
    )

    response = {
        "success": result.success,
        "platform": "pump.fun",
        "platform_display": "Pump.fun",
    }

    if result.success:
        response.update({
            "mint": result.mint,
            "signature": result.signature,
            "urls": {
                "explorer": result.explorer_url,
                "platform": result.pump_url,
            },
            "token_info": {
                "name": name,
                "symbol": symbol.upper(),
                "dev_buy_sol": dev_buy_sol,
            },
        })
    else:
        response["error"] = result.error

    if funding_info:
        response["setup_info"] = funding_info

    return response


async def _deploy_on_bags(
    name: str,
    symbol: str,
    description: str,
    image_path: str | None = None,
    image_url: str | None = None,
    image_base64: str | None = None,
    dev_buy_sol: float = 0.0,
    twitter: str | None = None,
    telegram: str | None = None,
    website: str | None = None,
) -> dict:
    """Deploy token on Bags.fm."""
    from ..sdk.bags_client import BagsClient, BagsTokenMetadata

    # Check for API key
    api_key = get_bags_api_key()
    if not api_key:
        return {
            "success": False,
            "error": "Bags.fm API key not configured",
            "hint": "Get an API key at dev.bags.fm and run: slopesniper config --set-bags-key YOUR_KEY",
        }

    # Check for wallet
    keypair = get_keypair()
    if not keypair:
        return {
            "success": False,
            "error": "No wallet configured",
            "hint": "Run: slopesniper setup",
        }

    client = BagsClient()

    # Create metadata
    metadata = BagsTokenMetadata(
        name=name,
        symbol=symbol.upper(),
        description=description,
        image_path=image_path,
        image_url=image_url,
        image_base64=image_base64,
        twitter=twitter,
        telegram=telegram,
        website=website,
    )

    # Deploy
    result = await client.deploy_token(
        metadata=metadata,
        wallet_keypair=keypair,
        initial_buy_sol=dev_buy_sol,
    )

    response = {
        "success": result.success,
        "platform": "bags.fm",
        "platform_display": "Bags.fm",
    }

    if result.success:
        response.update({
            "mint": result.mint,
            "signature": result.signature,
            "urls": {
                "explorer": result.explorer_url,
                "platform": result.bags_url,
                "metadata": result.metadata_url,
            },
            "token_info": {
                "name": name,
                "symbol": symbol.upper(),
                "dev_buy_sol": dev_buy_sol,
            },
        })
    else:
        response["error"] = result.error

    return response


async def setup_pumpportal() -> dict:
    """
    Setup PumpPortal API key (auto-generates wallet and key).

    Returns:
        Dict with setup status and wallet info
    """
    from ..sdk.pumpportal_deploy import PumpPortalDeployClient

    client = PumpPortalDeployClient()
    result = await client.ensure_setup(save_to_config=True)

    if result.get("status") == "created":
        return {
            "success": True,
            "message": "PumpPortal wallet and API key created",
            "linked_wallet": result.get("linked_wallet"),
            "linked_private_key": result.get("linked_private_key"),
            "api_key_preview": result.get("api_key_preview"),
            "important": [
                "SAVE YOUR LINKED WALLET PRIVATE KEY!",
                "Fund linked wallet with 0.02+ SOL for data API access",
                "API key has been saved to SlopeSniper config",
            ],
        }
    else:
        return {
            "success": True,
            "message": "PumpPortal already configured",
            "api_key_preview": result.get("api_key_preview"),
        }


def get_deploy_status() -> dict:
    """
    Get status of token deployment configuration.

    Returns:
        Dict with deployment readiness status
    """
    config_status = get_deploy_config_status()
    wallet_address = get_wallet_address()

    return {
        "wallet_configured": bool(wallet_address),
        "wallet_address": wallet_address,
        "platforms": {
            "pump_fun": {
                "ready": config_status["pumpportal"]["configured"],
                "api_key_preview": config_status["pumpportal"]["key_preview"],
                "linked_wallet": config_status["pumpportal"]["linked_wallet"],
                "note": "Auto-setup available if not configured",
            },
            "bags_fm": {
                "ready": config_status["bags_fm"]["configured"],
                "api_key_preview": config_status["bags_fm"]["key_preview"],
                "partner_configured": config_status["bags_fm"]["partner_configured"],
                "note": "Get API key at dev.bags.fm",
            },
        },
        "ready_to_deploy": config_status["ready_to_deploy"] or True,  # Pump auto-setup
        "recommendations": _get_deploy_recommendations(config_status, wallet_address),
    }


def _get_deploy_recommendations(config_status: dict, wallet_address: str | None) -> list[str]:
    """Generate recommendations for deployment setup."""
    recs = []

    if not wallet_address:
        recs.append("Run 'slopesniper setup' to create a wallet")

    if not config_status["pumpportal"]["configured"]:
        recs.append("PumpPortal will auto-setup on first deploy (creates wallet + API key)")

    if not config_status["bags_fm"]["configured"]:
        recs.append("For Bags.fm: Get API key at dev.bags.fm")

    if not recs:
        recs.append("Ready to deploy tokens!")

    return recs


# CLI-friendly wrapper functions

def deploy_token_sync(
    name: str,
    symbol: str,
    description: str,
    image_path: str | None = None,
    image_url: str | None = None,
    dev_buy_sol: float = 0.0,
    platform: str = "auto",
    **kwargs,
) -> dict:
    """Synchronous wrapper for deploy_token."""
    return asyncio.run(deploy_token(
        name=name,
        symbol=symbol,
        description=description,
        image_path=image_path,
        image_url=image_url,
        dev_buy_sol=dev_buy_sol,
        platform=platform,
        **kwargs,
    ))


def setup_pumpportal_sync() -> dict:
    """Synchronous wrapper for setup_pumpportal."""
    return asyncio.run(setup_pumpportal())
