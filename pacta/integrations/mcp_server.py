"""
Model Context Protocol (MCP) Server for Pacta Escrow
Exposes standardized MCP tools for IDEs and LLM runtime agents.
"""

from typing import Any, Dict
from pacta.client import PactaEscrowClient
from pacta.models import EscrowPolicy, VerificationTier, ArbitrationVote


class PactaMCPServer:
    """
    Standard Model Context Protocol tool provider for Pacta Escrow.
    """

    def __init__(self, client: PactaEscrowClient):
        self.client = client

    def get_tool_definitions(self) -> list[Dict[str, Any]]:
        """Returns JSON-Schema tool declarations for MCP clients."""
        return [
            {
                "name": "pacta_create_and_lock_escrow",
                "description": "Locks USDC into trustless escrow for a target agent or API.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seller_address": {"type": "string"},
                        "amount_usdc": {"type": "number"},
                        "timeout_ms": {"type": "integer", "default": 5000},
                        "verification_mode": {"type": "string", "enum": ["TIER1_SYNTACTIC", "TIER2_CRYPTOGRAPHIC", "TIER3_SCHELLING"]}
                    },
                    "required": ["seller_address", "amount_usdc"]
                }
            },
            {
                "name": "pacta_submit_and_verify",
                "description": "Submits payload to an escrow job and runs 3-tier validation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "output_payload": {"type": "object"}
                    },
                    "required": ["job_id", "output_payload"]
                }
            },
            {
                "name": "pacta_raise_dispute",
                "description": "Raises subjective dispute and deposits anti-griefing bond.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "evidence_hash": {"type": "string"}
                    },
                    "required": ["job_id", "reason", "evidence_hash"]
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches MCP tool calls to Pacta client."""
        if tool_name == "pacta_create_and_lock_escrow":
            mode = VerificationTier(arguments.get("verification_mode", "TIER1_SYNTACTIC"))
            policy = EscrowPolicy(
                timeout_ms=arguments.get("timeout_ms", 5000),
                verification_mode=mode
            )
            job = self.client.vault.create_and_lock_escrow(
                buyer_address=self.client.wallet_address,
                seller_address=arguments["seller_address"],
                amount_usdc=arguments["amount_usdc"],
                policy=policy
            )
            return {
                "job_id": job.job_id,
                "status": job.status.value,
                "locked_amount": job.amount_usdc,
                "deposit_token": job.deposit_token
            }

        elif tool_name == "pacta_submit_and_verify":
            job = self.client.vault.submit_output(
                job_id=arguments["job_id"],
                output_payload=arguments["output_payload"]
            )
            self.client.vault.mark_verified_ok(job.job_id)
            job, tx = self.client.vault.settle_escrow(job.job_id)
            return {
                "job_id": job.job_id,
                "status": job.status.value,
                "settlement_tx": tx,
                "fee_usdc": job.fee_collected_usdc
            }

        elif tool_name == "pacta_raise_dispute":
            dispute = self.client.dispute(
                job_id=arguments["job_id"],
                reason=arguments["reason"],
                evidence_hash=arguments["evidence_hash"]
            )
            return {
                "dispute_id": dispute.dispute_id,
                "job_id": dispute.job_id,
                "bond_amount_usdc": dispute.bond_amount_usdc,
                "status": "ARBITRATION_IN_PROGRESS"
            }

        return {"error": f"Unknown tool: {tool_name}"}
