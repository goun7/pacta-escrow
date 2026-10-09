"""PactaEscrowVault.settle_escrow dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: yerel yerleşik adresler + sahte zaman.
"""
import time

import pytest

from pacta.core.vault import PactaEscrowVault, EscrowNotFoundError
from pacta.models import EscrowJob
from pacta.models import EscrowStatus


BUYER = "0x59b66b9e6ffdd9ba6f0d11b4d24b8e1e3e4e5a9f"
SELLER = "0x2fe8d12b7a4c1e9f6b3d8a2c5e7b9f1d3a5c8e6b"


@pytest.fixture
def vault():
    return PactaEscrowVault()


def _lock(vault, buyer=BUYER, seller=SELLER, amount=50.0):
    return vault.create_and_lock_escrow(
        buyer_address=buyer, seller_address=seller, amount_usdc=amount)


def _settled(vault, job_id, caller=BUYER):
    vault.submit_output(job_id, {"delivery": "ok"})
    vault.mark_verified_ok(job_id)
    return vault.settle_escrow(job_id, caller_address=caller)[0]


# -- temel akış ---------------------------------------------------------------------------

def test_settle_returns_job(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id)
    assert isinstance(r, EscrowJob)


def test_settle_sets_terminal_status(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id)
    assert r.status == EscrowStatus.SETTLED


def test_settle_records_timestamp(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id)
    assert r.settled_at_epoch_ms is not None


def test_settle_tx_hash(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id)
    assert r.settlement_tx is not None
    assert r.settlement_tx.startswith("0x")


# -- ucret / ledger ---------------------------------------------------------------------------

def test_fee_collected(vault):
    job = _lock(vault, amount=100.0)
    r = _settled(vault, job.job_id)
    assert r.fee_collected_usdc > 0


def test_fee_less_than_amount(vault):
    job = _lock(vault, amount=100.0)
    r = _settled(vault, job.job_id)
    assert 0 < r.fee_collected_usdc < 100.0


def test_protocol_fee_ledger(vault):
    job = _lock(vault, amount=100.0)
    _settled(vault, job.job_id)
    assert vault.total_protocol_revenue_usdc > 0


def test_ledger_balances_dict(vault):
    _settled(vault, _lock(vault).job_id)
    assert isinstance(vault.ledger_balances, dict)


# -- rol-koruma ---------------------------------------------------------------------------

def test_buyer_can_settle(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id, caller=BUYER)
    assert r.status == EscrowStatus.SETTLED


def test_seller_can_settle(vault):
    """Uretim: caller adresi rol ayirmi yapmadan settle eder."""
    job = _lock(vault)
    r = _settled(vault, job.job_id, caller=SELLER)
    assert r.status == EscrowStatus.SETTLED


def test_stranger_rejected(vault):
    """Uretim: buyer/seller disinda reddedilir (EscrowAuthorizationError)."""
    job = _lock(vault)
    vault.submit_output(job.job_id, {"delivery": "ok"})
    vault.mark_verified_ok(job.job_id)
    with pytest.raises(Exception):
        vault.settle_escrow(
            job.job_id,
            caller_address="0x000000000000000000000000000000000000dead")


def test_none_caller_warns_but_settles(vault):
    """AT-193: None caller implicit-privilege (geri-uyumlu)."""
    job = _lock(vault)
    import warnings
    vault.submit_output(job.job_id, {"delivery": "ok"})
    vault.mark_verified_ok(job.job_id)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r, _ = vault.settle_escrow(job.job_id)
    assert r.status == EscrowStatus.SETTLED


def test_none_caller_warns(vault):
    """Uretim: None caller implicit-buyer + UserWarning."""
    job = _lock(vault)
    import warnings
    vault.submit_output(job.job_id, {"delivery": "ok"})
    vault.mark_verified_ok(job.job_id)
    with pytest.warns(UserWarning):
        vault.settle_escrow(job.job_id)


# -- hatali durum ---------------------------------------------------------------------------

def test_unknown_job_raises(vault):
    with pytest.raises(EscrowNotFoundError):
        _settled(vault, "yok-boyle-job")


def test_double_settle_rejected(vault):
    job = _lock(vault)
    _settled(vault, job.job_id)
    with pytest.raises(Exception):
        _settled(vault, job.job_id)


def test_settle_already_settled_status(vault):
    job = _lock(vault)
    _settled(vault, job.job_id)
    assert vault.jobs[job.job_id].status == EscrowStatus.SETTLED


# -- SLA asimi / refund ---------------------------------------------------------------------------

def test_sla_overflow_raises(vault, monkeypatch):
    """locked_at + SLA asimi -> EscrowSLAException."""
    job = _lock(vault)
    monkeypatch.setattr(job, "locked_at_epoch_ms",
                        int(time.time() * 1000) - 10 ** 9)
    with pytest.raises(Exception) as exc:
        _settled(vault, job.job_id)
    msg = str(exc.value).lower()
    assert "sla" in msg or "refund" in msg or "asim" in msg or "asımı" in str(exc.value)


# -- tutarlar ---------------------------------------------------------------------------

def test_small_amount(vault):
    job = _lock(vault, amount=1.0)
    r = _settled(vault, job.job_id)
    assert r.fee_collected_usdc < 1.0


def test_large_amount_fee(vault):
    job = _lock(vault, amount=10000.0)
    r = _settled(vault, job.job_id)
    assert r.fee_collected_usdc > 0


def test_solvency_holds_after_settle(vault):
    _settled(vault, _lock(vault, amount=75.0).job_id)
    assert vault.check_solvency_invariant() is True


# -- kuantum-proof kanit ---------------------------------------------------------------------------

def test_tx_hash_hex_length(vault):
    job = _lock(vault)
    r = _settled(vault, job.job_id)
    assert len(r.settlement_tx) >= 10


# -- birden cok job ---------------------------------------------------------------------------

def test_multiple_jobs_settle_independently(vault):
    j1 = _lock(vault, amount=10.0)
    j2 = _lock(vault, amount=20.0)
    r1 = _settled(vault, j1.job_id)
    r2 = _settled(vault, j2.job_id)
    assert r1.status == EscrowStatus.SETTLED
    assert r2.status == EscrowStatus.SETTLED
    assert r1.job_id != r2.job_id


def test_fees_accumulate(vault):
    _settled(vault, _lock(vault, amount=50.0).job_id)
    f1 = vault.total_protocol_revenue_usdc
    _settled(vault, _lock(vault, amount=50.0).job_id)
    f2 = vault.total_protocol_revenue_usdc
    assert f2 > f1


def test_tx_hashes_unique(vault):
    r1 = _settled(vault, _lock(vault).job_id)
    r2 = _settled(vault, _lock(vault).job_id)
    assert r1.settlement_tx != r2.settlement_tx
