"""
Pacta Protocol Configuration (Production-Grade Environment Settings)
Loads configuration from environment variables with fallback defaults.
Zero hardcoding of keys or secrets.
"""

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PactaSettings:
    """Immutable production runtime settings."""
    network: str = os.getenv("PACTA_NETWORK", "base")
    rpc_url: str = os.getenv("PACTA_RPC_URL", "https://mainnet.base.org")
    vault_address: str = os.getenv("PACTA_VAULT_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    usdc_token_address: str = os.getenv("PACTA_USDC_ADDRESS", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    protocol_treasury: str = os.getenv("PACTA_TREASURY_ADDRESS", "0xc5ad63e263ab5f3f722d3fa1c71bf73d73dd11ae")
    arbitrator_oracle: str = os.getenv("PACTA_ARBITRATOR_ORACLE", "0xPactaArbitrationOracle_BaseL2")
    default_timeout_ms: int = int(os.getenv("PACTA_DEFAULT_TIMEOUT_MS", "5000"))
    protocol_fee_bps: int = int(os.getenv("PACTA_PROTOCOL_FEE_BPS", "75"))  # 0.75%
    dispute_bond_bps: int = int(os.getenv("PACTA_DISPUTE_BOND_BPS", "2000"))  # 20%
    host: str = os.getenv("PACTA_HOST", "0.0.0.0")
    port: int = int(os.getenv("PACTA_PORT", "8090"))
    log_level: str = os.getenv("PACTA_LOG_LEVEL", "INFO")

    @property
    def protocol_fee_rate(self) -> Decimal:
        return Decimal(str(self.protocol_fee_bps)) / Decimal("10000")

    @property
    def dispute_bond_rate(self) -> Decimal:
        return Decimal(str(self.dispute_bond_bps)) / Decimal("10000")


# Singleton instance
settings = PactaSettings()
