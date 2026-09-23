"""
Pacta x402 Protocol Adapter
Implements HTTP 402 Payment Required headers with extended Pacta Escrow capabilities.
"""

from typing import Dict, Optional, Tuple
from pacta.models import EscrowJob, EscrowPolicy


class X402ProtocolHandler:
    """
    Constructs and parses extended x402 HTTP challenge & authorization headers.
    Enforces escrow commitment before delivery.
    """

    HEADER_VERSION = "X-Pacta-Version"
    HEADER_ESCROW_ADDRESS = "X-Pacta-Escrow-Address"
    HEADER_JOB_ID = "X-Pacta-Job-Id"
    HEADER_PRICE = "X-Pacta-Price"
    HEADER_DEPOSIT_TOKEN = "X-Pacta-Deposit-Token"
    HEADER_TIMEOUT_MS = "X-Pacta-Timeout-Ms"
    HEADER_SCHEMA_HASH = "X-Pacta-Required-Schema-Hash"
    HEADER_VERIFICATION_MODE = "X-Pacta-Verification-Mode"
    HEADER_DISPUTE_WINDOW = "X-Pacta-Dispute-Window-Sec"

    @classmethod
    def create_challenge_headers(
        cls,
        job: EscrowJob,
        vault_address: str = "0xPactaSmartVaultBaseL2_2026"
    ) -> Dict[str, str]:
        """Builds HTTP 402 response headers requesting escrow lock."""
        headers = {
            cls.HEADER_VERSION: "2026.1",
            cls.HEADER_ESCROW_ADDRESS: vault_address,
            cls.HEADER_JOB_ID: job.job_id,
            cls.HEADER_PRICE: f"{job.amount_usdc:.6f} USDC",
            cls.HEADER_DEPOSIT_TOKEN: job.deposit_token,
            cls.HEADER_TIMEOUT_MS: str(job.policy.timeout_ms),
            cls.HEADER_VERIFICATION_MODE: job.policy.verification_mode.value,
            cls.HEADER_DISPUTE_WINDOW: str(job.policy.dispute_window_sec),
        }
        schema_hash = job.policy.compute_schema_hash()
        if schema_hash:
            headers[cls.HEADER_SCHEMA_HASH] = schema_hash

        return headers

    @classmethod
    def create_authorization_header(cls, job_id: str, tx_hash: str) -> str:
        """Constructs Authorization header for buyer retry."""
        return f"PactaEscrow TxHash={tx_hash}, JobId={job_id}"

    @classmethod
    def parse_authorization_header(cls, auth_header: str) -> Optional[Dict[str, str]]:
        """
        Parses `Authorization: PactaEscrow TxHash=0x..., JobId=...`
        """
        if not auth_header.startswith("PactaEscrow "):
            return None

        tokens = auth_header[len("PactaEscrow "):].split(",")
        params: Dict[str, str] = {}
        for t in tokens:
            t = t.strip()
            if "=" in t:
                k, v = t.split("=", 1)
                params[k.strip()] = v.strip()

        if "JobId" in params and "TxHash" in params:
            return params
        return None
