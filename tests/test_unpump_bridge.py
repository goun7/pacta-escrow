"""Pacta ↔ Unpump ( 24-ajan-borsasi) ödeme-kanıtı köprü testleri.

Mesh-bağlantısının-kanıtları ( ödeme → escrow-settlement → D5-kanıtı):
  * Unpump'un-gerçek-``borsa_core``+``kanit_cekirdegi``'yle-koşar ( stub-DEĞİL):
    listele → teklif → eşleş → kanıt-zincirine-damga → complete_work.
  * receipt_hash-üçüncü-tarafça-bağımsız-yeniden-üretilebilir ( gönderenin-
    sözüne-güvenilmez).
  * ödeme-kanıtı-settled-escrow'la-uzlaşır-ve-D5'e-yazılır; RFC-010-üstküsesi-
    olarak-Tamga'nın-KENDİ-gate'i-ve-ledger-verify'ı-tarafından-KABUL-EDİLİR
    ( üç-yönlü-çapraz-test: Unpump ↔ Pacta ↔ Tamga).
  * fail-closed: kanıt/uzlaşı-KIRMIZI-ise-hiçbir-şey-zincire-yazılmaz.

24-ajan-borsasi-checkout'u-erişilebilirse-koşulur ( UNPUMP_ROOT-env-veya-
komşu-dizin); değilse-skip-atar ( bağımlılık-YOK).
"""

import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import D5Ledger, SettlementBinder
from pacta.integrations.unpump_bridge import (
    UnpumpBinding,
    UnpumpBridgeError,
    UnpumpPaymentBridge,
    UnpumpPaymentProof,
)
from pacta.models import EscrowStatus

BUYER = Account.create()                    # alıcı = gerçek-secp256k1-anahtar
AGENT = "0x" + "44" * 20                    # Unpump-ajanı = Pacta-satıcı


def _unpump_modules():
    """Gerçek-24-ajan-borsasi-modüllerini-yükle veya-yoksa-skip."""
    root = UnpumpPaymentBridge.unpump_root()
    if root is None:
        pytest.skip("Unpump (24-ajan-borsasi) erişilemez — UNPUMP_ROOT env "
                    "veya komşu dizin; cross-testler atlanıyor")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import borsa_core          # yerel-import ( keşif-yolu)
    import kanit_cekirdegi
    return root, borsa_core, kanit_cekirdegi


def _tamga_root():
    """TamgaProtocol-checkout'u veya None ( yoksa-cross-gate-testleri-skip)."""
    here = Path(__file__).resolve().parent
    cands = [os.environ.get("TAMGA_ROOT"),
             "/home/gokun/projects/05_acik_kaynak/TamgaProtocol"]
    for c in cands:
        if not c:
            continue
        root = Path(c).expanduser().resolve()
        if (root / "tamga_runner.py").is_file() \
                and (root / "tools" / "settlement_bind_verify.py").is_file():
            return root
    return None


def _settled_job(tmp_path, *, amount=100.0):
    """D5-ledger'yapılandırılmış-vault ile tam-happy-path ( SETTLED + charge)."""
    ledger = D5Ledger(Path(tmp_path) / "ledger.jsonl")
    vault = PactaEscrowVault(d5_ledger=ledger)
    job = vault.create_and_lock_escrow(
        buyer_address=BUYER.address,
        seller_address=AGENT,
        amount_usdc=amount,
        idempotency_key="ik-" + secrets.token_hex(8),
    )
    vault.submit_output(job.job_id, {"report": "unpump-analysis", "trades": [4, 5]})
    vault.mark_verified_ok(job.job_id)
    settled_job, tx = vault.settle_escrow(job.job_id, caller_address=BUYER.address)
    assert settled_job.status == EscrowStatus.SETTLED
    assert tx and tx.startswith("0x")
    return ledger, settled_job


