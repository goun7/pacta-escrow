"""unpump_bridge.reconcile dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: saf karsilastirma fonksiyonu.
"""
import pytest
from pydantic import BaseModel
from decimal import Decimal

from pacta.integrations.unpump_bridge import (
    AMOUNT_TOLERANCE, UnpumpPaymentBridge, UnpumpPaymentProof)
from pacta.models import EscrowJob, EscrowStatus


class _T:
    AGENT = "0xAGENT"
    BUYER = "0xBUYER"
    RECEIPT = "0xRECEIPT"
    AMOUNT = 10.0


def _proof(**kw):
    args = dict(
        match_id="m1", agent_id=_T.AGENT, buyer_id=_T.BUYER,
        amount=_T.AMOUNT, work_done=True,
        receipt_hash=_T.RECEIPT,
        kanit_entry={"h": _T.RECEIPT},
    )
    args.update(kw)
    return UnpumpPaymentProof(**args)


def _job(**kw):
    args = dict(
        job_id="j1", buyer_address=_T.BUYER,
        seller_address=_T.AGENT, amount_usdc=Decimal(str(_T.AMOUNT)),
        status=EscrowStatus.SETTLED, settlement_tx="0xSETTLE",
    )
    args.update(kw)
    return EscrowJob(**args)


def _r(proof=None, job=None):
    return UnpumpPaymentBridge.reconcile(proof or _proof(),
                                  job or _job())


# -- tam uzlasim ---------------------------------------------------------------------------------

def test_returns_dict():
    assert isinstance(_r(), dict)


def test_ok_true():
    assert _r()["ok"] is True


def test_all_checks_pass():
    c = _r()["checks"]
    assert all(c.values())


def test_reason_reconciled():
    assert _r()["reason"] == "reconciled"


def test_keys_stable():
    assert set(_r()) == {"ok", "checks", "reason"}


def test_checks_names():
    assert set(_r()["checks"]) == {"r1_settled", "r2_amount",
                                   "r3_parties",
                                   "r4_receipt_bound"}


def test_checks_is_dict():
    assert isinstance(_r()["checks"], dict)


# -- r1 status ---------------------------------------------------------------------------------

def test_r1_fails_on_not_settled():
    r = _r(job=_job(status=EscrowStatus.ESCROW_LOCKED))
    assert r["ok"] is False
    assert r["checks"]["r1_settled"] is False


def test_r1_fails_on_missing_tx():
    r = _r(job=_job(settlement_tx=None))
    assert r["ok"] is False
    assert r["checks"]["r1_settled"] is False


@pytest.mark.parametrize("status", [
    EscrowStatus.INITIALIZED, EscrowStatus.OUTPUT_SUBMITTED,
    EscrowStatus.VERIFIED_OK, EscrowStatus.DISPUTED,
    EscrowStatus.ARBITRATION_IN_PROGRESS,
])
def test_r1_non_settled_statuses(status):
    r = _r(job=_job(status=status))
    assert r["checks"]["r1_settled"] is False


def test_r1_reason_has_mismatch():
    r = _r(job=_job(status=EscrowStatus.DISPUTED))
    assert "unpump_escrow_mismatch" in r["reason"]


# -- r2 amount ---------------------------------------------------------------------------------

def test_r2_exact():
    assert _r()["checks"]["r2_amount"] is True


def test_r2_small_diff_ok():
    job = _job(amount_usdc=Decimal(str(_T.AMOUNT + 1e-9)))
    assert _r(job=job)["checks"]["r2_amount"] is True


def test_r2_big_diff_fails():
    job = _job(amount_usdc=Decimal("999"))
    r = _r(job=job)
    assert r["ok"] is False
    assert r["checks"]["r2_amount"] is False


def test_r2_negative_diff_fails():
    job = _job(amount_usdc=Decimal("0.01"))
    assert _r(job=job)["checks"]["r2_amount"] is False


def test_r2_both_zero():
    r = _r(job=_job(amount_usdc=Decimal("0.000001")),
           proof=_proof(amount=0.000001))
    assert r["checks"]["r2_amount"] is True


def test_r2_tolerance_boundary():
    job = _job(amount_usdc=Decimal(str(_T.AMOUNT + AMOUNT_TOLERANCE)))
    assert _r(job=job)["checks"]["r2_amount"] is True


