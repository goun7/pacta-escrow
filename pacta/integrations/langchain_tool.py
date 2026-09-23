"""
LangChain / LangGraph Tool for Pacta Escrow
"""

from typing import Any, Dict
from pacta.client import PactaEscrowClient
from pacta.models import EscrowPolicy


class PactaEscrowTool:
    """
    LangChain-compatible tool enabling autonomous agents to execute escrowed payments.
    """
    name: str = "pacta_escrow_payment"
    description: str = (
        "Executes a trustless delivery-versus-payment transaction with another AI agent or API. "
        "Locks funds until output data satisfies schema invariants and SLA limits."
    )

    def __init__(self, client: PactaEscrowClient):
        self.client = client

    def _run(
        self,
        seller_address: str,
        amount_usdc: float,
        output_payload: Dict[str, Any],
        timeout_ms: int = 5000
    ) -> str:
        policy = EscrowPolicy(timeout_ms=timeout_ms)
        resp = self.client.call_with_escrow(
            seller_address=seller_address,
            amount=amount_usdc,
            output_data=output_payload,
            policy=policy
        )
        if resp.success:
            return f"SUCCESS: Escrow {resp.job.job_id} settled to {seller_address} (Tx: {resp.escrow_settle_tx})"
        return f"FAILED: Escrow {resp.job.job_id} refunded to buyer. Reason: {resp.error_message}"