def _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path, *,
                          amount=100.0, buyer=None, agent=None):
    """Gerçek-Unpump-akışıyla-ödeme-kanıtı-üret ( listele→teklif→eşleş→damga→tamamla).

    ``complete_work``'ün-``receipt_hash``'i-``kanit_cekirdegi``'nin-zincir-
    girişinin-``h``'sidir — yani-ödeme-kanıtı-Unpump'un-KENDİ-hash-zincirinden-
    gelir ( Pacta'nın-uydurması-DEĞİL).
    """
    db = str(tmp_path / f"borsa-{secrets.token_hex(4)}.sqlite")
    store = str(tmp_path / f"kanit-store-{secrets.token_hex(4)}.json")
    by = buyer if buyer is not None else BUYER.address
    ag = agent if agent is not None else AGENT

    borsa_core.list_agent(
        agent_id=ag, name="test-agent", service="randevu",
        price_target=amount, proof_hash="sha256:" + "00" * 32, db=db)
    bid = borsa_core.place_bid(
        agent_id=ag, buyer_id=by, amount=amount,
        work_spec='{"islem":"randevu-analizi"}',
        nonce="n-" + secrets.token_hex(8), db=db)
    match = borsa_core.match_bid(bid.bid_id, db=db)
    assert match is not None, "teklif eşleşmedi ( amount < price_target)"

    # ⭐⭐⭐ kanıt-zincirine-damga → receipt_hash
    islem = kanit_cekirdegi.match_kanit_islemi(match, source="unpump-borsa")
    zincir = kanit_cekirdegi.KanitZinciri(store)
    res = zincir.ekle(islem)
    assert res["ok"], f"kanıt damgası başarısız: {res}"
    tamga = res["tamga"]                                  # {id, h, prev}

    match = borsa_core.complete_work(match.match_id, receipt_hash=tamga["h"], db=db)
    assert match.work_done is True
    assert match.receipt_hash == tamga["h"]

    return UnpumpPaymentProof.from_match(
        match, buyer_id=by, kanit_entry=tamga,
        kanit_operation=islem.kanonik()), zincir


# === 1) ödeme-kanıtı: bağımsız-yeniden-üretim ================================

def test_unpump_payment_proof_verifies_independently(tmp_path):
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    proof, zincir = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)

    v = UnpumpPaymentBridge.verify_payment_proof(proof)
    assert v["verdict"] == "GREEN", v["reason"]
    assert v["ok"] is True
    assert all(v["checks"].values()), v["checks"]

    # receipt-üçüncü-tarafça-bağımsız-teyit: Unpump'un-KENDİ-sözleşmesiyle
    dogrudan = kanit_cekirdegi.content_hash(proof.kanit_operation)
    assert dogrudan == proof.receipt_hash == proof.kanit_entry["h"]
    # zincir-de-sağlam ( Unpump-tarafı-kendisi-doğrular)
    assert zincir.dogrula()["ok"] is True

    # --- negatif: kurcalanmış-receipt → RED ( gönderene-güvenilmez)
    bozuk = UnpumpPaymentProof(**{**proof.__dict__})
    bozuk.receipt_hash = "sha256:" + "ff" * 32
    v2 = UnpumpPaymentBridge.verify_payment_proof(bozuk)
    assert v2["verdict"] == "RED"
    assert v2["checks"]["u2_kanit_entry"] is False

    # --- negatif: tamamlanmamış-iş → RED ( u1)
    yarim = UnpumpPaymentProof(**{**proof.__dict__})
    yarim.work_done = False
    v3 = UnpumpPaymentBridge.verify_payment_proof(yarim)
    assert (v3["verdict"], v3["reason_code"]) == ("RED", 11)
    assert v3["checks"]["u1_work_done"] is False


def test_payment_proof_indeterminate_without_kanit_cekirdegi(tmp_path, monkeypatch):
    """Dürüst-sınır: Delilix-hash-sözleşmesi-erişilemezse-RED-değil-İNDETERMİNE."""
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    proof, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)

    monkeypatch.setattr(UnpumpPaymentBridge, "_kanit_cekirdegi",
                        staticmethod(lambda: None))
    v = UnpumpPaymentBridge.verify_payment_proof(proof)
    assert v["verdict"] == "İNDETERMİNE"
    assert v["reason_code"] == 13
    # u1/u2-yeşil-AMA-receipt-esirgendi ( gizlice-geçti-denmez)
    assert v["checks"]["u1_work_done"] is True
    assert v["checks"]["u2_kanit_entry"] is True


