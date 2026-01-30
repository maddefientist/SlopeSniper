#!/usr/bin/env python3
"""
SlopeSniper CLI - Simple command interface for Moltbot agents.

Usage:
    slopesniper setup               Create new wallet (interactive, recommended)
    slopesniper setup --import-key KEY   Import existing private key
    slopesniper status              Full status: wallet, holdings, strategy, config
    slopesniper wallet              Show wallet address and all token holdings
    slopesniper export              Export private key for backup/recovery
    slopesniper export --list-backups    List all backed up wallets
    slopesniper export --backup TIMESTAMP    Export a specific backup
    slopesniper pnl                 Show profit/loss for your portfolio
    slopesniper pnl init            Set baseline snapshot (current wallet value)
    slopesniper pnl init --starting-value 100   Set manual baseline
    slopesniper pnl stats           Show trading statistics (win rate, avg gain/loss)
    slopesniper pnl positions       Show detailed position breakdown
    slopesniper pnl export          Export trade history as JSON
    slopesniper pnl export --format csv   Export as CSV
    slopesniper pnl reset           Reset PnL baseline
    slopesniper history [limit]     Show trade history (default: 20 trades)
    slopesniper price <token>       Get token price (symbol or mint)
    slopesniper buy <token> <usd>   Buy tokens
    slopesniper sell <token> <usd>  Sell tokens
    slopesniper check <token>       Safety check (symbol or mint)
    slopesniper search <query>      Search for tokens (returns mint addresses)
    slopesniper resolve <token>     Get mint address from symbol
    slopesniper strategy [name]     View or set strategy
    slopesniper strategy --slippage BPS   Set slippage (e.g., 300 for 3%)
    slopesniper strategy --max-trade USD  Set max trade size
    slopesniper scan [filter]       Scan for opportunities (trending/new/graduated/pumping)
    slopesniper deploy --name "Name" --symbol SYM --desc "..." --image path/url [--dev-buy SOL] [--platform pump|bags]
    slopesniper deploy --status     Show deployment API configuration
    slopesniper deploy --setup-pump Auto-setup PumpPortal (creates wallet + API key)
    slopesniper config              View current configuration
    slopesniper config --set KEY VALUE   Set config (jupiter-key, rpc-provider, rpc-url)
    slopesniper config --clear KEY       Clear config (rpc, jupiter-key)
    slopesniper health              Check system health and wallet sync status
    slopesniper health --diagnose   Run comprehensive wallet integrity diagnostics
    slopesniper restore TIMESTAMP   Restore wallet from backup (see export --list-backups)
    slopesniper contribute          Check for improvements and report to GitHub
    slopesniper contribute --enable       Enable contribution callbacks
    slopesniper contribute --disable      Disable contribution callbacks
    slopesniper update              Update to latest version
    slopesniper version [--check]   Show version (--check for update availability)
    slopesniper uninstall           Clean uninstall (removes CLI and optionally data)

Auto-sell targets:
    slopesniper target add <token> --mcap <value> [--sell all|50%|USD:100]
    slopesniper target add <token> --price <value> [--sell ...]
    slopesniper target add <token> --pct-gain <pct> [--sell ...]
    slopesniper target add <token> --trailing <pct> [--sell ...]
    slopesniper target list [--all]     List active (or all) targets
    slopesniper target remove <id>      Cancel a target
    slopesniper watch <token> --mcap <value> [--sell all] [--interval 5]
    slopesniper daemon start [--interval 15]
    slopesniper daemon stop
    slopesniper daemon status

Global flags:
    --quiet, -q                     Suppress all logging (only JSON to stdout)
    --verbose, -v                   Enable verbose logging for debugging
"""

from __future__ import annotations

import asyncio
import json
import sys


def print_json(data: dict) -> None:
    """Print data as formatted JSON."""
    print(json.dumps(data, indent=2, default=str))


async def cmd_status() -> None:
    """Full status: wallet, holdings, strategy, config, and monitoring."""
    from . import get_status, get_strategy, solana_get_wallet
    from .tools.config import get_config_status
    from .tools.targets import get_active_targets

    # Get all status info
    status = await get_status()
    wallet = await solana_get_wallet() if status.get("wallet_configured") else {}
    strategy = await get_strategy()
    config = get_config_status()

    # Get monitoring info (targets + daemon)
    try:
        active_targets = get_active_targets()
        targets_summary = [
            {
                "id": t.id,
                "symbol": t.symbol or t.mint[:8],
                "type": t.target_type.value,
                "target": t.target_value,
                "sell": t.sell_amount,
            }
            for t in active_targets
        ]
    except Exception:
        targets_summary = []

    # Check daemon status
    try:
        from .daemon import get_daemon_status

        daemon_info = get_daemon_status()
        daemon_running = daemon_info.get("running", False)
    except Exception:
        daemon_running = False

    result = {
        "wallet": {
            "configured": status.get("wallet_configured", False),
            "address": status.get("wallet_address"),
            "sol_balance": wallet.get("sol_balance"),
            "sol_value_usd": wallet.get("sol_value_usd"),
            "tokens": wallet.get("tokens", []),
        },
        "strategy": {
            "name": strategy.get("name"),
            "max_trade_usd": strategy.get("max_trade_usd"),
            "auto_execute_under_usd": strategy.get("auto_execute_under_usd"),
            "slippage_bps": strategy.get("slippage_bps"),
            "require_rugcheck": strategy.get("require_rugcheck"),
        },
        "config": {
            "jupiter_api_key": config.get("jupiter_api_key_status"),
            "rpc": config.get("rpc"),
        },
        "monitoring": {
            "daemon_running": daemon_running,
            "active_targets": len(targets_summary),
            "targets": targets_summary,
        },
        "ready_to_trade": status.get("ready_to_trade", False),
    }
    print_json(result)


