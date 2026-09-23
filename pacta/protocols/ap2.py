"""
Pacta Google AP2 (Agent Payments Protocol) Adapter
Extends FIDO/AP2 purchase mandates into conditional cryptographic escrow covenants.
"""

import time
import hashlib
import hmac
from typing import Optional
from pydantic import BaseModel, Field
from pacta.models import EscrowJob, VerificationTier


class AP2MandateToken(BaseModel):
    """Google AP2 standard user/agent authorization mandate token."""
    mandate_id: str
    principal_authority: str       # User or sovereign agent identifier
    delegated_agent_address: str  # The purchasing agent wallet
    merchant_scope: str           # Allowed merchant domain / address
    max_amount_usdc: float
    enforce_escrow: bool = True
    min_verification_tier: VerificationTier = VerificationTier.TIER1_SYNTACTIC
    expires_at_epoch: int
    mandate_signature: str

    def is_valid(self, requested_amount: float, merchant: str) -> bool:
        """Verifies if mandate covers the requested transaction parameters."""
        now = int(time.time())
        if now > self.expires_at_epoch:
            return False
        if requested_amount > self.max_amount_usdc:
            return False
        if self.merchant_scope != "*" and self.merchant_scope != merchant:
            return False
        return bool(self.mandate_signature)


class AP2EscrowCovenant(BaseModel):
    """Binds an AP2 mandate to an active on-chain Pacta escrow."""
    covenant_id: str
    mandate_id: str
    job_id: str
    covenant_hash: str
    locked_amount_usdc: float
    created_at_epoch: int = Field(default_factory=lambda: int(time.time()))


class AP2ProtocolHandler:
    """Handles translation between AP2 mandate workflows and Pacta Escrow vaults."""

    @classmethod
    def generate_covenant(
        cls,
        mandate: AP2MandateToken,
        job: EscrowJob,
        secret_key: str = "pacta-ap2-secret-2026"
    ) -> Optional[AP2EscrowCovenant]:
        """Validates mandate and issues binding AP2 escrow covenant."""
        if not mandate.is_valid(job.amount_usdc, job.seller_address):
            return None

        content = f"{mandate.mandate_id}:{job.job_id}:{job.amount_usdc}:{job.seller_address}"
        cov_hash = hmac.new(secret_key.encode(), content.encode(), hashlib.sha256).hexdigest()

        return AP2EscrowCovenant(
            covenant_id=f"cov-{job.job_id[:8]}",
            mandate_id=mandate.mandate_id,
            job_id=job.job_id,
            covenant_hash=cov_hash,
            locked_amount_usdc=job.amount_usdc,
        )
