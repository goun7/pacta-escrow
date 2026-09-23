"""Unit tests for Pacta models and data schemas."""

import pytest
from pacta.models import (
    EscrowJob,
    EscrowPolicy,
    EscrowStatus,
    VerificationTier,
    TamgaExecutionReceipt,
    ZkTLSCertificate,
)


def test_escrow_policy_defaults():
    policy = EscrowPolicy()
    assert policy.timeout_ms == 5000
    assert policy.verification_mode == VerificationTier.TIER1_SYNTACTIC
    assert policy.fee_rate_basis_points == 75
    from decimal import Decimal
    assert policy.dispute_bond_ratio == Decimal("0.20")


def test_escrow_policy_schema_hash():
    schema = {"type": "object", "properties": {"signal": {"type": "string"}}}
    policy = EscrowPolicy(required_schema=schema)
    h = policy.compute_schema_hash()
    assert h is not None
    assert len(h) == 64


def test_escrow_job_fee_and_net_calculations():
    job = EscrowJob(
        buyer_address="0xBuyer",
        seller_address="0xSeller",
        amount_usdc=100.0,
        policy=EscrowPolicy(fee_rate_basis_points=75),
    )
    assert job.amount_usdc == 100.0
    assert job.calculate_fee() == 0.75
    assert job.net_seller_amount() == 99.25


def test_escrow_job_invalid_negative_amount():
    with pytest.raises(ValueError):
        EscrowJob(
            buyer_address="0xBuyer",
            seller_address="0xSeller",
            amount_usdc=-10.0,
        )


def test_tamga_receipt_integrity():
    receipt = TamgaExecutionReceipt(
        job_id="job-1",
        program_hash="0xprog",
        input_commitment="0xinput",
        output_hash="0xout",
        wasi_trace_root="0xtrace",
        instruction_count=4500,
        timestamp_epoch=1789823000,
        signature="0xsig"
    )
    assert receipt.verify_tamga_integrity() is True

    corrupt = TamgaExecutionReceipt(
        job_id="job-2",
        program_hash="",
        input_commitment="0xinput",
        output_hash="0xout",
        wasi_trace_root="0xtrace",
        instruction_count=0,
        timestamp_epoch=1789823000,
        signature=""
    )
    assert corrupt.verify_tamga_integrity() is False


def test_zktls_certificate_integrity():
    cert = ZkTLSCertificate(
        session_id="sess-123",
        server_name="api.binance.com",
        data_hash="0xhash",
        zk_proof_snark="a" * 64,
        attestation_key="0xkey"
    )
    assert cert.verify_certificate() is True
