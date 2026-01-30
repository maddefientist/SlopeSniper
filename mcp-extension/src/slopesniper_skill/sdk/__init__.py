"""
SlopeSniper SDK - Multi-source Solana Token Data

Bundled SDK for Solana token operations:
- JupiterUltraClient: Swap quotes and execution
- JupiterDataClient: Price and token data
- RugCheckClient: Token safety analysis
- DexScreenerClient: Trending tokens, new pairs, volume data
- PumpFunClient: Pump.fun graduated/new tokens
- PumpPortalDeployClient: Token deployment on Pump.fun
- BagsClient: Token deployment on Bags.fm
"""

__version__ = "0.3.41"

from .bags_client import BagsClient, BagsDeployClient, BagsTokenMetadata, BagsDeployResult
from .dexscreener_client import DexScreenerClient
from .jupiter_data_client import JupiterDataClient
from .jupiter_ultra_client import JupiterUltraClient
from .pumpfun_client import PumpFunClient
from .pumpportal_deploy import (
    PumpPortalDeployClient,
    PumpDeployClient,
    TokenMetadata,
    DeployResult,
)
from .rugcheck_client import RugCheckClient
from .utils import Utils

__all__ = [
    "__version__",
    "JupiterUltraClient",
    "JupiterDataClient",
    "RugCheckClient",
    "DexScreenerClient",
    "PumpFunClient",
    # Deployment clients
    "PumpPortalDeployClient",
    "PumpDeployClient",
    "TokenMetadata",
    "DeployResult",
    "BagsClient",
    "BagsDeployClient",
    "BagsTokenMetadata",
    "BagsDeployResult",
    "Utils",
]
