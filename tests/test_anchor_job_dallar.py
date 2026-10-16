"""PactaEscrowVault.anchor_job dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: mock chain-adapter + yerel adresler.
"""
import types

import pytest

from pacta.core.vault import PactaEscrowVault
from pacta.models import EscrowPolicy


BUYER = "0x59b66b9e6ffdd9ba6ff61c12acfec66f46cd32"
SELLER = "0x2fe8de9732027146046b7f4603994c5a5f5cb0"


@pytest.fixture
def vault():
    return PactaEscrowVault()


def _job(vault, amount=10.0):
    return vault.create_and_lock_escrow(
        buyer_address=BUYER, seller_address=SELLER,
        amount_usdc=amount, policy=EscrowPolicy())


def _settled(vault, amount=10.0):
    job = _job(vault, amount)
    vault.submit_output(job.job_id, {"res": "ok"})
    vault.mark_verified_ok(job.job_id)
    settled, tx = vault.settle_escrow(job.job_id, caller_address=BUYER)
    return settled


class _FakeAdapter:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def anchor(self, **kw):
        self.calls.append(kw)
        if not self.ok:
            raise RuntimeError("chain-hata")
        return "0xabc"


def _adapter(vault, ok=True):
    ad = _FakeAdapter(ok)
    vault.chain_adapter = ad
    return ad


# -- temel ---------------------------------------------------------------------------------

def test_anchor_kind_settlement(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    assert ad.calls[0]["anchor_kind"] == "settlement"


def test_anchor_calls_adapter(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    assert len(ad.calls) == 1


def test_anchor_passes_job_id(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    assert ad.calls[0]["job_id"] == job.job_id


def test_anchor_to_seller(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    assert ad.calls[0]["to_address"] == SELLER


def test_anchor_terms_amount(vault):
    job = _job(vault, amount=25.0)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    terms = ad.calls[0]["terms"]
    assert terms["amount_usdc"] == "25.000000"


def test_anchor_terms_parties(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    terms = ad.calls[0]["terms"]
    assert terms["buyer"] == BUYER
    assert terms["seller"] == SELLER


def test_anchor_terms_status(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    terms = ad.calls[0]["terms"]
    assert terms["status"] == "ESCROW_LOCKED"


# -- hata ---------------------------------------------------------------------------------

def test_no_chain_adapter_raises(vault):
    job = _job(vault)
    with pytest.raises(Exception) as exc:
        vault.anchor_job(job.job_id)
    assert "chain" in str(exc.value).lower()


def test_unknown_job_raises(vault):
    _adapter(vault)
    with pytest.raises(Exception):
        vault.anchor_job("yok-job")


def test_adapter_error_propagates(vault):
    job = _job(vault)
    _adapter(vault, ok=False)
    with pytest.raises(RuntimeError):
        vault.anchor_job(job.job_id)


# -- ek alanlar ---------------------------------------------------------------------------------

def test_fee_included_when_settled(vault):
    settled = _settled(vault)
    ad = _adapter(vault)
    vault.anchor_job(settled.job_id)
    terms = ad.calls[0]["terms"]
    assert terms["fee_usdc"] == "0.075000"


def test_fee_absent_before_settle(vault):
    """PACTA-VLT-4: LOCKED işte-fee_usdc-terms'e-KONMAZ ( eski-pin-"sifir-
    olarak-bulunur"-diyordu — sessiz-sıfır-ücret-sabitlemesiydi; fee
    settle'da-tahsil-edilir, öncesi-"henüz-yok")."""
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    terms = ad.calls[0]["terms"]
    assert "fee_usdc" not in terms


def test_settled_at_ms_included(vault):
    settled = _settled(vault)
    ad = _adapter(vault)
    vault.anchor_job(settled.job_id)
    terms = ad.calls[0]["terms"]
    assert int(terms["settled_at_ms"]) > 0


def test_settled_at_absent_before_settle(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    terms = ad.calls[0]["terms"]
    assert "settled_at_ms" not in terms


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(vault):
    job = _job(vault)
    ad = _adapter(vault)
    vault.anchor_job(job.job_id)
    vault.anchor_job(job.job_id)
    assert len(ad.calls) == 2


def test_anchor_after_settle(vault):
    settled = _settled(vault)
    _adapter(vault)
    r = vault.anchor_job(settled.job_id)
    assert r is not None


def test_multiple_jobs_anchored(vault):
    j1 = _job(vault)
    j2 = _job(vault, amount=20.0)
    ad = _adapter(vault)
    vault.anchor_job(j1.job_id)
    vault.anchor_job(j2.job_id)
    assert len(ad.calls) == 2
    assert ad.calls[1]["terms"]["amount_usdc"] == "20.000000"
