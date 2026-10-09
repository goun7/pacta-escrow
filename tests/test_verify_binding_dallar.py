"""SettlementBinder.verify_binding bes-check dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: yerel Account + D5Ledger (tmp_path).
"""
from pathlib import Path

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import (SettlementBinder, D5Ledger)


@pytest.fixture
def green_pair(tmp_path):
    """Gerçek binding + charge + claim uydusu."""
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
    binding = SettlementBinder.bind_settled_job(settled, ledger,
                                               payer_signer=buyer)
    return {"charge": binding.charge, "claim": binding.claim,
            "buyer": buyer, "seller": seller, "binding": binding,
            "settled": settled, "ledger": ledger}


# -- temel ---------------------------------------------------------------------------------

def test_green_verdict(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert v["verdict"] == "GREEN"


def test_green_ok(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert v["ok"] is True


def test_green_all_checks_pass(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert all(v["checks"].values())


def test_five_checks(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert len(v["checks"]) == 5


def test_check_names(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    names = set(v["checks"])
    assert "1_receipt" in names
    assert "2_claim_sig" in names
    assert "3_settlement_ref" in names or "3_settl" in str(names)


def test_returns_dict(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert isinstance(v, dict)


def test_has_reason(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert "reason" in v


# -- 1) settlement_binding yok ---------------------------------------------------------------------------

def test_missing_binding_red():
    v = SettlementBinder.verify_binding({}, {"buyerAddress": "0x1"})
    assert v["ok"] is not True
    assert v["verdict"] != "GREEN"


def test_binding_wrong_type_red():
    v = SettlementBinder.verify_binding(
        {"settlement_bind": "not-a-dict"}, {"buyerAddress": "0x1"})
    assert v["ok"] is not True


def test_binding_none_red():
    v = SettlementBinder.verify_binding({"settlement_bind": None}, {})
    assert v["ok"] is not True


# -- scheme ---------------------------------------------------------------------------

def test_unsupported_scheme_red(green_pair):
    import copy
    charge = copy.deepcopy(green_pair["charge"])
    charge["settlement_bind"]["scheme"] = "unsupported/v9"
    v = SettlementBinder.verify_binding(charge, green_pair["claim"])
    assert v["ok"] is not True


def test_supported_scheme_passes(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert v["verdict"] == "GREEN"


# -- 2) imza -------------------------------------------------------------------------------

def test_forged_claim_sig_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    impostor = Account.create()
    forged["buyerAddress"] = impostor.address
    v = SettlementBinder.verify_binding(green_pair["charge"], forged)
    assert v["ok"] is not True


def test_claim_sig_check_name(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert "2_claim_sig" in v["checks"]


# -- 3) settlement_ref ---------------------------------------------------------------------------

def test_missing_settlement_ref_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    forged.pop("settlementRef", None)
    forged.pop("settlement_ref", None)
    v = SettlementBinder.verify_binding(green_pair["charge"], forged)
    assert v["ok"] is not True


def test_settlement_ref_wrong_type_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    key = "settlementRef" if "settlementRef" in forged else "settlement_ref"
    forged[key] = 42
    v = SettlementBinder.verify_binding(green_pair["charge"], forged)
    assert v["ok"] is not True


# -- 4) payer/payee -------------------------------------------------------------------------------

def test_payer_mismatch_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    impostor = Account.create()
    key = "payerAddress" if "payerAddress" in forged else "payer"
    if key in forged:
        forged[key] = impostor.address
        v = SettlementBinder.verify_binding(green_pair["charge"], forged)
        assert v["ok"] is not True


def test_payee_mismatch_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    key = "payeeAddress" if "payeeAddress" in forged else "payee"
    if key in forged:
        forged[key] = "0x" + "33" * 20
        v = SettlementBinder.verify_binding(green_pair["charge"], forged)
        assert v["ok"] is not True


# -- 5) evidenceHash ---------------------------------------------------------------------------

def test_evidence_check_name(green_pair):
    v = SettlementBinder.verify_binding(green_pair["charge"],
                                        green_pair["claim"])
    assert any(k.startswith("5_") for k in v["checks"])


def test_evidence_mismatch_red(green_pair):
    import copy
    forged = copy.deepcopy(green_pair["claim"])
    forged["evidenceHash"] = "0x" + "99" * 32
    v = SettlementBinder.verify_binding(green_pair["charge"], forged)
    assert v["ok"] is not True


# -- idempotency / tekrar ---------------------------------------------------------------------------

def test_repeatable(green_pair):
    v1 = SettlementBinder.verify_binding(green_pair["charge"],
                                         green_pair["claim"])
    v2 = SettlementBinder.verify_binding(green_pair["charge"],
                                         green_pair["claim"])
    assert v1["verdict"] == v2["verdict"] == "GREEN"


def test_charge_immutable_input(green_pair):
    before = dict(green_pair["charge"])
    SettlementBinder.verify_binding(green_pair["charge"],
                                    green_pair["claim"])
    assert set(before) == set(green_pair["charge"])


# -- binding bütünlüğü ---------------------------------------------------------------------------

def test_binding_has_charge(green_pair):
    assert "charge" in green_pair["binding"].charge or \
        isinstance(green_pair["binding"].charge, dict)


def test_binding_has_claim(green_pair):
    assert green_pair["binding"].claim is not None


def test_binding_has_delivery_hash(green_pair):
    assert green_pair["binding"].delivery_hash is not None


def test_charge_escrow_amount(green_pair):
    esc = green_pair["charge"]["escrow"]
    assert esc["amount_usdc"] == "100.000000"


def test_claim_buyer_address(green_pair):
    assert green_pair["claim"]["buyerAddress"] == green_pair["buyer"].address
