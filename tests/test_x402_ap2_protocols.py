"""Unit tests for x402 HTTP headers and Google AP2 Mandates."""

import time
from pacta.models import EscrowJob, EscrowPolicy, VerificationTier
from pacta.protocols.x402 import X402ProtocolHandler
from pacta.protocols.ap2 import AP2MandateToken, AP2ProtocolHandler


def test_x402_challenge_and_auth_headers():
    job = EscrowJob(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=15.0,
        policy=EscrowPolicy(timeout_ms=3500)
    )

    headers = X402ProtocolHandler.create_challenge_headers(job)
    assert headers["X-Pacta-Job-Id"] == job.job_id
    assert headers["X-Pacta-Price"] == "15.000000 USDC"
    assert headers["X-Pacta-Timeout-Ms"] == "3500"

    auth_header = X402ProtocolHandler.create_authorization_header(job.job_id, "0xtx123")
    assert "PactaEscrow" in auth_header

    parsed = X402ProtocolHandler.parse_authorization_header(auth_header)
    assert parsed is not None
    assert parsed["JobId"] == job.job_id
    assert parsed["TxHash"] == "0xtx123"


def test_ap2_mandate_token_validation_and_covenant():
    mandate = AP2MandateToken(
        mandate_id="mandate-99",
        principal_authority="user@corp.internal",
        delegated_agent_address="0xa2829f21feba3bc84f5ab430301d9c86a7794e",
        merchant_scope="0xf051d357327197d7cba0d55df1d311f113d9ae",
        max_amount_usdc=100.0,
        expires_at_epoch=int(time.time()) + 3600,
        mandate_signature="0x626668025320af3bceab39308dfe5b6f6ee3de"
    )

    job = EscrowJob(
        buyer_address="0xa2829f21feba3bc84f5ab430301d9c86a7794e",
        seller_address="0xf051d357327197d7cba0d55df1d311f113d9ae",
        amount_usdc=50.0
    )

    covenant = AP2ProtocolHandler.generate_covenant(mandate, job)
    assert covenant is not None
    assert covenant.mandate_id == "mandate-99"
    assert covenant.locked_amount_usdc == 50.0

    # Over-budget mandate attempt
    job_expensive = EscrowJob(
        buyer_address="0xa2829f21feba3bc84f5ab430301d9c86a7794e",
        seller_address="0xf051d357327197d7cba0d55df1d311f113d9ae",
        amount_usdc=150.0  # Exceeds max 100.0
    )
    assert AP2ProtocolHandler.generate_covenant(mandate, job_expensive) is None
