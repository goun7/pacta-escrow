"""
Coinbase AgentKit Action Provider for Pacta Escrow
Allows CDP/AgentKit agents to execute conditional x402 escrow payments natively.
"""

from typing import Any, Dict
from pacta.client import PactaEscrowClient
from pacta.models import EscrowPolicy, VerificationTier


class PactaEscrowActionProvider:
    """
    Coinbase AgentKit Action Provider.
    Exposes Pacta's trustless escrow actions to CDP Agent wallets.
    """

    def __init__(self, client: PactaEscrowClient):
        self.client = client

    def get_actions(self) -> Dict[str, Any]:
        return {
            "pacta_pay_with_escrow": self.pay_with_escrow,
            "pacta_raise_dispute": self.raise_dispute,
        }

    def pay_with_escrow(
        self,
        seller_address: str,
        amount_usdc: float,
        output_payload: Dict[str, Any],
        timeout_ms: int = 5000,
        verify_tamga: bool = False
    ) -> Dict[str, Any]:
        """Action for CDP agents to safely buy data or services with escrow."""
        mode = VerificationTier.TIER2_CRYPTOGRAPHIC if verify_tamga else VerificationTier.TIER1_SYNTACTIC
        policy = EscrowPolicy(
            timeout_ms=timeout_ms,
            verification_mode=mode
        )

        response = self.client.call_with_escrow(
            seller_address=seller_address,
            amount=amount_usdc,
            output_data=output_payload,
            policy=policy
        )

        return {
            "success": response.success,
            "job_id": response.job.job_id,
            "settlement_tx": response.escrow_settle_tx,
            "error": response.error_message,
            "status": response.job.status.value
        }

    def raise_dispute(
        self,
        job_id: str,
        reason: str,
        evidence_hash: str
    ) -> Dict[str, Any]:
        """Action for CDP agents to dispute bad output and invoke arbitration."""
        claim = self.client.dispute(
            job_id=job_id,
            reason=reason,
            evidence_hash=evidence_hash
        )
        return {
            "dispute_id": claim.dispute_id,
            "job_id": claim.job_id,
            "bond_amount_usdc": claim.bond_amount_usdc,
            "status": "ARBITRATION_IN_PROGRESS"
        }
