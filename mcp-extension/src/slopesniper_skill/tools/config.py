"""
Configuration and Secret Management.

Handles secure retrieval of secrets with gateway -> env fallback.
Supports auto-generation and encrypted local storage of wallet keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import base58
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from solders.keypair import Keypair

# Local storage paths
SLOPESNIPER_DIR = Path.home() / ".slopesniper"
WALLET_FILE = SLOPESNIPER_DIR / "wallet.json"
WALLET_FILE_ENCRYPTED = SLOPESNIPER_DIR / "wallet.enc"
WALLET_BACKUP_DIR = SLOPESNIPER_DIR / "wallet_backups"
MACHINE_KEY_FILE = SLOPESNIPER_DIR / ".machine_key"
USER_CONFIG_FILE = SLOPESNIPER_DIR / "config.enc"

# Maximum number of wallet backups to keep
MAX_WALLET_BACKUPS = 10


@dataclass
class PolicyConfig:
    """Policy configuration with safe defaults."""

    MAX_SLIPPAGE_BPS: int = 100  # 1% max slippage
    MAX_TRADE_USD: float = 50.0  # $50 max per trade
    MIN_RUGCHECK_SCORE: int = 2000  # Block if score > this
    REQUIRE_MINT_DISABLED: bool = True  # Block if mint authority active
    REQUIRE_FREEZE_DISABLED: bool = True  # Block if freeze authority active
    DENY_MINTS: list[str] = field(default_factory=list)  # Blocked token mints
    ALLOW_MINTS: list[str] = field(default_factory=list)  # If set, ONLY these allowed


def _ensure_wallet_dir() -> None:
    """Create wallet directory if it doesn't exist."""
    SLOPESNIPER_DIR.mkdir(parents=True, exist_ok=True)
    # Set restrictive permissions on the directory
    os.chmod(SLOPESNIPER_DIR, 0o700)


