"""Unit tests for PactaEscrowClient and CLI commands."""

from pacta.client import PactaEscrowClient
from pacta.cli import run_demo
from pacta.models import EscrowPolicy, VerificationTier


def test_client_call_with_escrow_failure():
    client = PactaEscrowClient()
    policy = EscrowPolicy(max_latency_ms=50)

    # Simulated latency 200ms will breach 50ms SLA
    resp = client.call_with_escrow(
        seller_address="0xSlowSeller",
        amount=10.0,
        output_data={"fast": False},
        policy=policy,
        simulated_latency_ms=200
    )
    assert resp.success is False
    assert resp.job.status.value == "AUTO_REFUNDED_TIMEOUT"
    assert "SLA breach" in resp.error_message


def test_client_dispute_flow():
    client = PactaEscrowClient()
    job = client.vault.create_and_lock_escrow("0xBuyer", "0xSeller", 30.0)
    client.vault.submit_output(job.job_id, {"broken": True})

    dispute = client.dispute(
        job_id=job.job_id,
        reason="Model returned invalid token sequence",
        evidence_hash="0xhash123"
    )
    assert dispute.bond_amount_usdc == 6.0
    assert client.vault.jobs[job.job_id].status.value == "ARBITRATION_IN_PROGRESS"


def test_cli_demo_execution(capsys):
    run_demo()
    captured = capsys.readouterr()
    assert "PACTA ESCROW PROTOCOL" in captured.out
    assert "PASSED [100% SOLVENT]" in captured.out
