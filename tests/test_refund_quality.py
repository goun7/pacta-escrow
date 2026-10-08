"""refund_quality_failure kalite-başarısızlığı iade testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: in-memory vault + sentetik adresler.
"""
import os

import pytest

from pacta.core.vault import (  # noqa: E402
    PactaEscrowVault,
    EscrowNotFoundError,
    EscrowAuthorizationError,
)
from pacta.models import EscrowStatus  # noqa: E402
from decimal import Decimal  # noqa: E402

BUYER = "0x59b66b9e6ffdd9b1A3D7d9C7f8B2c1a4E5f6A7b8"
SELLER = "0x2fe8de97320271a5E3a0BfA9f1c2D3e4F5a6B7c8"
OTHER = "0x9999888877776666555544443333222211110000"


@pytest.fixture
def vault_with_job():
    v = PactaEscrowVault()
    job = v.create_and_lock_escrow(
        buyer_address=BUYER, seller_address=SELLER, amount_usdc=50.0)
    return v, job


def _refund(vault_with_job, **kw):
    v, job = vault_with_job
    return v.refund_quality_failure(job.job_id, **kw)


# -- temel iade ---------------------------------------------------------------------------

def test_refund_changes_status(vault_with_job):
    v, job = vault_with_job
    j = v.refund_quality_failure(job.job_id, caller_address=BUYER)
    assert j.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT


def test_refund_returns_job(vault_with_job):
    j = _refund(vault_with_job, caller_address=BUYER)
    assert j is not None
    assert hasattr(j, "amount_usdc")


def test_refund_same_job_object(vault_with_job):
    v, job = vault_with_job
    j = v.refund_quality_failure(job.job_id, caller_address=SELLER)
    assert j.job_id == job.job_id


def test_refund_decrements_ledger(vault_with_job):
    v, job = vault_with_job
    before = v.ledger_balances[job.deposit_token]
    v.refund_quality_failure(job.job_id, caller_address=BUYER)
    after = v.ledger_balances[job.deposit_token]
    assert after == before - job.amount_usdc


def test_refund_sets_settled_at(vault_with_job):
    j = _refund(vault_with_job, caller_address=BUYER)
    assert j.settled_at_epoch_ms is not None
    assert j.settled_at_epoch_ms > 0


def test_solvency_holds_after_refund(vault_with_job):
    v, job = vault_with_job
    v.refund_quality_failure(job.job_id, caller_address=BUYER)
    assert v.check_solvency_invariant() is True or None


# -- rol-kontrolü (AT-180 / AT-184) ---------------------------------------------------------------------------

def test_buyer_can_refund(vault_with_job):
    j = _refund(vault_with_job, caller_address=BUYER)
    assert j.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT


def test_seller_can_refund(vault_with_job):
    j = _refund(vault_with_job, caller_address=SELLER)
    assert j.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT


def test_other_cannot_refund(vault_with_job):
    with pytest.raises(EscrowAuthorizationError):
        _refund(vault_with_job, caller_address=OTHER)


def test_role_check_fail_closed_message(vault_with_job):
    with pytest.raises(EscrowAuthorizationError) as e:
        _refund(vault_with_job, caller_address=OTHER)
    assert "role check" in str(e.value) or "neither buyer nor seller" in str(e.value)


def test_missing_caller_warns(vault_with_job, recwarn):
    """caller=None → uyarı ama iade olur (PACTA_REQUIRE_CALLER_ROLE yoksa)."""
    os.environ.pop("PACTA_REQUIRE_CALLER_ROLE", None)
    j = _refund(vault_with_job)
    assert j.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
    assert any("caller-missing" in str(w.message) for w in recwarn.list)


def test_missing_caller_required_raises(vault_with_job, monkeypatch):
    monkeypatch.setenv("PACTA_REQUIRE_CALLER_ROLE", "1")
    with pytest.raises(EscrowNotFoundError) as e:
        _refund(vault_with_job)
    assert "caller-required" in str(e.value)


def test_missing_caller_required_any_value(vault_with_job, monkeypatch):
    """PACTA_REQUIRE_CALLER_ROLE herhangi bir değerde zorunlu."""
    monkeypatch.setenv("PACTA_REQUIRE_CALLER_ROLE", "false")
    with pytest.raises(EscrowNotFoundError):
        _refund(vault_with_job)


def test_caller_case_insensitive(vault_with_job):
    j = _refund(vault_with_job, caller_address=BUYER.upper())
    assert j.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT


def test_other_case_insensitive_rejected(vault_with_job):
    with pytest.raises(EscrowAuthorizationError):
        _refund(vault_with_job, caller_address=OTHER.upper())


def test_empty_caller_rejected(vault_with_job):
    """Boş string — buyer/seller ile eşleşmiyor."""
    with pytest.raises(EscrowAuthorizationError):
        _refund(vault_with_job, caller_address="")


# -- job bulunamama ---------------------------------------------------------------------------

def test_missing_job_raises(vault_with_job):
    v, _ = vault_with_job
    with pytest.raises(EscrowNotFoundError):
        v.refund_quality_failure("yok-id", caller_address=BUYER)


def test_missing_job_message(vault_with_job):
    v, _ = vault_with_job
    with pytest.raises(EscrowNotFoundError) as e:
        v.refund_quality_failure("abc-123", caller_address=BUYER)
    assert "abc-123" in str(e.value)


def test_missing_job_role_checked_second(vault_with_job):
    """Job önce kontrol edilir — geçersiz caller bile olsa job-yok öncelikli."""
    v, _ = vault_with_job
    with pytest.raises(EscrowNotFoundError):
        v.refund_quality_failure("yok", caller_address=OTHER)


# -- iade sonrası durum ---------------------------------------------------------------------------

def test_double_refund_rejected(vault_with_job):
    """AUTO_REFUNDED durumundan tekrar iade — FSM geçiş yok."""
    v, job = vault_with_job
    v.refund_quality_failure(job.job_id, caller_address=BUYER)
    with pytest.raises(Exception):
        v.refund_quality_failure(job.job_id, caller_address=BUYER)


def test_refund_amount_preserved(vault_with_job):
    v, job = vault_with_job
    amt = job.amount_usdc
    j = v.refund_quality_failure(job.job_id, caller_address=BUYER)
    assert j.amount_usdc == amt


# -- farklı tutarlar ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount", [0.01, 1.0, 50.0, 1000.0])
def test_various_amounts(amount):
    v = PactaEscrowVault()
    job = v.create_and_lock_escrow(
        buyer_address=BUYER, seller_address=SELLER, amount_usdc=amount)
    before = v.ledger_balances[job.deposit_token]
    j = v.refund_quality_failure(job.job_id, caller_address=BUYER)
    assert v.ledger_balances[j.deposit_token] == before - Decimal(str(amount))


def test_multiple_jobs_independent():
    v = PactaEscrowVault()
    j1 = v.create_and_lock_escrow(buyer_address=BUYER, seller_address=SELLER,
                                  amount_usdc=10.0)
    j2 = v.create_and_lock_escrow(buyer_address=BUYER, seller_address=SELLER,
                                  amount_usdc=20.0)
    v.refund_quality_failure(j1.job_id, caller_address=BUYER)
    assert v.ledger_balances[j2.deposit_token] >= j2.amount_usdc