# === 2) ödeme → escrow-settlement → D5-kanıtı: happy-path =====================

def test_bind_unpump_payment_to_d5_green_path(tmp_path):
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    ledger, job = _settled_job(tmp_path)                    # escrow-settlement
    once = ledger.line_count()
    proof, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)

    binding = UnpumpPaymentBridge.bind_unpump_payment(
        proof, job, ledger, payer_signer=BUYER)

    assert isinstance(binding, UnpumpBinding)
    # D5-kanıtı-zincire-yazıldı-ve-zincir-sağlam
    ok, tip, why = ledger.verify_chain()
    assert (ok, why) == (True, "ok")
    assert tip == binding.ledger_tip == binding.charge["h"]
    assert ledger.line_count() == once + 1

    # RFC-010-üstküsesi: ``SettlementBinder``'ın-KENDİ-gate'i-de-GEÇER
    base = SettlementBinder.verify_binding(binding.charge, binding.claim)
    assert base["verdict"] == "GREEN", base["reason"]

    # sekiz-kontrol-tam-yeşil
    v = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert v["verdict"] == "GREEN", v["reason"]
    assert v["ok"] is True
    assert set(v["checks"]) >= {"1_receipt", "2_claim_sig", "3_settlement_ref",
                                "4_parties", "5_evidence_hash",
                                "6_unpump_proof", "7_receipt_recomputes",
                                "8_escrow_reconcile"}
    assert all(v["checks"].values()), v["checks"]

    # geri-okuma: D5 → Unpump-ödeme-referansı
    ref = UnpumpPaymentBridge.unpump_ref_of(binding.charge)
    assert ref["match_id"] == proof.match_id
    assert ref["receipt_hash"] == proof.receipt_hash
    assert UnpumpPaymentBridge.unpump_ref_of(
        job.settlement_binding["charge"]) is None     # sade-escrow-bağında-yok

    # delivery-hash-bağımsız-yeniden-üretilebilir ( öz-hizalama-YOK)
    assert SettlementBinder.compute_delivery_hash(job) == binding.delivery_hash


# === 3) üç-yönlü-çapraz-test: Tamga'nın-KENDİ-gate'i-ve-ledger'ı ==============

def test_tamga_gate_and_ledger_accept_unpump_charge(tmp_path):
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    root = _tamga_root()
    if root is None:
        pytest.skip("Tamga-checkout erişilemez — cross-gate atlanıyor")

    ledger, job = _settled_job(tmp_path)
    proof, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)
    binding = UnpumpPaymentBridge.bind_unpump_payment(
        proof, job, ledger, payer_signer=BUYER)

    # --- Tamga'nın-KENDİ-gate'i-Unpump-bağını-KABUL-ETMELİ ( üçüncü-proje) ---
    with tempfile.TemporaryDirectory() as d:
        cf = Path(d) / "charge.json"
        kf = Path(d) / "claim.json"
        cf.write_text(json.dumps(binding.charge), encoding="utf-8")
        kf.write_text(json.dumps(binding.claim), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(root / "tools" / "settlement_bind_verify.py"),
             str(cf), str(kf)],
            capture_output=True, text=True, cwd=str(root))
    assert r.returncode == 0, f"Tamga-gate RED/İND: {r.stdout}{r.stderr}"
    assert json.loads(r.stdout)["verdict"] == "GREEN"

    # --- Tamga'nın-ledger-verify'ı-Pacta'nın-ledger'ını-sağlam-bulmalı ------
    r2 = subprocess.run(
        [sys.executable, str(root / "tamga_runner.py"), "ledger-verify",
         str(ledger.path.parent)],
        capture_output=True, text=True, cwd=str(root))
    assert r2.returncode == 0, f"ledger-verify RED: {r2.stdout}{r2.stderr}"
    out = json.loads(r2.stdout)
    assert out["ok"] is True
    assert out["head"] == binding.ledger_tip
    assert out["lines"] == 2                      # escrow-charge + unpump-charge


