"""UnpumpPaymentBridge.build_unpump_charge dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: yerel Account + D5Ledger (tmp_path).
"""
from pathlib import Path

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import (SettlementBinder, D5Ledger)
from pacta.integrations.unpump_bridge import (UnpumpPaymentBridge,
                                              UnpumpPaymentProof)


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
            "ledger": ledger}


def _proof(**over):
    base = dict(match_id="m-1", bid_id="b-1", agent_id="ag-1",
                buyer_id="by-1", amount=10.0, work_done=True,
                receipt_hash="0x" + "ab" * 32)
    base.update(over)
    return UnpumpPaymentProof(**base)


# -- temel ---------------------------------------------------------------------------------

def test_returns_dict(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert isinstance(c, dict)


def test_op_is_charge(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["op"] == "charge"


def test_job_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["job_id"] == settled_job["job"].job_id


def test_base_delivery_hash(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["delivery_hash"]["alg"] == "sha256"


def test_explicit_delivery_hash(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(
        settled_job["job"], _proof(), "c" * 64)
    assert c["delivery_hash"]["hex"] == "c" * 64


def test_short_delivery_hash_raises(settled_job):
    with pytest.raises(ValueError):
        UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof(), "kisa")


# -- settlement_bind (unpump override) ---------------------------------------------------------------------------------

def test_base_scheme_preserved(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["settlement_bind"]["scheme"] == "x402/v1"


def test_unpump_ref_scheme(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    ref = c["settlement_bind"]["unpump_ref"]
    assert ref["scheme"] == "unpump/v1"


def test_unpump_ref_match_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["settlement_bind"]["unpump_ref"]["match_id"] == "m-1"


def test_unpump_ref_receipt_hash(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["settlement_bind"]["unpump_ref"]["receipt_hash"] == "0x" + "ab" * 32


def test_payer_preserved(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["settlement_bind"]["payer"] == settled_job["buyer"].address


# -- unpump blogu ---------------------------------------------------------------------------------

def test_unpump_block_exists(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert "unpump" in c


def test_unpump_borsa(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["borsa"] == "24-ajan-borsasi"


def test_unpump_match_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["match_id"] == "m-1"


def test_unpump_bid_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["bid_id"] == "b-1"


def test_unpump_agent_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["agent_id"] == "ag-1"


def test_unpump_buyer_id(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["buyer_id"] == "by-1"


def test_unpump_amount(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["amount_usdc"] == "10.000000"


def test_unpump_work_done(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["work_done"] is True


def test_unpump_receipt_hash(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["unpump"]["receipt_hash"] == "0x" + "ab" * 32


def test_unpump_kanit_fields(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert "kanit_entry" in c["unpump"]
    assert "kanit_operation" in c["unpump"]


def test_unpump_completed_at(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert "completed_at_epoch" in c["unpump"]


# -- escrow korundu ---------------------------------------------------------------------------------

def test_escrow_amount_preserved(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["escrow"]["amount_usdc"] == "100.000000"


def test_escrow_status_preserved(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert c["escrow"]["status"] == "SETTLED"


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(settled_job):
    a = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    b = UnpumpPaymentBridge.build_unpump_charge(settled_job["job"], _proof())
    assert a["delivery_hash"]["hex"] == b["delivery_hash"]["hex"]


def test_amount_variants(settled_job):
    c = UnpumpPaymentBridge.build_unpump_charge(
        settled_job["job"], _proof(amount=250.5))
    assert c["unpump"]["amount_usdc"] == "250.500000"