def _get_machine_id() -> str:
    """
    Get a machine-specific identifier for encryption key derivation.

    Combines multiple sources to create a stable machine fingerprint.
    """
    components = []

    # Platform info
    components.append(platform.node())
    components.append(platform.machine())
    components.append(platform.system())

    # Try to get hardware UUID (macOS)
    try:
        import subprocess

        result = subprocess.run(
            ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "IOPlatformUUID" in result.stdout:
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    uuid_part = line.split('"')[-2]
                    components.append(uuid_part)
                    break
    except Exception:
        pass

    # Try to get machine-id (Linux)
    try:
        machine_id_path = Path("/etc/machine-id")
        if machine_id_path.exists():
            components.append(machine_id_path.read_text().strip())
    except Exception:
        pass

    # Combine all components
    combined = "|".join(components)
    return hashlib.sha256(combined.encode()).hexdigest()


def _get_or_create_machine_key() -> bytes:
    """
    Get or create a machine-specific encryption key.

    The key is derived from:
    1. Machine-specific identifier (hardware/OS fingerprint)
    2. A random salt stored locally

    This ensures:
    - Wallet files are encrypted at rest
    - Wallet files are tied to this machine
    - Key survives updates (salt is persistent)
    """
    _ensure_wallet_dir()

    # Load or generate salt
    if MACHINE_KEY_FILE.exists():
        try:
            key_data = json.loads(MACHINE_KEY_FILE.read_text())
            salt = bytes.fromhex(key_data["salt"])
        except Exception:
            # Corrupted key file, regenerate
            salt = secrets.token_bytes(32)
            key_data = {"salt": salt.hex(), "version": 1}
            MACHINE_KEY_FILE.write_text(json.dumps(key_data))
            os.chmod(MACHINE_KEY_FILE, 0o600)
    else:
        salt = secrets.token_bytes(32)
        key_data = {"salt": salt.hex(), "version": 1}
        MACHINE_KEY_FILE.write_text(json.dumps(key_data))
        os.chmod(MACHINE_KEY_FILE, 0o600)

    # Derive key from machine ID + salt
    machine_id = _get_machine_id()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    key = kdf.derive(machine_id.encode())

    # Fernet requires URL-safe base64 encoded key
    import base64

    return base64.urlsafe_b64encode(key)


def _encrypt_data(data: str) -> bytes:
    """Encrypt data using machine-specific key."""
    key = _get_or_create_machine_key()
    f = Fernet(key)
    return f.encrypt(data.encode())


def _decrypt_data(encrypted: bytes) -> str:
    """Decrypt data using machine-specific key."""
    key = _get_or_create_machine_key()
    f = Fernet(key)
    return f.decrypt(encrypted).decode()


def generate_wallet() -> tuple[str, str]:
    """
    Generate a new Solana wallet.

    Returns:
        Tuple of (private_key_base58, public_address)
    """
    keypair = Keypair()
    private_key = base58.b58encode(bytes(keypair)).decode()
    address = str(keypair.pubkey())
    return private_key, address


def _backup_existing_wallet() -> str | None:
    """
    Backup existing wallet before overwriting.

    Creates a timestamped backup in ~/.slopesniper/wallet_backups/
    Keeps only the most recent MAX_WALLET_BACKUPS files.

    Returns:
        Path to backup file if created, None if no wallet to backup
    """
    import shutil
    from datetime import datetime

    # Check if there's a wallet to backup
    if not WALLET_FILE_ENCRYPTED.exists() and not WALLET_FILE.exists():
        return None

    # Create backup directory
    WALLET_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(WALLET_BACKUP_DIR, 0o700)

    # Generate timestamped backup filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Backup encrypted wallet
    if WALLET_FILE_ENCRYPTED.exists():
        backup_path = WALLET_BACKUP_DIR / f"wallet.enc.{timestamp}"
        shutil.copy2(WALLET_FILE_ENCRYPTED, backup_path)
        os.chmod(backup_path, 0o600)

        # Also try to save the address for reference
        try:
            wallet = load_local_wallet()
            if wallet and "address" in wallet:
                addr_file = WALLET_BACKUP_DIR / f"wallet.enc.{timestamp}.address"
                addr_file.write_text(wallet["address"])
                os.chmod(addr_file, 0o600)
        except Exception:
            pass

    # Backup plaintext wallet (legacy)
    elif WALLET_FILE.exists():
        backup_path = WALLET_BACKUP_DIR / f"wallet.json.{timestamp}"
        shutil.copy2(WALLET_FILE, backup_path)
        os.chmod(backup_path, 0o600)

    # Cleanup old backups (keep only MAX_WALLET_BACKUPS most recent)
    _cleanup_old_backups()

    return str(backup_path)


def _cleanup_old_backups() -> None:
    """Remove old wallet backups, keeping only the most recent ones."""
    if not WALLET_BACKUP_DIR.exists():
        return

    # Get all backup files (exclude .address files)
    backups = sorted(
        [f for f in WALLET_BACKUP_DIR.iterdir() if f.is_file() and not f.name.endswith(".address")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Remove old backups beyond the limit
    for old_backup in backups[MAX_WALLET_BACKUPS:]:
        try:
            old_backup.unlink()
            # Also remove corresponding .address file if it exists
            addr_file = old_backup.parent / f"{old_backup.name}.address"
            if addr_file.exists():
                addr_file.unlink()
        except Exception:
            pass


def save_wallet(private_key: str, address: str) -> None:
    """
    Save wallet to encrypted local storage.

    The wallet is encrypted with a machine-specific key,
    meaning it can only be decrypted on this machine.

    If a wallet already exists, it will be backed up first to
    ~/.slopesniper/wallet_backups/ with a timestamp.
    """
    _ensure_wallet_dir()

    # Backup existing wallet before overwriting
    backup_path = _backup_existing_wallet()
    if backup_path:
        # Log that we backed up (silent, but useful for debugging)
        pass

    wallet_data = {
        "private_key": private_key,
        "address": address,
        "version": 2,  # v2 = encrypted
    }

    # Encrypt the wallet data
    encrypted = _encrypt_data(json.dumps(wallet_data))

    # Save encrypted wallet
    WALLET_FILE_ENCRYPTED.write_bytes(encrypted)
    os.chmod(WALLET_FILE_ENCRYPTED, 0o600)

    # Remove old plaintext wallet if it exists
    if WALLET_FILE.exists():
        WALLET_FILE.unlink()


def _migrate_plaintext_wallet() -> dict | None:
    """
    Migrate old plaintext wallet to encrypted format.

    Returns the wallet data if migration was successful.
    """
    if not WALLET_FILE.exists():
        return None

    try:
        data = json.loads(WALLET_FILE.read_text())
        if "private_key" in data and "address" in data:
            # Migrate to encrypted format
            save_wallet(data["private_key"], data["address"])
            return data
    except Exception:
        pass

    return None


def load_local_wallet(raise_on_decrypt_error: bool = False) -> dict | None:
    """
    Load wallet from encrypted local storage.

    Args:
        raise_on_decrypt_error: If True, raise exception on decryption failure
            instead of returning None. Useful for diagnosing issues.

    Returns:
        dict with private_key and address, or None if not found
    """
    # Check for encrypted wallet first
    if WALLET_FILE_ENCRYPTED.exists():
        try:
            encrypted = WALLET_FILE_ENCRYPTED.read_bytes()
            decrypted = _decrypt_data(encrypted)
            data = json.loads(decrypted)
            if "private_key" in data and "address" in data:
                return data
        except InvalidToken:
            # Key mismatch - wallet from different machine or corrupted .machine_key
            if raise_on_decrypt_error:
                raise ValueError(
                    "Cannot decrypt wallet.enc - machine key mismatch. "
                    "This wallet was created on a different machine or .machine_key is corrupted. "
                    "Check ~/.slopesniper/wallet_backups/ for recoverable backups."
                )
            return None
        except Exception as e:
            if raise_on_decrypt_error:
                raise ValueError(f"Failed to load wallet: {e}")
            pass

    # Try to migrate old plaintext wallet
    migrated = _migrate_plaintext_wallet()
    if migrated:
        return migrated

    return None


def get_or_create_wallet() -> tuple[str, str, bool]:
    """
    Get existing wallet or create a new one.

    Returns:
        Tuple of (private_key, address, is_new)
        is_new is True if wallet was just generated
    """
    # Check environment variable first (override)
    env_key = os.environ.get("SOLANA_PRIVATE_KEY")
    if env_key:
        keypair = _parse_private_key(env_key)
        if keypair:
            return env_key, str(keypair.pubkey()), False

    # Check local storage
    local_wallet = load_local_wallet()
    if local_wallet:
        return local_wallet["private_key"], local_wallet["address"], False

    # Generate new wallet
    private_key, address = generate_wallet()
    save_wallet(private_key, address)
    return private_key, address, True


def _parse_private_key(private_key: str) -> Keypair | None:
    """Parse private key in various formats."""
    try:
        if private_key.startswith("["):
            key_bytes = bytes(json.loads(private_key))
            return Keypair.from_bytes(key_bytes)
        else:
            key_bytes = base58.b58decode(private_key)
            return Keypair.from_bytes(key_bytes)
    except Exception:
        return None


def get_secret(name: str) -> str | None:
    """
    Get a secret value with gateway -> env fallback.

    Args:
        name: Secret name (e.g., 'SOLANA_PRIVATE_KEY')

    Returns:
        Secret value or None if not found

    Priority:
    1. Moltbot gateway secret API (if available)
    2. Environment variable
    3. None
    """
    # Try moltbot gateway first, fallback to clawdbot for backward compatibility
    gateway_url = os.environ.get("MOLTBOT_GATEWAY_URL") or os.environ.get("CLAWDBOT_GATEWAY_URL")
    if gateway_url:
        try:
            # Future: implement gateway secret fetch
            pass
        except Exception:
            pass

    # Fallback to environment variable
    env_value = os.environ.get(name)
    if env_value:
        return env_value

    return None


def get_keypair() -> Keypair | None:
    """
    Load Solana keypair from local storage or environment.

    Priority:
    1. SOLANA_PRIVATE_KEY environment variable
    2. Local wallet file (~/.slopesniper/wallet.json)
    3. None (caller should use get_or_create_wallet to generate)

    Returns:
        Keypair or None if not configured

    Raises:
        ValueError: If key format is invalid
    """
    # Check env var first
    private_key = get_secret("SOLANA_PRIVATE_KEY")
    if private_key:
        keypair = _parse_private_key(private_key)
        if keypair:
            return keypair
        raise ValueError("Invalid SOLANA_PRIVATE_KEY format")

    # Check local wallet
    local_wallet = load_local_wallet()
    if local_wallet:
        keypair = _parse_private_key(local_wallet["private_key"])
        if keypair:
            return keypair

    return None


def get_wallet_address() -> str | None:
    """
    Get the wallet address from the configured keypair.

    Returns:
        Wallet address string or None if not configured
    """
    keypair = get_keypair()
    if keypair:
        return str(keypair.pubkey())
    return None


def get_wallet_sync_status() -> dict:
    """
    Check wallet configuration sync status.

    Detects mismatches between environment variable and local wallet file.
    This helps identify desynchronization issues between wrapper (Moltbot/MCP)
    and CLI configurations.

    Returns:
        Dict with:
        - active_source: "environment" | "local" | "none"
        - active_address: Current active wallet address
        - env_configured: bool
        - env_address: Address from env var (if set)
        - local_configured: bool
        - local_address: Address from local file (if exists)
        - is_synced: True if no mismatch detected
        - warning: Warning message if mismatch detected
    """
    result = {
        "active_source": "none",
        "active_address": None,
        "env_configured": False,
        "env_address": None,
        "local_configured": False,
        "local_address": None,
        "is_synced": True,
        "warning": None,
    }

    # Check environment variable
    env_key = os.environ.get("SOLANA_PRIVATE_KEY")
    if env_key:
        keypair = _parse_private_key(env_key)
        if keypair:
            result["env_configured"] = True
            result["env_address"] = str(keypair.pubkey())

    # Check local wallet file
    local_wallet = load_local_wallet()
    if local_wallet:
        result["local_configured"] = True
        result["local_address"] = local_wallet.get("address")

    # Determine active source (matches get_keypair priority)
    if result["env_configured"]:
        result["active_source"] = "environment"
        result["active_address"] = result["env_address"]
    elif result["local_configured"]:
        result["active_source"] = "local"
        result["active_address"] = result["local_address"]

    # Check for mismatch
    if result["env_configured"] and result["local_configured"]:
        if result["env_address"] != result["local_address"]:
            result["is_synced"] = False
            result["warning"] = (
                f"WALLET MISMATCH: Environment variable points to {result['env_address'][:8]}... "
                f"but local wallet file contains {result['local_address'][:8]}... "
                f"Using environment variable (priority). "
                f"Run 'slopesniper setup --import-key' to sync, or unset SOLANA_PRIVATE_KEY to use local."
            )

    return result


def get_rpc_url() -> str:
    """
    Get Solana RPC URL with priority: env > user config > default.

    Priority:
    1. SOLANA_RPC_URL environment variable
    2. User's configured RPC provider (~/.slopesniper/config.enc)
    3. Default mainnet-beta endpoint

    Returns:
        RPC URL
    """
    # Check env var first (highest priority)
    env_url = get_secret("SOLANA_RPC_URL")
    if env_url:
        return env_url

    # Check user config
    config = load_user_config()
    if config and config.get("rpc_provider"):
        provider = config["rpc_provider"]
        value = config.get("rpc_value")
        if provider and value:
            return _build_rpc_url(provider, value)

    # Default
    return "https://api.mainnet-beta.solana.com"


def save_user_config(config: dict, merge: bool = True) -> None:
    """
    Save user configuration (encrypted).

    Args:
        config: Dict with user settings (e.g., jupiter_api_key, rpc_url)
        merge: If True, merge with existing config. If False, replace entirely.
    """
    _ensure_wallet_dir()

    if merge:
        # Merge with existing config
        existing = load_user_config() or {}
        existing.update(config)
        config = existing

    encrypted = _encrypt_data(json.dumps(config))
    USER_CONFIG_FILE.write_bytes(encrypted)
    os.chmod(USER_CONFIG_FILE, 0o600)


def load_user_config() -> dict | None:
    """
    Load user configuration (encrypted).

    Returns:
        Dict with user settings or None if not found
    """
    if not USER_CONFIG_FILE.exists():
        return None

    try:
        encrypted = USER_CONFIG_FILE.read_bytes()
        decrypted = _decrypt_data(encrypted)
        return json.loads(decrypted)
    except Exception:
        return None


def record_wallet_created() -> None:
    """Record when wallet was created (for backup reminder tracking)."""
    save_user_config({"wallet_created_at": datetime.now().isoformat()})


def record_backup_export() -> None:
    """Record that user exported their wallet (for reminder tracking)."""
    save_user_config({"last_backup_export": datetime.now().isoformat()})


def get_backup_status() -> dict:
    """
    Check if wallet needs backup reminder.

    Returns dict with:
    - wallet_created_at: str | None
    - last_backup_export: str | None
    - days_since_creation: int | None
    - days_since_export: int | None
    - needs_reminder: bool
    """
    config = load_user_config() or {}

    wallet_created_at = config.get("wallet_created_at")
    last_backup_export = config.get("last_backup_export")

    days_since_creation = None
    days_since_export = None

    if wallet_created_at:
        try:
            created = datetime.fromisoformat(wallet_created_at)
            days_since_creation = (datetime.now() - created).days
        except Exception:
            pass

    if last_backup_export:
        try:
            exported = datetime.fromisoformat(last_backup_export)
            days_since_export = (datetime.now() - exported).days
        except Exception:
            pass

    # Show reminder if:
    # - Never exported, OR
    # - Last export was more than 7 days ago
    needs_reminder = last_backup_export is None or (
        days_since_export is not None and days_since_export > 7
    )

    return {
        "wallet_created_at": wallet_created_at,
        "last_backup_export": last_backup_export,
        "days_since_creation": days_since_creation,
        "days_since_export": days_since_export,
        "needs_reminder": needs_reminder,
    }


def set_jupiter_api_key(api_key: str) -> dict:
    """
    Save user's Jupiter API key for improved performance.

    Args:
        api_key: Jupiter Ultra API key

    Returns:
        Status dict
    """
    if not api_key or len(api_key) < 10:
        return {"success": False, "error": "Invalid API key format"}

    save_user_config({"jupiter_api_key": api_key})

    return {
        "success": True,
        "message": "Jupiter API key saved (encrypted)",
        "benefits": [
            "Higher rate limits",
            "Faster quote responses",
            "Priority routing",
        ],
    }


def get_jupiter_api_key() -> str | None:
    """
    Get Jupiter API key with priority: env var > local config > None.

    Priority:
    1. JUPITER_API_KEY environment variable
    2. User's saved config (~/.slopesniper/config.enc)
    3. None (will use bundled key from GitHub)

    Returns:
        API key or None
    """
    # Check env var first
    env_key = get_secret("JUPITER_API_KEY")
    if env_key:
        return env_key

    # Check user's saved config
    config = load_user_config()
    if config and config.get("jupiter_api_key"):
        return config["jupiter_api_key"]

    return None


def clear_jupiter_api_key() -> dict:
    """
    Clear saved Jupiter API key (revert to bundled key).

    Returns:
        Status dict
    """
    config = load_user_config() or {}
    had_key = "jupiter_api_key" in config
    config.pop("jupiter_api_key", None)
    save_user_config(config, merge=False)

    return {
        "success": True,
        "cleared": had_key,
        "message": "Jupiter API key cleared. Now using bundled key.",
        "tip": "Get your own free key at: https://station.jup.ag/docs/apis/ultra-api",
    }


# ============================================================================
# Token Deployment API Keys (Pump.fun / Bags.fm)
# ============================================================================


def set_bags_api_key(api_key: str, partner_key: str | None = None) -> dict:
    """
    Save Bags.fm API key and optional partner key.

    Args:
        api_key: Bags.fm API key (from dev.bags.fm)
        partner_key: Optional partner key for fee sharing

    Returns:
        Status dict
    """
    if not api_key or len(api_key) < 10:
        return {"success": False, "error": "Invalid API key format"}

    config_data = {"bags_api_key": api_key}
    if partner_key:
        config_data["bags_partner_key"] = partner_key

    save_user_config(config_data)

    return {
        "success": True,
        "message": "Bags.fm API key saved (encrypted)",
        "partner_configured": bool(partner_key),
        "capabilities": [
            "Token launches on Bags.fm",
            "Fee sharing configuration",
            "Token metadata uploads",
        ],
    }


def get_bags_api_key() -> str | None:
    """
    Get Bags.fm API key.

    Priority:
    1. BAGS_API_KEY environment variable
    2. User's saved config (~/.slopesniper/config.enc)

    Returns:
        API key or None
    """
    env_key = os.environ.get("BAGS_API_KEY")
    if env_key:
        return env_key

    config = load_user_config()
    if config and config.get("bags_api_key"):
        return config["bags_api_key"]

    return None


def get_bags_partner_key() -> str | None:
    """
    Get Bags.fm partner key for fee sharing.

    Returns:
        Partner key or None
    """
    env_key = os.environ.get("BAGS_PARTNER_KEY")
    if env_key:
        return env_key

    config = load_user_config()
    if config and config.get("bags_partner_key"):
        return config["bags_partner_key"]

    return None


def set_pumpportal_api_key(api_key: str, linked_wallet: str | None = None) -> dict:
    """
    Save PumpPortal API key.

    Args:
        api_key: PumpPortal API key
        linked_wallet: Optional linked wallet address (for reference)

    Returns:
        Status dict
    """
    if not api_key or len(api_key) < 10:
        return {"success": False, "error": "Invalid API key format"}

    config_data = {"pumpportal_api_key": api_key}
    if linked_wallet:
        config_data["pumpportal_linked_wallet"] = linked_wallet

    save_user_config(config_data)

    return {
        "success": True,
        "message": "PumpPortal API key saved (encrypted)",
        "linked_wallet": linked_wallet,
        "capabilities": [
            "Token launches on Pump.fun",
            "Lightning transactions (no local signing)",
            "Jito bundle support",
        ],
        "note": "Linked wallet must have 0.02+ SOL for data API access",
    }


def get_pumpportal_api_key() -> str | None:
    """
    Get PumpPortal API key.

    Priority:
    1. PUMPPORTAL_API_KEY environment variable
    2. User's saved config (~/.slopesniper/config.enc)

    Returns:
        API key or None
    """
    env_key = os.environ.get("PUMPPORTAL_API_KEY")
    if env_key:
        return env_key

    config = load_user_config()
    if config and config.get("pumpportal_api_key"):
        return config["pumpportal_api_key"]

    return None


def get_pumpportal_linked_wallet() -> str | None:
    """
    Get PumpPortal linked wallet address.

    Returns:
        Wallet address or None
    """
    config = load_user_config()
    if config and config.get("pumpportal_linked_wallet"):
        return config["pumpportal_linked_wallet"]
    return None


def get_deploy_config_status() -> dict:
    """
    Get status of token deployment API configurations.

    Returns:
        Dict with deployment API status
    """
    bags_key = get_bags_api_key()
    bags_partner = get_bags_partner_key()
    pumpportal_key = get_pumpportal_api_key()
    pumpportal_wallet = get_pumpportal_linked_wallet()

    return {
        "bags_fm": {
            "configured": bool(bags_key),
            "partner_configured": bool(bags_partner),
            "key_preview": f"{bags_key[:10]}...{bags_key[-4:]}" if bags_key else None,
        },
        "pumpportal": {
            "configured": bool(pumpportal_key),
            "linked_wallet": pumpportal_wallet,
            "key_preview": f"{pumpportal_key[:10]}...{pumpportal_key[-4:]}" if pumpportal_key else None,
        },
        "ready_to_deploy": bool(bags_key or pumpportal_key),
    }


# RPC Provider Configuration
RPC_PROVIDERS = {
    "helius": "https://mainnet.helius-rpc.com/?api-key={key}",
    "alchemy": "https://solana-mainnet.g.alchemy.com/v2/{key}",
    "quicknode": None,  # Full URL provided by user
    "custom": None,  # Full URL provided by user
}


def _build_rpc_url(provider: str, value: str) -> str:
    """
    Build full RPC URL from provider and key/url.

    Args:
        provider: helius | alchemy | quicknode | custom
        value: API key (helius/alchemy) or full URL (quicknode/custom)

    Returns:
        Full RPC URL
    """
    if provider == "helius":
        return f"https://mainnet.helius-rpc.com/?api-key={value}"
    elif provider == "alchemy":
        return f"https://solana-mainnet.g.alchemy.com/v2/{value}"
    elif provider in ("quicknode", "custom"):
        return value  # Full URL already provided
    return value


def _validate_rpc_config(provider: str, value: str) -> tuple[bool, str | None]:
    """
    Validate RPC provider and value.

    Args:
        provider: Provider name
        value: API key or URL

    Returns:
        Tuple of (is_valid, error_message)
    """
    if provider not in RPC_PROVIDERS:
        return False, f"Invalid provider. Must be one of: {', '.join(RPC_PROVIDERS.keys())}"

    if not value or len(value) < 5:
        return False, "Value too short"

    # Provider-specific validation
    if provider == "helius":
        # Helius keys are alphanumeric
        if not value.replace("-", "").replace("_", "").isalnum():
            return False, "Invalid Helius API key format"

    elif provider == "alchemy":
        # Alchemy keys are alphanumeric with hyphens/underscores
        if not value.replace("-", "").replace("_", "").isalnum():
            return False, "Invalid Alchemy API key format"

    elif provider == "quicknode":
        # Quicknode URLs must match pattern
        if not value.startswith("https://") or "quiknode.pro" not in value:
            return (
                False,
                "Invalid Quicknode URL. Must be https://your-endpoint.solana-*.quiknode.pro/...",
            )

    elif provider == "custom":
        # Custom must be a valid HTTPS URL
        if not value.startswith("https://") and not value.startswith("http://"):
            return False, "Custom RPC URL must start with https:// or http://"

    return True, None


def set_rpc_config(provider: str, value: str) -> dict:
    """
    Set RPC provider configuration.

    Args:
        provider: helius | alchemy | quicknode | custom
        value: API key (helius/alchemy) or full URL (quicknode/custom)

    Returns:
        Status dict with success/error
    """
    # Validate
    is_valid, error = _validate_rpc_config(provider, value)
    if not is_valid:
        return {"success": False, "error": error}

    # Save to encrypted config
    save_user_config(
        {
            "rpc_provider": provider,
            "rpc_value": value,
        }
    )

    # Build URL for display (masked)
    url = _build_rpc_url(provider, value)
    # Mask the key/token in display
    if provider in ("helius", "alchemy"):
        display_url = _build_rpc_url(provider, "****")
    else:
        # Mask the path for URLs
        display_url = url.split("//")[0] + "//" + url.split("//")[1].split("/")[0] + "/****"

    return {
        "success": True,
        "message": f"RPC endpoint configured: {provider}",
        "provider": provider,
        "url_preview": display_url,
        "benefits": [
            "Faster transaction processing",
            "Higher rate limits",
            "Better reliability",
            "Priority access to network",
        ],
    }


def clear_rpc_config() -> dict:
    """
    Clear custom RPC configuration (revert to default).

    Returns:
        Status dict
    """
    config = load_user_config() or {}
    config.pop("rpc_provider", None)
    config.pop("rpc_value", None)
    save_user_config(config, merge=False)

    return {
        "success": True,
        "message": "RPC configuration cleared. Using default endpoint.",
        "default_url": "https://api.mainnet-beta.solana.com",
    }


def get_rpc_config_status() -> dict:
    """
    Get current RPC configuration status.

    Returns:
        Dict with RPC config details
    """
    config = load_user_config() or {}
    env_url = os.environ.get("SOLANA_RPC_URL")

    provider = config.get("rpc_provider")
    value = config.get("rpc_value")
    has_custom = bool(env_url or (provider and value))

    # Determine source
    source = "default"
    url = "https://api.mainnet-beta.solana.com"
    url_preview = url

    if env_url:
        source = "environment"
        url = env_url
        # Mask env URL for display
        url_preview = url.split("//")[0] + "//" + url.split("//")[1].split("/")[0] + "/****"
    elif provider and value:
        source = "local_config"
        url = _build_rpc_url(provider, value)
        # Mask the key/token
        if provider in ("helius", "alchemy"):
            url_preview = _build_rpc_url(provider, "****")
        else:
            url_preview = url.split("//")[0] + "//" + url.split("//")[1].split("/")[0] + "/****"

    result = {
        "configured": has_custom,
        "provider": provider or "default",
        "source": source,
        "url": url,
        "url_preview": url_preview,
    }

    if not has_custom:
        result["recommendation"] = {
            "message": "Using default RPC endpoint. For faster transactions, configure a custom RPC provider.",
            "providers": {
                "helius": "Fast, reliable. Get free key at: https://www.helius.dev",
                "quicknode": "Enterprise-grade. Get started at: https://www.quicknode.com",
                "alchemy": "High-performance. Sign up at: https://www.alchemy.com",
            },
            "how_to": "Run: slopesniper config --set-rpc helius YOUR_KEY",
        }

    return result


def get_config_status() -> dict:
    """
    Get current configuration status.

    Returns:
        Dict with config status and recommendations
    """
    config = load_user_config() or {}
    env_key = os.environ.get("JUPITER_API_KEY")

    has_custom_key = bool(env_key or config.get("jupiter_api_key"))
    key_source = None
    if env_key:
        key_source = "environment"
    elif config.get("jupiter_api_key"):
        key_source = "local_config"

    # Get RPC status
    rpc_status = get_rpc_config_status()

    result = {
        "jupiter_api_key": {
            "configured": has_custom_key,
            "source": key_source,
        },
        "rpc": rpc_status,
        "wallet_configured": WALLET_FILE_ENCRYPTED.exists(),
        "config_dir": str(SLOPESNIPER_DIR),
    }

    # Add recommendations
    recommendations = []

    if not has_custom_key:
        recommendations.append(
            {
                "category": "Jupiter API",
                "message": "Using shared API key. For better performance, set your own Jupiter API key.",
                "benefits": [
                    "10x higher rate limits",
                    "Faster quote responses",
                    "Priority transaction routing",
                ],
                "how_to": "Run: slopesniper config --set-jupiter-key YOUR_KEY",
                "get_key": "Get a free key at: https://station.jup.ag/docs/apis/ultra-api",
            }
        )

    if not rpc_status["configured"]:
        recommendations.append(
            {
                "category": "RPC Endpoint",
                "message": "Using default RPC endpoint. For faster transactions, configure a custom RPC provider.",
                "providers": rpc_status["recommendation"]["providers"],
                "how_to": rpc_status["recommendation"]["how_to"],
            }
        )

    if recommendations:
        result["recommendations"] = recommendations

    return result


def list_wallet_backups() -> list[dict]:
    """
    List all wallet backups with their addresses and timestamps.

    Returns:
        List of dicts with backup info: timestamp, address, path
    """
    if not WALLET_BACKUP_DIR.exists():
        return []

    backups = []

    # Get all backup files (exclude .address files)
    backup_files = sorted(
        [f for f in WALLET_BACKUP_DIR.iterdir() if f.is_file() and not f.name.endswith(".address")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for backup_file in backup_files:
        # Parse timestamp from filename
        # Format: wallet.enc.YYYYMMDD_HHMMSS or wallet.json.YYYYMMDD_HHMMSS
        parts = backup_file.name.split(".")
        if len(parts) >= 3:
            timestamp = parts[-1]  # YYYYMMDD_HHMMSS
        else:
            timestamp = "unknown"

        # Try to read address from .address file
        addr_file = backup_file.parent / f"{backup_file.name}.address"
        address = None
        if addr_file.exists():
            try:
                address = addr_file.read_text().strip()
            except Exception:
                pass

        # Try to decrypt if no address file
        if not address and backup_file.name.startswith("wallet.enc"):
            try:
                encrypted = backup_file.read_bytes()
                decrypted = _decrypt_data(encrypted)
                data = json.loads(decrypted)
                address = data.get("address")
            except Exception:
                address = "(encrypted - cannot read)"

        # For legacy plaintext backups
        if not address and backup_file.name.startswith("wallet.json"):
            try:
                data = json.loads(backup_file.read_text())
                address = data.get("address")
            except Exception:
                address = "(corrupted)"

        backups.append(
            {
                "timestamp": timestamp,
                "address": address,
                "path": str(backup_file),
                "filename": backup_file.name,
            }
        )

    return backups


def export_backup_wallet(timestamp: str) -> dict | None:
    """
    Export a specific wallet backup by timestamp.

    Args:
        timestamp: The timestamp from list_wallet_backups (YYYYMMDD_HHMMSS)

    Returns:
        Dict with address and private_key, or None if not found/decryptable
    """
    if not WALLET_BACKUP_DIR.exists():
        return None

    # Find the backup file
    for backup_file in WALLET_BACKUP_DIR.iterdir():
        if not backup_file.is_file() or backup_file.name.endswith(".address"):
            continue

        if timestamp in backup_file.name:
            # Try to decrypt
            if backup_file.name.startswith("wallet.enc"):
                try:
                    encrypted = backup_file.read_bytes()
                    decrypted = _decrypt_data(encrypted)
                    data = json.loads(decrypted)
                    return {
                        "address": data.get("address"),
                        "private_key": data.get("private_key"),
                        "timestamp": timestamp,
                        "source": str(backup_file),
                    }
                except InvalidToken:
                    return {
                        "error": "Cannot decrypt - wallet from different machine",
                        "timestamp": timestamp,
                    }
                except Exception as e:
                    return {
                        "error": f"Failed to decrypt: {e}",
                        "timestamp": timestamp,
                    }

            # Legacy plaintext backup
            elif backup_file.name.startswith("wallet.json"):
                try:
                    data = json.loads(backup_file.read_text())
                    return {
                        "address": data.get("address"),
                        "private_key": data.get("private_key"),
                        "timestamp": timestamp,
                        "source": str(backup_file),
                    }
                except Exception as e:
                    return {
                        "error": f"Failed to read: {e}",
                        "timestamp": timestamp,
                    }

    return None


def get_policy_config() -> PolicyConfig:
    """
    Load policy configuration from environment.

    Environment variables:
    - POLICY_MAX_SLIPPAGE_BPS: Max slippage in basis points
    - POLICY_MAX_TRADE_USD: Max trade size in USD
    - POLICY_MIN_RUGCHECK_SCORE: Max acceptable rugcheck score
    - POLICY_REQUIRE_MINT_DISABLED: Require mint authority disabled
    - POLICY_REQUIRE_FREEZE_DISABLED: Require freeze authority disabled
    - POLICY_DENY_MINTS: Comma-separated list of blocked mints
    - POLICY_ALLOW_MINTS: Comma-separated list of allowed mints (whitelist)

    Returns:
        PolicyConfig with values from env or defaults
    """
    config = PolicyConfig()

    # Parse numeric values
    if max_slippage := os.environ.get("POLICY_MAX_SLIPPAGE_BPS"):
        config.MAX_SLIPPAGE_BPS = int(max_slippage)

    if max_trade := os.environ.get("POLICY_MAX_TRADE_USD"):
        config.MAX_TRADE_USD = float(max_trade)

    if min_score := os.environ.get("POLICY_MIN_RUGCHECK_SCORE"):
        config.MIN_RUGCHECK_SCORE = int(min_score)

    # Parse boolean values
    if require_mint := os.environ.get("POLICY_REQUIRE_MINT_DISABLED"):
        config.REQUIRE_MINT_DISABLED = require_mint.lower() in ("true", "1", "yes")

    if require_freeze := os.environ.get("POLICY_REQUIRE_FREEZE_DISABLED"):
        config.REQUIRE_FREEZE_DISABLED = require_freeze.lower() in ("true", "1", "yes")

    # Parse list values
    if deny_mints := os.environ.get("POLICY_DENY_MINTS"):
        config.DENY_MINTS = [m.strip() for m in deny_mints.split(",") if m.strip()]

    if allow_mints := os.environ.get("POLICY_ALLOW_MINTS"):
        config.ALLOW_MINTS = [m.strip() for m in allow_mints.split(",") if m.strip()]

    return config


def restore_backup_wallet(timestamp: str) -> dict:
    """
    Restore a wallet from backup, making it the active wallet.

    This exports the backup and imports it as the current wallet.
    The current wallet (if any) is backed up first.

    Args:
        timestamp: Backup timestamp (YYYYMMDD_HHMMSS format)

    Returns:
        Dict with success status, restored address, or error
    """
    # Get the backup
    backup = export_backup_wallet(timestamp)

    if not backup:
        return {
            "success": False,
            "error": f"Backup not found: {timestamp}",
            "hint": "Run 'slopesniper export --list-backups' to see available backups.",
        }

    if "error" in backup:
        return {
            "success": False,
            "error": backup["error"],
            "timestamp": timestamp,
        }

    # Import the backup as the current wallet
    private_key = backup.get("private_key")
    address = backup.get("address")

    if not private_key or not address:
        return {
            "success": False,
            "error": "Backup is missing private_key or address",
            "timestamp": timestamp,
        }

    # Save as current wallet (this backs up the existing wallet first)
    save_wallet(private_key, address)

    return {
        "success": True,
        "restored_address": address,
        "from_backup": timestamp,
        "message": f"Wallet restored from backup. Active wallet is now: {address}",
    }


def get_wallet_integrity_status() -> dict:
    """
    Comprehensive wallet integrity check.

    Diagnoses common issues:
    - Machine key status
    - Wallet file existence and readability
    - Encryption/decryption health
    - Backup availability
    - Environment vs local conflicts

    Returns:
        Dict with detailed diagnostic info
    """
    result = {
        "machine_key": {
            "exists": MACHINE_KEY_FILE.exists(),
            "readable": False,
            "valid": False,
        },
        "wallet_file": {
            "exists": WALLET_FILE_ENCRYPTED.exists(),
            "readable": False,
            "decryptable": False,
            "address": None,
        },
        "legacy_wallet": {
            "exists": WALLET_FILE.exists(),
        },
        "backups": {
            "count": 0,
            "available": [],
        },
        "environment": {
            "configured": bool(os.environ.get("SOLANA_PRIVATE_KEY")),
            "address": None,
        },
        "issues": [],
        "recommendations": [],
    }

    # Check machine key
    if MACHINE_KEY_FILE.exists():
        try:
            key_data = json.loads(MACHINE_KEY_FILE.read_text())
            if "salt" in key_data:
                result["machine_key"]["readable"] = True
                result["machine_key"]["valid"] = True
        except Exception as e:
            result["issues"].append(f"Machine key file corrupted: {e}")
            result["recommendations"].append(
                "Machine key is corrupted. Wallet may be unrecoverable. "
                "Check backups with 'slopesniper export --list-backups'."
            )

    # Check wallet file
    if WALLET_FILE_ENCRYPTED.exists():
        result["wallet_file"]["readable"] = True
        try:
            wallet = load_local_wallet(raise_on_decrypt_error=True)
            if wallet:
                result["wallet_file"]["decryptable"] = True
                result["wallet_file"]["address"] = wallet.get("address")
        except ValueError as e:
            result["issues"].append(str(e))
            result["recommendations"].append(
                "Wallet file exists but cannot be decrypted. "
                "This usually means the wallet was created on a different machine. "
                "Check backups or import your private key again."
            )
        except Exception as e:
            result["issues"].append(f"Wallet read error: {e}")

    # Check legacy wallet
    if WALLET_FILE.exists():
        result["issues"].append("Legacy plaintext wallet.json found - should be migrated")
        result["recommendations"].append(
            "Run 'slopesniper status' to automatically migrate the plaintext wallet."
        )

    # Check backups
    backups = list_wallet_backups()
    result["backups"]["count"] = len(backups)
    result["backups"]["available"] = [
        {"timestamp": b["timestamp"], "address": b["address"]}
        for b in backups[:5]  # Show last 5
    ]

    # Check environment
    env_key = os.environ.get("SOLANA_PRIVATE_KEY")
    if env_key:
        keypair = _parse_private_key(env_key)
        if keypair:
            result["environment"]["address"] = str(keypair.pubkey())

    # Check for conflicts
    if result["environment"]["configured"] and result["wallet_file"]["decryptable"]:
        if result["environment"]["address"] != result["wallet_file"]["address"]:
            result["issues"].append(
                f"WALLET MISMATCH: Environment ({result['environment']['address'][:8]}...) "
                f"differs from local file ({result['wallet_file']['address'][:8]}...)"
            )
            result["recommendations"].append(
                "Environment variable takes priority. To use local wallet, unset SOLANA_PRIVATE_KEY. "
                "To sync, run 'slopesniper setup --import-key' with desired key."
            )

    # Overall health
    if not result["issues"]:
        result["health"] = "ok"
    elif any("MISMATCH" in issue for issue in result["issues"]):
        result["health"] = "warning"
    else:
        result["health"] = "error"

    return result


def get_wallet_fingerprint() -> str | None:
    """
    Get a short fingerprint of the current active wallet.

    Useful for detecting wallet changes between processes.

    Returns:
        Short hash of wallet address, or None if no wallet
    """
    sync_status = get_wallet_sync_status()
    address = sync_status.get("active_address")
    if not address:
        return None

    # Create a short fingerprint
    return hashlib.sha256(address.encode()).hexdigest()[:12]
