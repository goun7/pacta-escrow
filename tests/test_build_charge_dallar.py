"""SettlementBinder.build_charge dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: yerel Account + D5Ledger (tmp_path).
"""
from pathlib import Path

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import (SettlementBinder, D5Ledger)


@pytest.fixture
def settled_job(tmp_path):
    buyer = Account.create()
    seller = "0x" + "22" * 20
    ledger = D5Ledger(Path(tmp_path) / "d5")
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address=buyer.address, seller_address=seller,
        amount_usdc=100.0, idempotency_key="pay-1")
    vault.submit_output(job.job_id, {"res": "ok"})
    vault.mark_verified_ok(job.job_id)
    settled, tx = vault.settle_escrow(job.job_id, caller_address=buyer.address)
    return {"job": settled, "buyer": buyer, "seller": seller,
            "ledger": ledger, "vault": vault}


# -- temel ---------------------------------------------------------------------------------

def test_returns_dict(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert isinstance(c, dict)


def test_op_is_charge(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["op"] == "charge"


def test_kind_settlement(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["kind"] == "settlement"


def test_job_id(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["job_id"] == settled_job["job"].job_id


def test_delivery_hash_is_dict(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    dh = c["delivery_hash"]
    assert isinstance(dh, dict)
    assert dh["alg"] == "sha256"


def test_delivery_hash_64hex(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    hx = c["delivery_hash"]["hex"]
    assert len(hx) == 64
    assert all(ch in "0123456789abcdef" for ch in hx)


def test_explicit_delivery_hash(settled_job):
    job = settled_job["job"]
    c = SettlementBinder.build_charge(job, "a" * 64)
    assert c["delivery_hash"]["hex"] == "a" * 64


def test_short_delivery_hash_raises(settled_job):
    with pytest.raises(ValueError):
        SettlementBinder.build_charge(settled_job["job"], "kisa")



def test_non_hex_delivery_hash_raises(settled_job):
    with pytest.raises(ValueError):
        SettlementBinder.build_charge(settled_job["job"], "g" * 64)


# -- settlement_bind ---------------------------------------------------------------------------

def test_binding_scheme(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["settlement_bind"]["scheme"] == "x402/v1"


def test_binding_payer(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["settlement_bind"]["payer"] == settled_job["buyer"].address


def test_binding_payee(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["settlement_bind"]["payee"] == settled_job["seller"]


def test_binding_payment_id(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["settlement_bind"]["payment_id"]


def test_binding_claim_evidence_hash(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["settlement_bind"]["claim_evidence_hash"]


# -- escrow ---------------------------------------------------------------------------

def test_escrow_amount(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["escrow"]["amount_usdc"] == "100.000000"


def test_escrow_fee(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["escrow"]["fee_usdc"]


def test_escrow_status(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["escrow"]["status"] == "SETTLED"


def test_escrow_settlement_tx(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert c["escrow"]["settlement_tx"]


# -- bütünlük ---------------------------------------------------------------------------

def test_pkg_field(settled_job):
    c = SettlementBinder.build_charge(settled_job["job"])
    assert "pkg" in c


def test_repeatable(settled_job):
    a = SettlementBinder.build_charge(settled_job["job"])
    b = SettlementBinder.build_charge(settled_job["job"])
    assert a["delivery_hash"] == b["delivery_hash"]


def test_charge_verify_binding_green(settled_job):
    """build_charge ciktisi verify_binding ile dogrulanabilir."""
    job = settled_job["job"]
    binding = SettlementBinder.bind_settled_job(
        job, settled_job["ledger"], payer_signer=settled_job["buyer"])
    v = SettlementBinder.verify_binding(binding.charge, binding.claim)
    assert v["verdict"] == "GREEN"
