"""Pacta ↔ Tamga D5-ledger bridge testleri ( RFC-010 cross-artifact settlement binding).

Mesh-bağlantısının-kanıtları:
  * D5-zincir-kuralı-ve-JCS-Pacta-tarafında-Tamga-ile-BİREBİT-üretilir
  * vault-settlement-otomatik-olarak-D5-kaydı-yazar
  * beş-kontrol-gate'i-GREEN/RED-verir ( fail-closed)
  * Tamga'nın-KENDİ-gate'i-ve-ledger-verify'ı-Pacta-kayıtlarını-KABUL-EDER
    ( gerçek-çapraz-proje-doğrulama — stub-DEĞİL).

Tamga-checkout'u erişilebilir-olduğunda ( TAMGA_ROOT-env veya komşu-dizin),
cross-gate-testleri-koşulur; değilse-skip-atarlar ( bağımlılık-YOK).
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations import tamga_jcs
from pacta.integrations.tamga_d5 import (
    D5Ledger,
    D5LedgerError,
    SettlementBinder,
)
from pacta.models import EscrowStatus

BUYER = Account.create()                    # alıcı = gerçek-secp256k1-anahtar
SELLER = "0x" + "22" * 20
STRANGER = "0x" + "33" * 20


def _tamga_root():
    """TamgaProtocol-checkout'u veya None ( yoksa-cross-gate-testleri-skip)."""
    here = Path(__file__).resolve().parent
    cands = [os.environ.get("TAMGA_ROOT"),
             str(here / ".." / ".." / ".." / "05_acik_kaynak" / "TamgaProtocol"),
             "/home/gokun/projects/05_acik_kaynak/TamgaProtocol"]
    for c in cands:
        if not c:
            continue
        root = Path(c).expanduser().resolve()
        if (root / "tamga_runner.py").is_file() \
                and (root / "tools" / "settlement_bind_verify.py").is_file():
            return root
    return None


def _settled_job_with_ledger(tmp_path):
    """D5-ledger-yapılandırılmış-vault ile tam-happy-path ( lock→submit→verify→settle)."""
    ledger = D5Ledger(Path(tmp_path) / "ledger.jsonl")
    vault = PactaEscrowVault(d5_ledger=ledger)
    job = vault.create_and_lock_escrow(
        buyer_address=BUYER.address,
        seller_address=SELLER,
        amount_usdc=100.0,
        idempotency_key="pay-req-1",
    )
    vault.submit_output(job.job_id, {"report": "alpha-analysis", "trades": [1, 2, 3]})
    vault.mark_verified_ok(job.job_id)
    settled_job, tx = vault.settle_escrow(job.job_id, caller_address=BUYER.address)
    assert settled_job.status == EscrowStatus.SETTLED
    assert tx and tx.startswith("0x")
    return ledger, settled_job


# === 1) D5 hash-chain: append + streaming-verify ============================

def test_d5_ledger_chain_appends_and_verifies(tmp_path):
    ledger = D5Ledger(Path(tmp_path) / "ledger.jsonl")

    # boş-zincir-geçerli-bir-pre-genesis-durumudur ( Tamga-D7-ile-aynı)
    ok, tip, why = ledger.verify_chain()
    assert (ok, why) == (True, "ok")
    assert tip == "0" * 64

    r1 = ledger.append({"op": "charge", "x": 1.0})
    r2 = ledger.append({"op": "charge", "x": 2})
    r3 = ledger.append({"op": "charge", "x": 3})

    assert [r["seq"] for r in (r1, r2, r3)] == [1, 2, 3]
    assert r1["prev"] == "0" * 64
    assert r2["prev"] == r1["h"] and r3["prev"] == r2["h"]
    assert all(len(r["h"]) == 64 for r in (r1, r2, r3))

    ok, tip, why = ledger.verify_chain()
    assert (ok, why) == (True, "ok")
    assert tip == r3["h"]
    assert ledger.line_count() == 3

    # RFC-8785-JCS-kanıtı: plain-json-değil — 1.0 → "1" ( ECMAScript-kuralı)
    assert tamga_jcs.jcs({"x": 1.0}) == b'{"x":1}'
    assert tamga_jcs.jcs({"a": 1, "b": 1.0}) == b'{"a":1,"b":1}'