def test_r2_over_tolerance():
    job = _job(
        amount_usdc=Decimal(str(_T.AMOUNT + AMOUNT_TOLERANCE + 1e-6)))
    assert _r(job=job)["checks"]["r2_amount"] is False


# -- r3 parties ---------------------------------------------------------------------------------

def test_r3_case_insensitive():
    job = _job(buyer_address=_T.BUYER.lower(),
               seller_address=_T.AGENT.lower())
    assert _r(job=job)["checks"]["r3_parties"] is True


def test_r3_case_mixed():
    job = _job(buyer_address=_T.BUYER.title(),
               seller_address=_T.AGENT.title())
    assert _r(job=job)["checks"]["r3_parties"] is True


def test_r3_buyer_mismatch():
    r = _r(job=_job(buyer_address="0xBASKA"))
    assert r["ok"] is False
    assert r["checks"]["r3_parties"] is False


def test_r3_seller_mismatch():
    r = _r(job=_job(seller_address="0xBASKA"))
    assert r["ok"] is False
    assert r["checks"]["r3_parties"] is False


def test_r3_both_mismatch():
    r = _r(job=_job(buyer_address="0xB1", seller_address="0xB2"))
    assert r["checks"]["r3_parties"] is False


def test_r3_swapped_parties():
    r = _r(job=_job(buyer_address=_T.AGENT,
                    seller_address=_T.BUYER))
    assert r["checks"]["r3_parties"] is False


# -- r4 receipt ---------------------------------------------------------------------------------

def test_r4_fails_on_missing_kanit():
    r = _r(proof=_proof(kanit_entry=None))
    assert r["ok"] is False
    assert r["checks"]["r4_receipt_bound"] is False


def test_r4_fails_on_wrong_hash():
    r = _r(proof=_proof(kanit_entry={"h": "0xBASKA"}))
    assert r["checks"]["r4_receipt_bound"] is False


def test_r4_fails_on_missing_key():
    r = _r(proof=_proof(kanit_entry={"other": "x"}))
    assert r["checks"]["r4_receipt_bound"] is False


def test_r4_passes_with_correct_hash():
    assert _r()["checks"]["r4_receipt_bound"] is True


def test_r4_empty_kanit_fails():
    r = _r(proof=_proof(kanit_entry={}))
    assert r["checks"]["r4_receipt_bound"] is False


# -- coklu hatalar ---------------------------------------------------------------------------------

def test_two_failures_listed():
    r = _r(job=_job(status=EscrowStatus.INITIALIZED,
                    amount_usdc=Decimal("999")))
    assert "r1_settled" in r["reason"]
    assert "r2_amount" in r["reason"]


def test_all_four_failures():
    r = _r(
        proof=_proof(kanit_entry=None, amount=0.0),
        job=_job(status=EscrowStatus.INITIALIZED,
                 amount_usdc=Decimal("999"),
                 buyer_address="0xB1"))
    assert r["ok"] is False
    assert not any(r["checks"].values())


def test_only_one_failure():
    r = _r(job=_job(status=EscrowStatus.INITIALIZED))
    bad = [k for k, v in r["checks"].items() if not v]
    assert bad == ["r1_settled"]


# -- reason format ---------------------------------------------------------------------------------

def test_reason_lists_failed_checks():
    r = _r(job=_job(status=EscrowStatus.INITIALIZED))
    assert r["reason"] == "unpump_escrow_mismatch: r1_settled"


def test_ok_true_reason_reconciled():
    assert _r()["reason"] == "reconciled"


def test_ok_false_reason_mismatch():
    r = _r(job=_job(status=EscrowStatus.INITIALIZED))
    assert r["reason"].startswith("unpump_escrow_mismatch")


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    assert _r() == _r()


def test_independent_jobs():
    a = _r(job=_job(status=EscrowStatus.SETTLED))
    b = _r(job=_job(status=EscrowStatus.INITIALIZED))
    assert a["ok"] and not b["ok"]


def test_no_mutation():
    p, j = _proof(), _job()
    _r(p, j)
    assert p.receipt_hash == _T.RECEIPT
    assert j.status == EscrowStatus.SETTLED


def test_work_done_irrelevant():
    r = _r(proof=_proof(work_done=False))
    assert r["ok"] is True