def cmd_setup(import_key: str | None = None) -> None:
    """Interactive wallet setup with confirmation."""
    from .tools.config import load_local_wallet
    from .tools.onboarding import create_wallet_explicit, setup_wallet

    # Check if wallet already exists
    existing = load_local_wallet()
    if existing and not import_key:
        print("")
        print("Wallet already configured!")
        print(f"  Address: {existing['address']}")
        print("")
        print("To import a different wallet (current will be backed up):")
        print("  slopesniper setup --import-key YOUR_PRIVATE_KEY")
        print("")
        print("To view/export your current key:")
        print("  slopesniper export")
        print("")
        return

    print("")
    print("=" * 60)
    print("  SlopeSniper Wallet Setup")
    print("=" * 60)
    print("")

    if import_key:
        # Import existing private key
        result = asyncio.run(setup_wallet(private_key=import_key))
        if result.get("success"):
            print("Wallet imported successfully!")
            print(f"  Address: {result['wallet_address']}")
            print("")
            print("Send SOL to this address to start trading.")
        else:
            print(f"Error: {result.get('error')}")
            if result.get("hint"):
                print(f"Hint: {result['hint']}")
        print("")
        return

    # New wallet creation - get user confirmation
    print("This will create a new Solana trading wallet.")
    print("")
    print("IMPORTANT:")
    print("  - You will receive a PRIVATE KEY")
    print("  - Anyone with this key can access your funds")
    print("  - You MUST save it securely - it cannot be recovered")
    print("")

    try:
        confirm = input("Create new wallet? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("")
            print("Setup cancelled.")
            return
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        return

    # Generate wallet
    result = asyncio.run(create_wallet_explicit())

    # Display with emphasis
    print("")
    print("=" * 60)
    print("  WALLET CREATED - SAVE YOUR PRIVATE KEY NOW!")
    print("=" * 60)
    print("")
    print(f"  Address: {result['address']}")
    print("")
    print("  Private Key:")
    print(f"  {result['private_key']}")
    print("")
    print("=" * 60)
    print("")

    # Require confirmation they saved it
    try:
        print("To confirm you saved your key, type your wallet address:")
        user_addr = input("> ").strip()
        if user_addr != result["address"]:
            print("")
            print("WARNING: Address doesn't match!")
            print(f"Your address is: {result['address']}")
            print("Make sure you saved your private key correctly.")
            print("")
            return
    except (EOFError, KeyboardInterrupt):
        print("\nPlease make sure you saved your private key!")
        print("")
        return

    print("")
    print("Setup complete! Send SOL to your address to start trading.")
    print("")
    print("Next steps:")
    print("  slopesniper status   - Check balance")
    print("  slopesniper export   - Backup key anytime")
    print("")


async def cmd_wallet() -> None:
    """Show wallet address and holdings."""
    from . import solana_get_wallet

    result = await solana_get_wallet()
    print_json(result)


async def cmd_export(
    list_backups: bool = False,
    backup_timestamp: str | None = None,
) -> None:
    """Export private key for backup/recovery."""
    if list_backups:
        from .tools.onboarding import list_backup_wallets

        result = await list_backup_wallets()
        print_json(result)
    elif backup_timestamp:
        from .tools.onboarding import export_backup

        result = await export_backup(backup_timestamp)
        print_json(result)
    else:
        from . import export_wallet
        from .tools.config import record_backup_export

        result = await export_wallet(include_backups=True)
        # Record that user exported their wallet (for backup reminder tracking)
        if result.get("success"):
            record_backup_export()
        print_json(result)


async def cmd_pnl(
    subcommand: str | None = None,
    starting_value: float | None = None,
    format_type: str = "json",
) -> None:
    """
    Show portfolio profit/loss with optional subcommands.

    Subcommands:
        (none)      Show current PnL summary
        init        Set baseline snapshot for tracking
        stats       Show trading statistics (win rate, etc.)
        positions   Show detailed position breakdown
        export      Export trade history (--format json|csv)
        reset       Reset PnL baseline
    """
    from .tools.strategies import (
        pnl_export,
        pnl_init,
        pnl_positions,
        pnl_reset,
        pnl_stats,
        pnl_with_baseline,
    )

    if subcommand is None:
        # Default: show PnL with baseline if available
        result = await pnl_with_baseline()
    elif subcommand == "init":
        result = await pnl_init(starting_value=starting_value)
    elif subcommand == "stats":
        result = pnl_stats()
    elif subcommand == "positions":
        result = await pnl_positions()
    elif subcommand == "export":
        result = pnl_export(format_type=format_type)
    elif subcommand == "reset":
        result = pnl_reset()
    else:
        result = {
            "error": f"Unknown pnl subcommand: {subcommand}",
            "available": ["init", "stats", "positions", "export", "reset"],
        }

    print_json(result)


def cmd_history(limit: int = 20) -> None:
    """Show trade history."""
    from . import get_trade_history

    result = get_trade_history(limit=limit)
    print_json({"trades": result, "count": len(result)})


async def cmd_price(token: str) -> None:
    """Get token price."""
    from . import solana_get_price

    result = await solana_get_price(token)
    print_json(result)


async def cmd_buy(token: str, amount_usd: float) -> None:
    """Buy tokens."""
    from . import quick_trade

    result = await quick_trade("buy", token, amount_usd)
    print_json(result)


async def cmd_sell(token: str, amount_usd: float) -> None:
    """Sell tokens."""
    from . import quick_trade

    result = await quick_trade("sell", token, amount_usd)
    print_json(result)


async def cmd_check(token: str) -> None:
    """Run safety check on token."""
    from . import solana_check_token

    result = await solana_check_token(token)
    print_json(result)


async def cmd_search(query: str) -> None:
    """Search for tokens."""
    from . import solana_search_token

    result = await solana_search_token(query)
    print_json(result)


async def cmd_resolve(token: str) -> None:
    """Resolve token symbol to mint address."""
    from . import solana_resolve_token

    result = await solana_resolve_token(token)
    print_json(result)


async def cmd_strategy(
    name: str | None = None,
    slippage_bps: int | None = None,
    max_trade_usd: float | None = None,
) -> None:
    """
    View or set trading strategy.

    Args:
        name: Strategy preset name (conservative/balanced/aggressive/degen)
        slippage_bps: Override slippage tolerance in basis points (100 = 1%)
        max_trade_usd: Override max trade size in USD
    """
    from . import get_strategy, set_strategy

    # If any parameter is set, update strategy
    if name or slippage_bps is not None or max_trade_usd is not None:
        result = await set_strategy(
            strategy=name,
            slippage_bps=slippage_bps,
            max_trade_usd=max_trade_usd,
        )
    else:
        result = await get_strategy()
    print_json(result)


async def cmd_scan(filter_type: str = "all") -> None:
    """Scan for trading opportunities."""
    from . import scan_opportunities

    result = await scan_opportunities(filter_type)
    print_json(result)


async def cmd_deploy(
    name: str,
    symbol: str,
    description: str,
    image: str,
    dev_buy_sol: float = 0.0,
    platform: str = "auto",
    twitter: str | None = None,
    telegram: str | None = None,
    website: str | None = None,
) -> None:
    """Deploy a new token on Pump.fun or Bags.fm."""
    from .tools.deploy import deploy_token
    from pathlib import Path

    # Determine if image is path or URL
    image_path = None
    image_url = None

    if image.startswith("http://") or image.startswith("https://"):
        image_url = image
    else:
        image_path = image
        if not Path(image_path).exists():
            print_json({"success": False, "error": f"Image file not found: {image_path}"})
            return

    result = await deploy_token(
        name=name,
        symbol=symbol,
        description=description,
        image_path=image_path,
        image_url=image_url,
        dev_buy_sol=dev_buy_sol,
        platform=platform,
        twitter=twitter,
        telegram=telegram,
        website=website,
    )
    print_json(result)


def cmd_deploy_status() -> None:
    """Show token deployment configuration status."""
    from .tools.deploy import get_deploy_status

    result = get_deploy_status()
    print_json(result)


async def cmd_setup_pumpportal() -> None:
    """Setup PumpPortal API key (auto-generates wallet)."""
    from .tools.deploy import setup_pumpportal

    result = await setup_pumpportal()
    print_json(result)


def cmd_config(
    set_key: str | None = None,
    set_value: str | None = None,
    clear_key: str | None = None,
) -> None:
    """View or update configuration."""
    from .tools.config import (
        clear_jupiter_api_key,
        clear_rpc_config,
        get_config_status,
        set_jupiter_api_key,
        set_rpc_config,
    )

    if set_key and set_value:
        key_lower = set_key.lower().replace("-", "_").replace(" ", "_")

        if key_lower in ("jupiter_key", "jupiter_api_key", "jup_key", "jup"):
            result = set_jupiter_api_key(set_value)
        elif key_lower in ("rpc_provider", "rpc_type"):
            # For provider, we need a second value - assume custom URL
            result = set_rpc_config(set_value, set_value)
        elif key_lower in ("rpc_url", "rpc", "solana_rpc"):
            result = set_rpc_config("custom", set_value)
        elif key_lower in ("helius", "quicknode", "alchemy"):
            result = set_rpc_config(key_lower, set_value)
        else:
            result = {
                "error": f"Unknown config key: {set_key}",
                "valid_keys": ["jupiter-key", "rpc-url", "helius", "quicknode", "alchemy"],
            }
        print_json(result)

    elif clear_key:
        key_lower = clear_key.lower().replace("-", "_").replace(" ", "_")
        if key_lower in ("rpc", "rpc_url", "rpc_provider"):
            result = clear_rpc_config()
            print_json(result)
        elif key_lower in ("jupiter", "jupiter_key", "jupiter_api_key", "jup", "jup_key"):
            result = clear_jupiter_api_key()
            print_json(result)
        else:
            print_json({"error": f"Cannot clear: {clear_key}", "clearable": ["rpc", "jupiter-key"]})

    else:
        result = get_config_status()
        print_json(result)


def cmd_health(diagnose: bool = False) -> None:
    """
    Check system health and wallet sync status.

    Args:
        diagnose: If True, run comprehensive integrity diagnostics

    Shows:
    - Wallet configuration sources (env vs local)
    - Mismatch warnings if env and local wallets differ
    - Jupiter API key status
    - RPC configuration status
    - Overall system health
    """
    from . import __version__

    from .tools.config import (
        get_config_status,
        get_wallet_integrity_status,
        get_wallet_sync_status,
        load_user_config,
    )

    # Get wallet sync status
    sync_status = get_wallet_sync_status()

    # Get config status
    config = load_user_config() or {}

    result = {
        "version": __version__,
        "health": "ok" if sync_status["is_synced"] else "warning",
        "wallet": {
            "active_source": sync_status["active_source"],
            "active_address": sync_status["active_address"],
            "env_configured": sync_status["env_configured"],
            "env_address": sync_status["env_address"],
            "local_configured": sync_status["local_configured"],
            "local_address": sync_status["local_address"],
            "is_synced": sync_status["is_synced"],
        },
        "jupiter_api_key": {
            "configured": bool(config.get("jupiter_api_key")),
            "source": "local_config" if config.get("jupiter_api_key") else "bundled",
        },
        "rpc": {
            "configured": bool(config.get("rpc_provider")),
            "provider": config.get("rpc_provider", "default"),
        },
    }

    # Add warning if wallet mismatch detected
    if not sync_status["is_synced"]:
        result["WARNING"] = sync_status["warning"]
        result["fix_options"] = [
            "1. To use the LOCAL wallet: unset SOLANA_PRIVATE_KEY environment variable",
            "2. To sync ENV to LOCAL: slopesniper setup --import-key $SOLANA_PRIVATE_KEY",
            "3. To see which wallet is active: check 'active_source' above",
        ]

    # Run comprehensive diagnostics if requested
    if diagnose:
        integrity = get_wallet_integrity_status()
        result["diagnostics"] = integrity

        # Update health based on diagnostics
        if integrity.get("health") == "error":
            result["health"] = "error"
        elif integrity.get("health") == "warning" and result["health"] == "ok":
            result["health"] = "warning"

        if integrity.get("issues"):
            result["issues"] = integrity["issues"]
        if integrity.get("recommendations"):
            result["recommendations"] = integrity["recommendations"]

    print_json(result)


def cmd_restore(timestamp: str) -> None:
    """
    Restore a wallet from backup.

    Args:
        timestamp: Backup timestamp (YYYYMMDD_HHMMSS format)
    """
    from .tools.config import restore_backup_wallet

    result = restore_backup_wallet(timestamp)
    print_json(result)


def cmd_version(check_latest: bool = False) -> None:
    """Show current version and optionally check for updates."""
    from . import __version__

    result = {
        "version": __version__,
        "package": "slopesniper-mcp",
        "repo": "https://github.com/BAGWATCHER/SlopeSniper",
        "changelog": "https://github.com/BAGWATCHER/SlopeSniper/blob/main/CHANGELOG.md",
    }

    if check_latest:
        try:
            import re
            import urllib.request

            # Fetch pyproject.toml from GitHub to get latest version
            url = "https://raw.githubusercontent.com/BAGWATCHER/SlopeSniper/main/mcp-extension/pyproject.toml"
            req = urllib.request.Request(url, headers={"User-Agent": "SlopeSniper"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                content = resp.read().decode()
                match = re.search(r'version\s*=\s*"([^"]+)"', content)
                if match:
                    latest = match.group(1)
                    result["latest_version"] = latest
                    result["update_available"] = latest != __version__
                    if latest != __version__:
                        result["update_command"] = "slopesniper update"
        except Exception:
            result["latest_version"] = "unknown (couldn't check)"

    print_json(result)


def cmd_update() -> None:
    """Update to latest version from GitHub."""
    import re
    import subprocess
    import urllib.request

    from . import __version__

    old_version = __version__

    print("Updating SlopeSniper...")
    print(f"Current version: {old_version}")
    print("")

    success = False
    method = ""

    # Try uv tool first (preferred for CLI tools)
    try:
        result = subprocess.run(
            [
                "uv",
                "tool",
                "install",
                "slopesniper-mcp @ git+https://github.com/BAGWATCHER/SlopeSniper.git#subdirectory=mcp-extension",
                "--force",
                "--refresh",  # Bust git cache
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            success = True
            method = "uv tool"
    except FileNotFoundError:
        pass

    # Fallback to uv pip
    if not success:
        try:
            result = subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--refresh",  # Bust git cache
                    "slopesniper-mcp @ git+https://github.com/BAGWATCHER/SlopeSniper.git#subdirectory=mcp-extension",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                success = True
                method = "uv pip"
        except FileNotFoundError:
            pass

    # Final fallback to pip
    if not success:
        try:
            result = subprocess.run(
                [
                    "pip",
                    "install",
                    "--force-reinstall",
                    "--no-cache-dir",  # Bust pip cache
                    "slopesniper-mcp @ git+https://github.com/BAGWATCHER/SlopeSniper.git#subdirectory=mcp-extension",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                success = True
                method = "pip"
        except FileNotFoundError:
            pass

    if not success:
        print_json(
            {
                "error": "Update failed",
                "suggestion": "Try manually: uv tool install 'slopesniper-mcp @ git+https://github.com/BAGWATCHER/SlopeSniper.git#subdirectory=mcp-extension' --force",
            }
        )
        return

    # Fetch new version from GitHub
    new_version = "unknown"
    changelog_summary = []
    try:
        # Get version
        version_url = "https://raw.githubusercontent.com/BAGWATCHER/SlopeSniper/main/mcp-extension/pyproject.toml"
        req = urllib.request.Request(version_url, headers={"User-Agent": "SlopeSniper"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode()
            match = re.search(r'version\s*=\s*"([^"]+)"', content)
            if match:
                new_version = match.group(1)

        # Get recent changelog
        changelog_url = "https://raw.githubusercontent.com/BAGWATCHER/SlopeSniper/main/CHANGELOG.md"
        req = urllib.request.Request(changelog_url, headers={"User-Agent": "SlopeSniper"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            changelog = resp.read().decode()
            # Extract first version section (after [Unreleased])
            lines = changelog.split("\n")
            in_section = False
            section_count = 0
            for line in lines:
                if line.startswith("## [") and "Unreleased" not in line:
                    if section_count == 0:
                        in_section = True
                        changelog_summary.append(line)
                        section_count += 1
                    else:
                        break
                elif in_section:
                    if line.startswith("## ["):
                        break
                    if line.strip():
                        changelog_summary.append(line)
    except Exception:
        pass

    # Print success message
    print("=" * 50)
    print(f"  Updated successfully via {method}!")
    print("=" * 50)
    print("")
    print(f"  {old_version} → {new_version}")
    print("")

    if changelog_summary:
        print("What's new:")
        print("-" * 50)
        for line in changelog_summary[:15]:  # Limit to 15 lines
            print(line)
        print("-" * 50)
        print("")

    print("Full changelog: https://github.com/BAGWATCHER/SlopeSniper/blob/main/CHANGELOG.md")
    print("")


def cmd_uninstall(keep_data: bool = False, confirm: bool = False) -> None:
    """Clean uninstall SlopeSniper."""
    import shutil
    import subprocess

    from .tools.config import SLOPESNIPER_DIR

    print("")
    print("=" * 50)
    print("  SlopeSniper Uninstall")
    print("=" * 50)
    print("")

    # Check for wallet
    wallet_exists = (SLOPESNIPER_DIR / "wallet.enc").exists()

    if wallet_exists:
        print("WARNING: You have a wallet configured!")
        print("")
        # Try to show the address
        try:
            from .tools.config import load_local_wallet

            wallet = load_local_wallet()
            if wallet:
                print(f"  Wallet address: {wallet['address']}")
                print("")
        except Exception:
            pass

        print("IMPORTANT: Before uninstalling, make sure you have:")
        print("  1. Exported your private key: slopesniper export")
        print("  2. Saved it in a secure location")
        print("  3. Transferred any remaining funds")
        print("")
        print("If you lose your private key, YOUR FUNDS WILL BE LOST FOREVER.")
        print("")

    if not confirm:
        print("To proceed with uninstall, add --confirm flag:")
        print("")
        print("  slopesniper uninstall --confirm            # Remove everything")
        print("  slopesniper uninstall --confirm --keep-data  # Keep wallet/config")
        print("")
        return

    # Double-check if wallet exists and not keeping data
    if wallet_exists and not keep_data:
        print("=" * 50)
        print("  FINAL WARNING: WALLET WILL BE DELETED")
        print("=" * 50)
        print("")
        try:
            response = input("Type 'DELETE MY WALLET' to confirm: ")
            if response.strip() != "DELETE MY WALLET":
                print("")
                print("Uninstall cancelled.")
                return
        except (EOFError, KeyboardInterrupt):
            print("")
            print("Uninstall cancelled.")
            return

    # Remove CLI tool
    print("Removing SlopeSniper CLI...")
    success = False

    # Try uv tool uninstall
    try:
        result = subprocess.run(
            ["uv", "tool", "uninstall", "slopesniper-mcp"], capture_output=True, text=True
        )
        if result.returncode == 0:
            success = True
            print("   Removed via uv tool")
    except FileNotFoundError:
        pass

    # Fallback to pip
    if not success:
        try:
            result = subprocess.run(
                ["pip", "uninstall", "-y", "slopesniper-mcp"], capture_output=True, text=True
            )
            if result.returncode == 0:
                success = True
                print("   Removed via pip")
        except FileNotFoundError:
            pass

    if not success:
        print("   Warning: Could not remove CLI package")

    print("")

    # Handle data directory
    if SLOPESNIPER_DIR.exists():
        if keep_data:
            print(f"Keeping data directory: {SLOPESNIPER_DIR}")
            print("Your wallet and config are preserved.")
        else:
            print(f"Removing data directory: {SLOPESNIPER_DIR}")
            try:
                shutil.rmtree(SLOPESNIPER_DIR)
                print("   Removed successfully")
            except Exception as e:
                print(f"   Error: {e}")

    print("")
    print("=" * 50)
    print("  Uninstall complete!")
    print("=" * 50)
    print("")


def cmd_contribute(
    enable: bool = False,
    disable: bool = False,
) -> None:
    """Manage contribution callbacks and check for improvements."""
    from .integrity import (
        check_and_report,
        disable_contribution_callbacks,
        enable_contribution_callbacks,
    )
    from .tools.config import load_user_config

    if enable:
        # No URL needed - contributions go to GitHub Issues
        result = enable_contribution_callbacks()
        result["method"] = "GitHub Issues"
        result["repo"] = "BAGWATCHER/SlopeSniper"
        print_json(result)
    elif disable:
        result = disable_contribution_callbacks()
        print_json(result)
    else:
        # Run check and report
        result = check_and_report(force=True)

        # Add callback config status
        config = load_user_config() or {}
        result["contribution_method"] = "GitHub Issues"
        result["callbacks_enabled"] = not config.get("contribution_callbacks_disabled", False)

        print_json(result)


# ============================================================================
# Auto-sell Target Commands
# ============================================================================


async def cmd_target_add(
    token: str,
    mcap: float | None = None,
    price: float | None = None,
    pct_gain: float | None = None,
    trailing: float | None = None,
    sell: str = "all",
) -> None:
    """Add a new sell target."""
    from .tools import add_target, resolve_token

    # Determine target type and value
    if mcap is not None:
        target_type = "mcap"
        target_value = mcap
    elif price is not None:
        target_type = "price"
        target_value = price
    elif pct_gain is not None:
        target_type = "pct_gain"
        target_value = pct_gain
    elif trailing is not None:
        target_type = "trailing_stop"
        target_value = trailing
    else:
        print_json(
            {
                "error": "Must specify one of: --mcap, --price, --pct-gain, --trailing",
                "examples": [
                    "slopesniper target add BONK --mcap 500000000 --sell all",
                    "slopesniper target add SOL --price 200 --sell 50%",
                    "slopesniper target add WIF --pct-gain 100 --sell USD:50",
                    "slopesniper target add POPCAT --trailing 20 --sell all",
                ],
            }
        )
        return

    # Resolve token to mint address
    resolved = await resolve_token(token)
    if not resolved.get("mint"):
        print_json({"error": f"Could not resolve token: {token}"})
        return

    mint = resolved["mint"]
    symbol = resolved.get("symbol", token)

    # Get current price/mcap for entry tracking
    entry_price = resolved.get("price_usd")
    entry_mcap = resolved.get("mcap")

    result = await add_target(
        mint=mint,
        target_type=target_type,
        target_value=target_value,
        sell_amount=sell,
        symbol=symbol,
        entry_price=entry_price,
        entry_mcap=entry_mcap,
    )

    print_json(result)


async def cmd_target_list(show_all: bool = False) -> None:
    """List sell targets."""
    from .tools import format_target_for_display, get_active_targets, get_all_targets

    if show_all:
        targets = get_all_targets(include_executed=True)
    else:
        targets = get_active_targets()

    if not targets:
        print_json({"targets": [], "message": "No active targets"})
        return

    formatted = [format_target_for_display(t) for t in targets]
    print_json({"targets": formatted, "count": len(formatted)})


async def cmd_target_remove(target_id: int) -> None:
    """Remove/cancel a target."""
    from .tools import remove_target

    result = remove_target(target_id)
    print_json(result)


async def cmd_watch_foreground(
    token: str,
    mcap: float | None = None,
    price: float | None = None,
    pct_gain: float | None = None,
    trailing: float | None = None,
    sell: str = "all",
    interval: int = 5,
) -> None:
    """
    Foreground watch mode - monitors token until target hit.

    Blocks until target is reached or Ctrl+C is pressed.
    """
    import time

    from .tools import resolve_token
    from .tools.config import get_jupiter_api_key

    # Determine target type and value
    if mcap is not None:
        target_type = "mcap"
        target_value = mcap
        condition = f"mcap >= ${mcap:,.0f}"
    elif price is not None:
        target_type = "price"
        target_value = price
        condition = f"price >= ${price:.8g}"
    elif pct_gain is not None:
        target_type = "pct_gain"
        target_value = pct_gain
        condition = f"+{pct_gain:.1f}% gain"
    elif trailing is not None:
        target_type = "trailing_stop"
        target_value = trailing
        condition = f"-{trailing:.1f}% from peak"
    else:
        print("Error: Must specify one of: --mcap, --price, --pct-gain, --trailing")
        return

    # Resolve token
    resolved = await resolve_token(token)
    if not resolved.get("mint"):
        print(f"Error: Could not resolve token: {token}")
        return

    mint = resolved["mint"]
    symbol = resolved.get("symbol", token)
    entry_price = resolved.get("price_usd", 0)
    entry_mcap = resolved.get("mcap")
    peak_price = entry_price

    print("")
    print("=" * 60)
    print(f"  Watching {symbol} ({mint[:8]}...)")
    print(f"  Target: {condition}")
    print(f"  Sell: {sell}")
    print(f"  Interval: {interval}s")
    print("=" * 60)
    print("")
    print("Press Ctrl+C to cancel")
    print("")

    from ..sdk import JupiterDataClient

    client = JupiterDataClient(api_key=get_jupiter_api_key())

    try:
        while True:
            try:
                # Fetch current price
                prices = await client.get_prices([mint])
                price_data = prices.get(mint, {})
                current_price = price_data.get("usdPrice", 0)

                # Get mcap if needed
                current_mcap = None
                if target_type == "mcap":
                    info = await client.get_token_info(mint)
                    current_mcap = info.get("mcap") if info else None

                # Update peak for trailing stop
                if target_type == "trailing_stop" and current_price > peak_price:
                    peak_price = current_price

                # Check condition
                triggered = False
                if target_type == "mcap" and current_mcap:
                    triggered = current_mcap >= target_value
                    status = f"mcap: ${current_mcap:,.0f} / ${target_value:,.0f}"
                elif target_type == "price":
                    triggered = current_price >= target_value
                    status = f"price: ${current_price:.8g} / ${target_value:.8g}"
                elif target_type == "pct_gain" and entry_price > 0:
                    pct = ((current_price - entry_price) / entry_price) * 100
                    triggered = pct >= target_value
                    status = f"gain: {pct:+.1f}% / {target_value:+.1f}%"
                elif target_type == "trailing_stop" and peak_price > 0:
                    drop = ((peak_price - current_price) / peak_price) * 100
                    triggered = drop >= target_value
                    status = f"drop: {drop:.1f}% / {target_value:.1f}% (peak: ${peak_price:.8g})"
                else:
                    status = f"price: ${current_price:.8g}"

                timestamp = time.strftime("%H:%M:%S")
                print(f"[{timestamp}] {status}")

                if triggered:
                    print("")
                    print("=" * 60)
                    print(f"  TARGET HIT!")
                    print("=" * 60)
                    print("")
                    print(f"Executing sell ({sell})...")

                    from .tools import quick_trade

                    if sell.lower() == "all":
                        result = await quick_trade("sell", mint, "all")
                    else:
                        # Calculate sell amount
                        from .tools import parse_sell_amount, solana_get_wallet

                        wallet = await solana_get_wallet()
                        tokens = wallet.get("tokens", [])
                        holdings = next(
                            (t for t in tokens if t.get("mint") == mint), None
                        )
                        if holdings:
                            token_amt = holdings.get("amount", 0)
                            value_usd = holdings.get("value_usd", 0)
                            sell_tokens = parse_sell_amount(sell, value_usd, token_amt)
                            sell_usd = sell_tokens * current_price
                            result = await quick_trade("sell", mint, sell_usd)
                        else:
                            result = {"error": "Token not found in wallet"}

                    print_json(result)
                    return

            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] Error: {e}")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("")
        print("Watch cancelled.")


def print_help() -> None:
    """Print usage help."""
    print(__doc__)


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    # Check for --quiet flag (suppresses ALL logging)
    quiet = "--quiet" in args or "-q" in args
    if quiet:
        args = [a for a in args if a not in ("--quiet", "-q")]
        import logging

        logging.disable(logging.CRITICAL)
        import warnings

        warnings.filterwarnings("ignore")

    # Check for --verbose flag (enables INFO logging for debugging)
    verbose = "--verbose" in args or "-v" in args
    if verbose:
        args = [a for a in args if a not in ("--verbose", "-v")]
        import os

        os.environ["SLOPESNIPER_LOG_LEVEL"] = "INFO"

    if not args or args[0] in ("-h", "--help", "help"):
        print_help()
        return

    cmd = args[0].lower()

    try:
        if cmd == "setup":
            import_key = None
            if "--import-key" in args:
                idx = args.index("--import-key")
                if idx + 1 < len(args):
                    import_key = args[idx + 1]
            cmd_setup(import_key=import_key)

        elif cmd == "status":
            asyncio.run(cmd_status())

        elif cmd == "wallet":
            asyncio.run(cmd_wallet())

        elif cmd == "export":
            list_backups = "--list-backups" in args or "-l" in args
            backup_timestamp = None
            if "--backup" in args:
                idx = args.index("--backup")
                if idx + 1 < len(args):
                    backup_timestamp = args[idx + 1]
            asyncio.run(cmd_export(list_backups=list_backups, backup_timestamp=backup_timestamp))

        elif cmd == "pnl":
            # Parse pnl subcommands: pnl [init|stats|positions|export|reset]
            subcommand = args[1] if len(args) > 1 and not args[1].startswith("-") else None
            starting_value = None
            format_type = "json"

            # Parse flags
            for i, arg in enumerate(args):
                if arg == "--starting-value" and i + 1 < len(args):
                    try:
                        starting_value = float(args[i + 1])
                    except ValueError:
                        pass
                elif arg == "--format" and i + 1 < len(args):
                    format_type = args[i + 1]

            asyncio.run(cmd_pnl(subcommand, starting_value, format_type))

        elif cmd == "history":
            limit = int(args[1]) if len(args) > 1 else 20
            cmd_history(limit)

        elif cmd == "price":
            if len(args) < 2:
                print("Error: price requires <token>")
                sys.exit(1)
            asyncio.run(cmd_price(args[1]))

        elif cmd == "buy":
            if len(args) < 3:
                print("Error: buy requires <token> <usd_amount>")
                sys.exit(1)
            asyncio.run(cmd_buy(args[1], float(args[2])))

        elif cmd == "sell":
            if len(args) < 3:
                print("Error: sell requires <token> <usd_amount>")
                sys.exit(1)
            asyncio.run(cmd_sell(args[1], float(args[2])))

        elif cmd == "check":
            if len(args) < 2:
                print("Error: check requires <token>")
                sys.exit(1)
            asyncio.run(cmd_check(args[1]))

        elif cmd == "search":
            if len(args) < 2:
                print("Error: search requires <query>")
                sys.exit(1)
            asyncio.run(cmd_search(args[1]))

        elif cmd == "resolve":
            if len(args) < 2:
                print("Error: resolve requires <token>")
                sys.exit(1)
            asyncio.run(cmd_resolve(args[1]))

        elif cmd == "strategy":
            # Parse strategy flags: [name] [--slippage BPS] [--max-trade USD]
            name = None
            slippage_bps = None
            max_trade_usd = None

            i = 1
            while i < len(args):
                arg = args[i]
                if arg in ("--slippage", "-s") and i + 1 < len(args):
                    try:
                        slippage_bps = int(args[i + 1])
                    except ValueError:
                        print(f"Error: slippage must be an integer (basis points)")
                        sys.exit(1)
                    i += 2
                elif arg in ("--max-trade", "-m") and i + 1 < len(args):
                    try:
                        max_trade_usd = float(args[i + 1])
                    except ValueError:
                        print(f"Error: max-trade must be a number (USD)")
                        sys.exit(1)
                    i += 2
                elif not arg.startswith("-"):
                    name = arg
                    i += 1
                else:
                    i += 1

            asyncio.run(cmd_strategy(name, slippage_bps, max_trade_usd))

        elif cmd == "scan":
            filter_type = args[1] if len(args) > 1 else "all"
            asyncio.run(cmd_scan(filter_type))

        elif cmd == "deploy":
            # Parse deploy flags
            # slopesniper deploy --name "Token" --symbol TKN --desc "Description" --image path/url --dev-buy 1.0 --platform pump|bags
            name = None
            symbol = None
            description = None
            image = None
            dev_buy = 0.0
            platform = "auto"
            twitter = None
            telegram = None
            website = None

            i = 1
            while i < len(args):
                arg = args[i]
                if arg in ("--name", "-n") and i + 1 < len(args):
                    name = args[i + 1]
                    i += 2
                elif arg in ("--symbol", "-s") and i + 1 < len(args):
                    symbol = args[i + 1]
                    i += 2
                elif arg in ("--desc", "--description", "-d") and i + 1 < len(args):
                    description = args[i + 1]
                    i += 2
                elif arg in ("--image", "-i") and i + 1 < len(args):
                    image = args[i + 1]
                    i += 2
                elif arg in ("--dev-buy", "--devbuy", "-b") and i + 1 < len(args):
                    try:
                        dev_buy = float(args[i + 1])
                    except ValueError:
                        print("Error: dev-buy must be a number (SOL)")
                        sys.exit(1)
                    i += 2
                elif arg in ("--platform", "-p") and i + 1 < len(args):
                    platform = args[i + 1].lower()
                    i += 2
                elif arg == "--twitter" and i + 1 < len(args):
                    twitter = args[i + 1]
                    i += 2
                elif arg == "--telegram" and i + 1 < len(args):
                    telegram = args[i + 1]
                    i += 2
                elif arg == "--website" and i + 1 < len(args):
                    website = args[i + 1]
                    i += 2
                elif arg == "--status":
                    # Show deploy status instead
                    cmd_deploy_status()
                    return
                elif arg == "--setup-pump":
                    # Setup PumpPortal
                    asyncio.run(cmd_setup_pumpportal())
                    return
                else:
                    i += 1

            # Validate required args
            if not name or not symbol or not description or not image:
                print("Error: deploy requires --name, --symbol, --desc, and --image")
                print("Usage: slopesniper deploy --name 'Token' --symbol TKN --desc 'Description' --image path/url [--dev-buy SOL] [--platform pump|bags]")
                print("\nOther commands:")
                print("  slopesniper deploy --status        Show deployment configuration")
                print("  slopesniper deploy --setup-pump    Setup PumpPortal (auto-generates wallet/key)")
                sys.exit(1)

            asyncio.run(cmd_deploy(
                name=name,
                symbol=symbol,
                description=description,
                image=image,
                dev_buy_sol=dev_buy,
                platform=platform,
                twitter=twitter,
                telegram=telegram,
                website=website,
            ))

        elif cmd == "config":
            # Parse config flags: --set KEY VALUE or --clear KEY
            set_key = None
            set_value = None
            clear_key = None

            i = 1  # Skip 'config'
            while i < len(args):
                arg = args[i]
                if arg == "--set" and i + 2 < len(args):
                    set_key = args[i + 1]
                    set_value = args[i + 2]
                    i += 3
                elif arg == "--clear" and i + 1 < len(args):
                    clear_key = args[i + 1]
                    i += 2
                # Legacy support
                elif arg == "--set-jupiter-key" and i + 1 < len(args):
                    set_key = "jupiter-key"
                    set_value = args[i + 1]
                    i += 2
                elif arg == "--set-rpc" and i + 2 < len(args):
                    set_key = args[i + 1]  # provider name
                    set_value = args[i + 2]
                    i += 3
                elif arg == "--clear-rpc":
                    clear_key = "rpc"
                    i += 1
                else:
                    i += 1

            cmd_config(set_key=set_key, set_value=set_value, clear_key=clear_key)

        elif cmd == "health":
            diagnose = "--diagnose" in args or "-d" in args
            cmd_health(diagnose=diagnose)

        elif cmd == "restore":
            if len(args) < 2:
                print_json({"error": "Missing timestamp", "usage": "slopesniper restore TIMESTAMP"})
                sys.exit(1)
            cmd_restore(args[1])

        elif cmd == "version":
            check_latest = "--check" in args or "-c" in args
            cmd_version(check_latest=check_latest)

        elif cmd == "update":
            cmd_update()

        elif cmd == "contribute":
            enable = "--enable" in args
            disable = "--disable" in args
            cmd_contribute(enable=enable, disable=disable)

        elif cmd == "uninstall":
            confirm = "--confirm" in args or "-y" in args
            keep_data = "--keep-data" in args
            cmd_uninstall(keep_data=keep_data, confirm=confirm)

        # ================================================================
        # Auto-sell Target Commands
        # ================================================================
        elif cmd == "target":
            if len(args) < 2:
                print_json({
                    "error": "Missing subcommand",
                    "usage": [
                        "slopesniper target add TOKEN --mcap VALUE --sell all",
                        "slopesniper target list [--all]",
                        "slopesniper target remove ID",
                    ],
                })
                sys.exit(1)

            subcmd = args[1].lower()

            if subcmd == "add":
                if len(args) < 3:
                    print_json({"error": "Missing token", "usage": "slopesniper target add TOKEN --mcap VALUE"})
                    sys.exit(1)

                token = args[2]
                mcap = price = pct_gain = trailing = None
                sell = "all"

                i = 3
                while i < len(args):
                    arg = args[i]
                    if arg == "--mcap" and i + 1 < len(args):
                        mcap = float(args[i + 1])
                        i += 2
                    elif arg == "--price" and i + 1 < len(args):
                        price = float(args[i + 1])
                        i += 2
                    elif arg in ("--pct-gain", "--pct", "--gain") and i + 1 < len(args):
                        pct_gain = float(args[i + 1])
                        i += 2
                    elif arg in ("--trailing", "--trail") and i + 1 < len(args):
                        trailing = float(args[i + 1])
                        i += 2
                    elif arg == "--sell" and i + 1 < len(args):
                        sell = args[i + 1]
                        i += 2
                    else:
                        i += 1

                asyncio.run(cmd_target_add(token, mcap, price, pct_gain, trailing, sell))

            elif subcmd == "list":
                show_all = "--all" in args or "-a" in args
                asyncio.run(cmd_target_list(show_all))

            elif subcmd == "remove":
                if len(args) < 3:
                    print_json({"error": "Missing target ID", "usage": "slopesniper target remove ID"})
                    sys.exit(1)
                try:
                    target_id = int(args[2])
                except ValueError:
                    print_json({"error": "Target ID must be a number"})
                    sys.exit(1)
                asyncio.run(cmd_target_remove(target_id))

            else:
                print_json({"error": f"Unknown target subcommand: {subcmd}"})
                sys.exit(1)

        elif cmd == "watch":
            if len(args) < 2:
                print_json({"error": "Missing token", "usage": "slopesniper watch TOKEN --mcap VALUE"})
                sys.exit(1)

            token = args[1]
            mcap = price = pct_gain = trailing = None
            sell = "all"
            interval = 5

            i = 2
            while i < len(args):
                arg = args[i]
                if arg == "--mcap" and i + 1 < len(args):
                    mcap = float(args[i + 1])
                    i += 2
                elif arg == "--price" and i + 1 < len(args):
                    price = float(args[i + 1])
                    i += 2
                elif arg in ("--pct-gain", "--pct", "--gain") and i + 1 < len(args):
                    pct_gain = float(args[i + 1])
                    i += 2
                elif arg in ("--trailing", "--trail") and i + 1 < len(args):
                    trailing = float(args[i + 1])
                    i += 2
                elif arg == "--sell" and i + 1 < len(args):
                    sell = args[i + 1]
                    i += 2
                elif arg in ("--interval", "-i") and i + 1 < len(args):
                    interval = int(args[i + 1])
                    i += 2
                else:
                    i += 1

            asyncio.run(cmd_watch_foreground(token, mcap, price, pct_gain, trailing, sell, interval))

        elif cmd == "daemon":
            if len(args) < 2:
                print_json({
                    "error": "Missing subcommand",
                    "usage": ["slopesniper daemon start", "slopesniper daemon stop", "slopesniper daemon status"],
                })
                sys.exit(1)

            subcmd = args[1].lower()

            if subcmd == "start":
                interval = 15
                if "--interval" in args:
                    idx = args.index("--interval")
                    if idx + 1 < len(args):
                        interval = int(args[idx + 1])
                from .daemon import start_daemon
                result = start_daemon(interval)
                print_json(result)

            elif subcmd == "stop":
                from .daemon import stop_daemon
                result = stop_daemon()
                print_json(result)

            elif subcmd == "status":
                from .daemon import get_daemon_status
                result = get_daemon_status()
                print_json(result)

            elif subcmd == "logs":
                tail = 50
                if "--tail" in args:
                    idx = args.index("--tail")
                    if idx + 1 < len(args):
                        tail = int(args[idx + 1])
                from .daemon import get_daemon_logs
                result = get_daemon_logs(tail)
                print_json(result)

            else:
                print_json({"error": f"Unknown daemon subcommand: {subcmd}"})
                sys.exit(1)

        else:
            print(f"Unknown command: {cmd}")
            print_help()
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
