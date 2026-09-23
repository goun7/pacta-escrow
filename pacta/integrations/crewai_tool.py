"""
CrewAI Tool for Pacta Escrow
"""

from typing import Any, Dict
from pacta.client import PactaEscrowClient
from pacta.models import EscrowPolicy


class CrewAIEscrowTool:
    """
    CrewAI-compatible tool for inter-agent budget and service settlements.
    """
    name: str = "EscrowPaymentTool"
    description: str = (
        "Delegates work to another agent or sub-crew under conditional escrow lock. "
        "Funds release only upon verified task completion."
    )

    def __init__(self, client: PactaEscrowClient):
        self.client = client

    def run(
        self,
        peer_agent_address: str,
        task_bounty_usdc: float,
        result_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        resp = self.client.call_with_escrow(
            seller_address=peer_agent_address,
            amount=task_bounty_usdc,
            output_data=result_payload,
            policy=EscrowPolicy(timeout_ms=10000)
        )
        return {
            "job_id": resp.job.job_id,
            "status": resp.job.status.value,
            "success": resp.success,
            "tx_hash": resp.escrow_settle_tx,
            "error": resp.error_message
        }