def test_d5_ledger_detects_tampering(tmp_path):
    p = Path(tmp_path) / "ledger.jsonl"
    ledger = D5Ledger(p)
    ledger.append({"op": "charge", "x": 1})
    ledger.append({"op": "charge", "x": 2})
    assert ledger.verify_chain()[0] is True

    lines = p.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["x"] = 999                      # h-artık-tutmaz → broken@1
    lines[0] = json.dumps(tampered, sort_keys=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, tip, why = ledger.verify_chain()
    assert ok is False
    assert tip is None
    assert why.startswith("broken@")


def test_d5_ledger_refuses_append_to_broken_chain(tmp_path):
    p = Path(tmp_path) / "ledger.jsonl"
    ledger = D5Ledger(p)
    ledger.append({"op": "charge", "x": 1})
    # kuyruğu-boz: h-alanı-olmayan-satır ( geçerli-head-yok)
    p.write_text('{"op":"charge","x":2,"seq":2,"prev":"deadbeef"}\n', encoding="utf-8")

    with pytest.raises(D5LedgerError, match="ledger_broken"):
        ledger.append({"op": "charge", "x": 3})


def test_d5_ledger_requires_op(tmp_path):
    ledger = D5Ledger(Path(tmp_path) / "ledger.jsonl")
    with pytest.raises(D5LedgerError, match="op_required"):
        ledger.append({"x": 1})


# === 2) JCS parity: Pacta-vendor-kopyası ↔ Tamga-orijinali ===================

def test_jcs_byte_parity_with_tamga_canon():
    root = _tamga_root()
    if root is None:
        pytest.skip("Tamga-checkout erişilemez ( TAMGA_ROOT env veya komşu dizin)")

    sys.path.insert(0, str(root))
    try:
        import tamga_canon  # orijinal-modül ( RFC-8785)
    finally:
        if str(root) in sys.path:
            sys.path.remove(str(root))

    fixtures = [
        # sayılar ( ECMAScript-vs-Python divergence: 1.0, 2.93e-07, 1e16)
        {"op": "charge", "seq": 1, "amount": 1.0, "ratio": 2.93e-07, "big": 1e16},
        # UTF-16-kod-birimi-sıralaması-ve-kaçışlar
        {"delivery": "ğĞıİşŞ", "nested": {"b": 1, "a": [1.5, -0.0, True, None]}},
        {"z": "𝄞music", "A": 1, "_": "\x00\x1f"},
    ]
    for fx in fixtures:
        assert tamga_jcs.jcs(fx) == tamga_canon.jcs(fx), f"JCS-divergence: {fx!r}"


# === 3) settlement-binding: happy-path + gerçek-Tamga-gate ====================

def test_vault_settlement_emits_d5_binding(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    binding = job.settlement_binding
    assert binding is not None, "D5-ledger-yapılandırılmış-vault bağ yazmalı"
    charge = binding["charge"]
    # RFC-010-şekil-kontratı
    assert charge["op"] == "charge"
    assert charge["settlement_bind"]["scheme"] == "x402/v1"
    assert charge["settlement_bind"]["payment_id"] == job.job_id
    assert charge["settlement_bind"]["payer"] == BUYER.address
    assert charge["settlement_bind"]["payee"] == SELLER
    assert set(charge["delivery_hash"]) == {"alg", "hex"}
    # vault-imzalı-claim-ÜRETMEZ ( non-custodial) — alıcı-imzalar
    assert "signature" not in binding["claim"]
    # delivery-hash-bağımsız-yeniden-üretilebilir ( öz-hizalama-YOK)
    assert SettlementBinder.compute_delivery_hash(job) == binding["delivery_hash"]
    # zincir-sağlam-ve-bağ-onun-ucunda
    ok, tip, why = ledger.verify_chain()
    assert (ok, why) == (True, "ok")
    assert tip == binding["ledger_tip"] == charge["h"]
    # escrow-fon-akışı-değişmemiş
    assert binding["charge"]["escrow"]["amount_usdc"] == "100.000000"


def test_settlement_binding_green_and_tamga_gate_accepts(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    b = job.settlement_binding
    claim = SettlementBinder.build_claim(job, b["delivery_hash"], payer_signer=BUYER)
    assert claim["buyerAddress"] == BUYER.address

    v = SettlementBinder.verify_binding(b["charge"], claim)
    assert v["verdict"] == "GREEN", v["reason"]
    assert v["ok"] is True
    assert all(v["checks"].values())

    # --- Tamga'nın-KENDİ-gate'i-aynı-girdide-aynı-sonucu-vermeli ( mesh-bağı) ---
    root = _tamga_root()
    if root is None:
        pytest.skip("Tamga-checkout erişilemez — cross-gate atlanıyor")
    with tempfile.TemporaryDirectory() as d:
        cf = Path(d) / "charge.json"
        kf = Path(d) / "claim.json"
        cf.write_text(json.dumps(b["charge"]), encoding="utf-8")
        kf.write_text(json.dumps(claim), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(root / "tools" / "settlement_bind_verify.py"),
             str(cf), str(kf)],
            capture_output=True, text=True, cwd=str(root))
    assert r.returncode == 0, f"Tamga-gate RED/İND: {r.stdout}{r.stderr}"
    assert json.loads(r.stdout)["verdict"] == "GREEN"


def test_tamga_runner_ledger_verify_accepts_pacta_ledger(tmp_path):
    """Pacta'nın-yazdığı-ledger.jsonl Tamga'nın-kendi-ledger-verify'ında-sağlam."""
    root = _tamga_root()
    if root is None:
        pytest.skip("Tamga-checkout erişilemez — ledger-verify atlanıyor")
    ledger, job = _settled_job_with_ledger(tmp_path)

    r = subprocess.run(
        [sys.executable, str(root / "tamga_runner.py"), "ledger-verify",
         str(ledger.path.parent)],
        capture_output=True, text=True, cwd=str(root))
    assert r.returncode == 0, f"ledger-verify RED: {r.stdout}{r.stderr}"
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["head"] == job.settlement_binding["ledger_tip"]
    assert out["lines"] == 1


# === 4) fail-closed negatifleri =============================================

def test_settlement_binding_red_on_swapped_parties(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    b = job.settlement_binding
    charge = json.loads(json.dumps(b["charge"]))
    bind = charge["settlement_bind"]
    bind["payer"], bind["payee"] = bind["payee"], bind["payer"]
    claim = SettlementBinder.build_claim(job, b["delivery_hash"], payer_signer=BUYER)

    v = SettlementBinder.verify_binding(charge, claim)
    assert v["verdict"] == "RED"
    assert v["reason_code"] == 6            # party_mismatch
    assert v["checks"]["4_parties"] is False
    # ilk-4-kontrol-yeşil-olsa-bile-5'inci-RED → tümü-RED ( fail-closed)
    assert v["checks"]["1_receipt"] is True
    assert v["checks"]["2_claim_sig"] is True


def test_settlement_binding_red_on_tampered_evidence_hash(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    b = job.settlement_binding

    # safal207-negative-control: geri-kalan-4-kontrol-yeşil-AMA-evidenceHash-farklı
    # ( imza-YENİ-forged-hash-üzerine-düzgün-atıldı — böylece-sadece-5. kontrol-RED)
    forged = hashlib.sha256(b"forged-delivery").hexdigest()
    forged_claim = SettlementBinder.build_claim(
        job, delivery_hash=forged, payer_signer=BUYER)
    v = SettlementBinder.verify_binding(b["charge"], forged_claim)
    assert (v["verdict"], v["reason_code"]) == ("RED", 7)   # evidence_hash_mismatch
    assert v["checks"]["5_evidence_hash"] is False
    assert v["checks"]["2_claim_sig"] is True                # imza-geçerli-AMA-hash-yanlış

    # imzalı-claim'i-sonradan-değiştirmek-imzayı-da-bozar ( ek-fail-closed)
    signed = SettlementBinder.build_claim(job, b["delivery_hash"], payer_signer=BUYER)
    signed["evidenceHash"]["hex"] = forged
    v2 = SettlementBinder.verify_binding(b["charge"], signed)
    assert (v2["verdict"], v2["reason_code"]) == ("RED", 4)  # claim_signature_invalid


def test_unsigned_or_wrong_signer_claim_is_red(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    b = job.settlement_binding

    unsigned = SettlementBinder.build_claim(job, b["delivery_hash"])
    assert "signature" not in unsigned
    v = SettlementBinder.verify_binding(b["charge"], unsigned)
    assert (v["verdict"], v["reason_code"]) == ("RED", 4)   # claim_signature_invalid

    # yanlış-anahtarla-imzalama-girişimi-üretimde-reddedilir ( signer != buyer)
    impostor = Account.create()
    with pytest.raises(ValueError, match="signer_mismatch"):
        SettlementBinder.build_claim(job, b["delivery_hash"], payer_signer=impostor)


def test_binding_refuses_unsettled_job(tmp_path):
    ledger = D5Ledger(Path(tmp_path) / "ledger.jsonl")
    vault = PactaEscrowVault(d5_ledger=ledger)
    job = vault.create_and_lock_escrow(
        buyer_address=BUYER.address, seller_address=SELLER, amount_usdc=10.0)

    with pytest.raises(ValueError, match="not_settled"):
        SettlementBinder.bind_settled_job(job, ledger)
    # fail-closed: RED-öncesi-hiçbir-şey-zincire-yazılmamış
    assert ledger.line_count() == 0


def test_unknown_scheme_is_indeterminate(tmp_path):
    ledger, job = _settled_job_with_ledger(tmp_path)
    b = job.settlement_binding
    charge = json.loads(json.dumps(b["charge"]))
    charge["settlement_bind"]["scheme"] = "totally/fake"
    claim = SettlementBinder.build_claim(job, b["delivery_hash"], payer_signer=BUYER)

    v = SettlementBinder.verify_binding(charge, claim)
    assert v["verdict"] == "İNDETERMİNE"    # bilinmeyen-şema-RED-değil-esirgenir
    assert v["reason_code"] == 2