# === 4) fail-closed: uzlaşısız-bağ-yazmaz ====================================

def test_bind_rejects_mismatched_payment_and_writes_nothing(tmp_path):
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    ledger, job = _settled_job(tmp_path, amount=100.0)
    once = ledger.line_count()

    # tutar-uymayan-ödeme ( 50 ≠ 100)
    proof50, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path,
                                       amount=50.0)
    with pytest.raises(UnpumpBridgeError, match="reconciliation_failed"):
        UnpumpPaymentBridge.bind_unpump_payment(proof50, job, ledger,
                                                payer_signer=BUYER)
    assert ledger.line_count() == once, "uzlaşısız bağ zincire YAZILMAMALI"

    # taraflar-uymayan-ödeme ( başka-alıcı)
    stranger = Account.create()
    proof_stranger, _ = _unpump_payment_proof(
        borsa_core, kanit_cekirdegi, tmp_path, amount=100.0, buyer=stranger.address)
    with pytest.raises(UnpumpBridgeError, match="reconciliation_failed"):
        UnpumpPaymentBridge.bind_unpump_payment(proof_stranger, job, ledger,
                                                payer_signer=BUYER)
    assert ledger.line_count() == once

    # tamamlanmamış-iş-iddiası
    proof_open, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)
    proof_open.work_done = False
    with pytest.raises(UnpumpBridgeError, match="payment_proof_not_green"):
        UnpumpPaymentBridge.bind_unpump_payment(proof_open, job, ledger,
                                                payer_signer=BUYER)
    assert ledger.line_count() == once


# === 5) doğrulama-kapısı: kurcalamaya-RED ====================================

def test_verify_binding_red_on_forged_receipt(tmp_path):
    _, borsa_core, kanit_cekirdegi = _unpump_modules()
    ledger, job = _settled_job(tmp_path)
    proof, _ = _unpump_payment_proof(borsa_core, kanit_cekirdegi, tmp_path)
    binding = UnpumpPaymentBridge.bind_unpump_payment(
        proof, job, ledger, payer_signer=BUYER)
    claim = binding.claim

    # --- (a) unpump-bloğundaki-receipt-kurcalandı → 6. kontrol-RED
    c1 = json.loads(json.dumps(binding.charge))
    c1["unpump"]["receipt_hash"] = "sha256:" + "ee" * 32
    v1 = UnpumpPaymentBridge.verify_binding(c1, claim)
    assert (v1["verdict"], v1["reason_code"]) == ("RED", 16)
    assert v1["checks"]["6_unpump_proof"] is False
    assert v1["checks"]["5_evidence_hash"] is True       # RFC-010-kısmı-hâlâ-yeşil

    # --- (b) receipt + ref-birlikte-düzeltildi-AMA-kanıt-olgusu-kurcalandı:
    #     bağımsız-yeniden-hesap-uyuşmaz → 7. kontrol-RED
    c2 = json.loads(json.dumps(binding.charge))
    forged = c2["unpump"]["receipt_hash"]                # ref'le-aynı-yap
    c2["settlement_bind"]["unpump_ref"]["receipt_hash"] = forged
    c2["unpump"]["kanit_operation"]["amount"] = 999.0
    v2 = UnpumpPaymentBridge.verify_binding(c2, claim)
    assert v2["verdict"] == "RED"
    assert v2["checks"]["6_unpump_proof"] is True        # bu-kez-6-geçti
    assert v2["checks"]["7_receipt_recomputes"] is False

    # --- (c) escrow-tutarı-kurcalandı → 8. kontrol-RED
    c3 = json.loads(json.dumps(binding.charge))
    c3["unpump"]["amount_usdc"] = "999.000000"
    v3 = UnpumpPaymentBridge.verify_binding(c3, claim)
    assert v3["verdict"] == "RED"
    assert v3["checks"]["8_escrow_reconcile"] is False

    # orijinal-kayıtlar-hâlâ-yeşil ( kurcalama-yalnızca-kopyaları-etkiledi)
    assert UnpumpPaymentBridge.verify_binding(
        binding.charge, claim)["verdict"] == "GREEN"
