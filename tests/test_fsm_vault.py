"""Unit tests for FSM transitions and Vault Solvency Invariants."""

import pytest
from pacta.models import EscrowStatus, EscrowPolicy
from pacta.core.fsm import EscrowFSM, InvalidStateTransitionError
from pacta.core.vault import PactaEscrowVault, InvariantViolationError


def test_fsm_valid_transitions():
    assert EscrowFSM.can_transition(EscrowStatus.INITIALIZED, EscrowStatus.ESCROW_LOCKED) is True
    assert EscrowFSM.can_transition(EscrowStatus.ESCROW_LOCKED, EscrowStatus.OUTPUT_SUBMITTED) is True
    assert EscrowFSM.can_transition(EscrowStatus.OUTPUT_SUBMITTED, EscrowStatus.VERIFIED_OK) is True
    assert EscrowFSM.can_transition(EscrowStatus.VERIFIED_OK, EscrowStatus.SETTLED) is True


def test_fsm_invalid_transition_raises():
    with pytest.raises(InvalidStateTransitionError):
        EscrowFSM.transition(EscrowStatus.INITIALIZED, EscrowStatus.SETTLED)


def test_vault_create_lock_and_solvency():
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=50.0
    )
    assert job.status == EscrowStatus.ESCROW_LOCKED
    assert vault.ledger_balances[job.deposit_token] == 50.0
    assert vault.check_solvency_invariant() is True


def test_vault_settlement_flow():
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=10.0
    )
    vault.submit_output(job.job_id, {"result": "data"})
    vault.mark_verified_ok(job.job_id)
    settled_job, tx = vault.settle_escrow(job.job_id)

    assert settled_job.status == EscrowStatus.SETTLED
    from decimal import Decimal
    assert settled_job.fee_collected_usdc == Decimal("0.075000")
    assert vault.total_protocol_revenue_usdc == Decimal("0.075000")
    assert vault.check_solvency_invariant() is True


def test_vault_timeout_refund():
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=20.0
    )
    # AT-165-düzeltmesi: refund-artık-GERÇEK-SLA-aşımı-istiyor. İş-kilitli-
    # anını-geçmişe-taşıyarak-gerçek-zaman-aşımı-simüle-et.
    job.locked_at_epoch_ms -= 10 * 60_000   # 10-dakika-önce ( SLA-aşımı)
    refunded_job = vault.refund_timeout(job.job_id)
    assert refunded_job.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
    assert vault.ledger_balances[refunded_job.deposit_token] == 0.0
    assert vault.check_solvency_invariant() is True

    # KARŞIT: zamanında-teslim-iade-edilemez ( SLA-aşımı-YOK)
    job2 = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32", seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0", amount_usdc=5.0)
    try:
        vault.refund_timeout(job2.job_id)
        raise AssertionError("zamanında-teslim-iade-edildi ( HATA)")
    except Exception as e:
        assert "within timeout SLA" in str(e)


def test_vault_solvency_invariant_enforcement():
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address="0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32",
        seller_address="0x2fe8de9732027146046b7f4603994c5a5f5cb0",
        amount_usdc=100.0
    )
    # Manually tamper with balance to simulate deficit
    vault.ledger_balances[job.deposit_token] = 50.0
    with pytest.raises(InvariantViolationError):
        vault.check_solvency_invariant()
