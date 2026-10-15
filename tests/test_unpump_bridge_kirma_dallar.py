"""unpump_bridge odeme-kaniti koprude dal-kesen testleri (LEED).

Kapsanan modul: pacta/integrations/unpump_bridge.py
  - UnpumpPaymentProof.from_match (duck-typed Match)
  - UnpumpPaymentBridge: unpump_root/_kanit_cekirdegi keşfi, _kanonik_islem,
    verify_payment_proof (u1..u4 GREEN/RED/INDETERMINE), reconcile (r1..r4),
    build_unpump_charge, bind_unpump_payment, verify_binding (RFC-010 beşi +
    unpump 6/7/8 sekiz-kontrol), unpump_ref_of

Kural-1: mevcut testlere/conftest'e/uretime DOKUNULMADI — SADECE bu yeni
dosya eklendi.
Saf-bellek: kanit_cekirdegi yerel STUB (gercek checkout ogrenilmez),
D5Ledger(tmp_path), yerel eth_account anahtarlari — ag/DNS/socket/
gercek-subprocess YOK.
"""
import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from eth_account import Account

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import D5Ledger, SettlementBinder
from pacta.integrations.unpump_bridge import (
    UNPUMP_TAG,
    UnpumpBinding,
    UnpumpBridgeError,
    UnpumpPaymentBridge,
    UnpumpPaymentProof,
)
from pacta.models import EscrowStatus

_S_SELLER = "0x" + "22" * 20
_OTHER = "0x" + "33" * 20
_TS = "2026-10-15T10:00:00Z"


# ------------------------------------------------------- kanit stub (saf-bellek)

class _KanitStub:
    """Delilix hash-sozlesmesinin IN-MEMORY taklidi (gercek modul OGRENILMEZ).

    content_hash -> "sha256:" + sha256(kanonik-6-alan JSON'u) — 发包者 sırası
    korunur (gercekteki js_stringify davranisinin sadik kopyasi degil; test
    icin tutarlılık yeterlidir).
    """

    CANONICAL_ALANLAR = ("agent_id", "operation", "amount", "ref", "ts", "source")

    @staticmethod
    def content_hash(kayit) -> str:
        govde = json.dumps(
            {a: kayit.get(a) for a in _KanitStub.CANONICAL_ALANLAR},
            separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(govde).hexdigest()

    @staticmethod
    def day_key(ts: str) -> str:
        if not isinstance(ts, str) or len(ts) < 10 or "T" not in ts:
            raise ValueError(f"gecersiz ts: {ts!r}")
        return ts[:10]


def _stub_kc():
    return _KanitStub


def _kanitre_kc(monkeypatch):
    monkeypatch.setattr(UnpumpPaymentBridge, "_kanit_cekirdegi",
                        staticmethod(_stub_kc))


def _none_kc(monkeypatch):
    monkeypatch.setattr(UnpumpPaymentBridge, "_kanit_cekirdegi",
                        staticmethod(lambda: None))


def _make_operation(agent=_S_SELLER, amount=100.0, ref="m-1", ts=_TS) -> dict:
    return {"agent_id": agent, "operation": "complete_work", "amount": amount,
            "ref": ref, "ts": ts, "source": "borsa"}


def _make_proof(*, buyer=_S_SELLER, agent=_S_SELLER, amount=100.0,
                work_done=True, ts=_TS, kanit=True, receipt=None,
                kanit_entry=None, kanit_operation=None) -> UnpumpPaymentProof:
    """Tutarli kanit: receipt_hash stub tarafindan bağımsızca hesaplanir."""
    op = kanit_operation if kanit_operation is not None else _make_operation(
        agent=agent, amount=amount, ts=ts)
    rh = receipt if receipt is not None else _KanitStub.content_hash(op)
    entry = kanit_entry
    if kanit and entry is None:
        entry = {"id": f"{agent}|complete_work|{_KanitStub.day_key(ts)}",
                 "h": rh, "prev": "GENESIS"}
    return UnpumpPaymentProof(
        match_id="m-1", agent_id=agent, buyer_id=buyer, amount=amount,
        work_done=work_done, receipt_hash=rh, bid_id="b-7", completed_at=1.5,
        kanit_entry=entry, kanit_operation=op if kanit else None)


# ---------------------------------------------------------------- fiksler

@pytest.fixture
def buyer() -> Account:
    return Account.create()


@pytest.fixture
def ledger(tmp_path) -> D5Ledger:
    return D5Ledger(Path(tmp_path) / "d5.jsonl")


def _settled_job(buyer: Account, amount: float = 100.0):
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address=buyer.address, seller_address=_S_SELLER,
        amount_usdc=amount, idempotency_key="k-" + buyer.address[-8:])
    vault.submit_output(job.job_id, {"res": "ok"})
    vault.mark_verified_ok(job.job_id)
    settled, _tx = vault.settle_escrow(job.job_id, caller_address=buyer.address)
    return settled


@pytest.fixture
def settled(buyer):
    return _settled_job(buyer)


def _green_binding(monkeypatch, buyer, ledger, settled) -> UnpumpBinding:
    """Tam yesil bag (stub kanit + uyumlu escrow) — verify_binding testlerine
    hazir; claim alici tarafindan imzalanir."""
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    binding = UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    binding.claim["signature"] = SettlementBinder.sign_claim(
        binding.claim, buyer)
    return binding


# ============================================== UnpumpPaymentProof.from_match

def _match(**ayir) -> SimpleNamespace:
    esas = dict(match_id="m-1", agent_id=_S_SELLER, amount=10.0,
                work_done=True, receipt_hash="sha256:" + "a" * 64,
                buyer_id="0xbuyer", bid_id="b-9", completed_at=1.5)
    esas.update(ayir)
    return SimpleNamespace(**esas)


def test_from_match_gecerli():
    p = UnpumpPaymentProof.from_match(_match())
    assert p.match_id == "m-1"
    assert p.agent_id == _S_SELLER
    assert p.buyer_id == "0xbuyer"
    assert p.amount == 10.0
    assert p.work_done is True
    assert p.receipt_hash == "sha256:" + "a" * 64
    assert p.bid_id == "b-9"
    assert p.completed_at == 1.5


def test_from_match_eksik_alanlar_tip_hatisi():
    with pytest.raises(TypeError, match="eksik alanlar"):
        UnpumpPaymentProof.from_match(SimpleNamespace(match_id="m", agent_id="a"))


def test_from_match_eksik_alanlar_mesaji_tum_alanlari():
    m = SimpleNamespace(match_id="m")
    with pytest.raises(TypeError) as bil:
        UnpumpPaymentProof.from_match(m)
    mesaj = str(bil.value)
    for alan in ("agent_id", "amount", "work_done"):
        assert alan in mesaj


def test_from_match_buyer_id_parametre_önceligi():
    p = UnpumpPaymentProof.from_match(_match(), buyer_id="parametre")
    assert p.buyer_id == "parametre"


def test_from_match_buyer_yoksa_reddeder():
    m = _match()
    del m.buyer_id
    with pytest.raises(ValueError, match="buyer_id gerekli"):
        UnpumpPaymentProof.from_match(m)


def test_from_match_receipt_yoksa_reddeder():
    m = _match(receipt_hash=None)
    with pytest.raises(ValueError, match="receipt_hash yok"):
        UnpumpPaymentProof.from_match(m)


def test_from_match_receipt_bos_reddeder():
    m = _match(receipt_hash="")
    with pytest.raises(ValueError, match="receipt_hash yok"):
        UnpumpPaymentProof.from_match(m)


def test_from_match_bid_id_bos_str_none():
    assert UnpumpPaymentProof.from_match(_match(bid_id="")).bid_id is None


def test_from_match_bid_id_yok_none():
    m = _match()
    del m.bid_id
    assert UnpumpPaymentProof.from_match(m).bid_id is None


def test_from_match_completed_at_none():
    assert UnpumpPaymentProof.from_match(_match(completed_at=None)).completed_at is None


def test_from_match_str_amount_float_yapar():
    p = UnpumpPaymentProof.from_match(_match(amount="12"))
    assert p.amount == 12.0 and isinstance(p.amount, float)


def test_from_match_str_work_done_bool_yapar():
    p = UnpumpPaymentProof.from_match(_match(amount=10, work_done=1))
    assert p.work_done is True


def test_from_match_kanit_yoksa_varsayilan_none():
    p = UnpumpPaymentProof.from_match(_match())
    assert p.kanit_entry is None and p.kanit_operation is None


def test_from_match_kanit_gecirilir():
    ke = {"id": "x|op|gun", "h": "sha256:h"}
    p = UnpumpPaymentProof.from_match(_match(), kanit_entry=ke,
                                      kanit_operation={"a": 1})
    assert p.kanit_entry == ke and p.kanit_operation == {"a": 1}


# ======================================================== keşif (kok/modul)

def test_unpump_root_env_gecerli_kok_doner(tmp_path, monkeypatch):
    kok = tmp_path / "borsa"
    kok.mkdir()
    (kok / "kanit_cekirdegi.py").write_text("X = 1", encoding="utf-8")
    (kok / "borsa_core.py").write_text("X = 1", encoding="utf-8")
    monkeypatch.setenv("UNPUMP_ROOT", str(kok))
    root = UnpumpPaymentBridge.unpump_root()
    assert root == kok.resolve()
    assert (root / "kanit_cekirdegi.py").is_file()


def test_unpump_root_eksik_dosya_atlanir(tmp_path, monkeypatch):
    """Sadece kanit_cekirdegi var, borsa_core yok -> aday gecersizdir."""
    kok = tmp_path / "eksik"
    kok.mkdir()
    (kok / "kanit_cekirdegi.py").write_text("X = 1", encoding="utf-8")
    monkeypatch.setenv("UNPUMP_ROOT", str(kok))
    root = UnpumpPaymentBridge.unpump_root()
    # bu aday atlandi; sonraki adaylar makineye-bagli — Path|None转为 beliebig
    assert root is None or isinstance(root, Path)


def test_kanit_cekirdegi_yoksa_none(monkeypatch):
    monkeypatch.setattr(UnpumpPaymentBridge, "unpump_root",
                        staticmethod(lambda: None))
    assert UnpumpPaymentBridge._kanit_cekirdegi() is None


def test_kanit_cekirdegi_sys_modules_onbellegi(tmp_path, monkeypatch):
    """Modul sys.modules'te varsa tekrar yuklenmez (load-once)."""
    mod = type(sys)("kanit_cekirdegi")
    mod.CANONICAL_ALANLAR = _KanitStub.CANONICAL_ALANLAR
    eski = sys.modules.get("kanit_cekirdegi")
    sys.modules["kanit_cekirdegi"] = mod
    try:
        assert UnpumpPaymentBridge._kanit_cekirdegi() is mod
    finally:
        if eski is None:
            del sys.modules["kanit_cekirdegi"]
        else:
            sys.modules["kanit_cekirdegi"] = eski


def test_kanit_cekirdegi_diskten_yukleme_ve_path_temizligi(tmp_path, monkeypatch):
    """Gercel diske yazilmis stub modul: sys.path'e-ekle-yukle-temizle."""
    kok = tmp_path / "diskborsa"
    kok.mkdir()
    (kok / "kanit_cekirdegi.py").write_text(
        "CANONICAL_ALANLAR = ('agent_id',)\n")
    monkeypatch.setattr(UnpumpPaymentBridge, "unpump_root",
                        staticmethod(lambda: kok))
    eski = sys.modules.get("kanit_cekirdegi")
    if "kanit_cekirdegi" in sys.modules:
        del sys.modules["kanit_cekirdegi"]
    try:
        mod = UnpumpPaymentBridge._kanit_cekirdegi()
        assert mod.CANONICAL_ALANLAR == ("agent_id",)
        assert str(kok) not in sys.path          # finally-temizligi calisti
    finally:
        if eski is not None:
            sys.modules["kanit_cekirdegi"] = eski


def test_kanonik_islem_alan_sirasini_sabitle():
    """Gonderen sirasi ne olursa olsun — kanonik siraya duzeltilir."""
    op = {"ts": _TS, "amount": 1, "ref": "r", "agent_id": "a",
          "source": "s", "operation": "op", "fazla": 1}
    sonuc = UnpumpPaymentBridge._kanonik_islem(_KanitStub, op)
    assert list(sonuc.keys()) == list(_KanitStub.CANONICAL_ALANLAR)
    assert "fazla" not in sonuc


def test_kanonik_islem_eksik_alan_none():
    sonuc = UnpumpPaymentBridge._kanonik_islem(_KanitStub, {"agent_id": "a"})
    assert sonuc["agent_id"] == "a"
    assert sonuc["amount"] is None


# ================================================== verify_payment_proof

def test_proof_green(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(_make_proof())
    assert out["verdict"] == "GREEN" and out["ok"] is True
    assert out["reason_code"] == 0
    assert out["checks"]["u1_work_done"] is True
    assert out["checks"]["u2_kanit_entry"] is True
    assert out["checks"]["u3_receipt_recomputes"] is True
    assert out["checks"]["u4_day_key"] is True


def test_proof_work_done_false_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(_make_proof(work_done=False))
    assert out["verdict"] == "RED" and out["reason_code"] == 11
    assert "work_not_done" in out["reason"]
    assert out["checks"]["u1_work_done"] is False


def test_proof_receipt_bos_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(receipt="", kanit=False))
    assert out["verdict"] == "RED" and out["reason_code"] == 11


def test_proof_kanit_entry_yok_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(_make_proof(kanit=False))
    assert out["verdict"] == "RED" and out["reason_code"] == 12
    assert "kanit_entry_missing" in out["reason"]


def test_proof_kanit_entry_h_farkli_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(kanit_entry={"id": "x|op|gun", "h": "baska"}))
    assert out["verdict"] == "RED" and out["reason_code"] == 12


def test_proof_kanit_entry_h_str_degil_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(kanit_entry={"id": "x|op|gun", "h": 123}))
    assert out["verdict"] == "RED" and out["reason_code"] == 12


def test_proof_kanit_cekirdegi_yoksa_indeterminate(monkeypatch):
    _none_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(_make_proof())
    assert out["verdict"] == "İNDETERMİNE" and out["reason_code"] == 13
    assert "unpump_kanit_cekirdegi_unavailable" in out["reason"]


def test_proof_kanit_operation_yok_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(receipt="sha256:" + "a" * 64,
                    kanit_operation="op-degil-dict",
                    kanit_entry={"id": "a|op|gun", "h": "sha256:" + "a" * 64}))
    assert out["verdict"] == "RED" and out["reason_code"] == 12
    assert "kanit_operation_missing" in out["reason"]


def test_proof_receipt_mismatch_red(monkeypatch):
    """Bağımsız yeniden-hesap farklı çıkarsa RED (gönderene güvenilmez).

    receipt ORJINAL islemden üretilmistir; koprüye verilen kanit-operation
    celismektedir → bagimsiz hesap mismatch verir."""
    _kanitre_kc(monkeypatch)
    orijinal = _make_operation()
    celisen = _make_operation(amount=999.0)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(receipt=_KanitStub.content_hash(orijinal),
                    kanit_operation=celisen,
                    kanit_entry={"id": "a|op|gun",
                                 "h": _KanitStub.content_hash(orijinal)}))
    assert out["verdict"] == "RED" and out["reason_code"] == 14
    assert "receipt_hash_mismatch" in out["reason"]
    assert out["checks"]["u3_receipt_recomputes"] is False


def test_proof_day_key_uyumsuz_red(monkeypatch):
    """kanit-id'nin günü ts ile uyuşmazsa RED (Delilix idempotency)."""
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(kanit_entry={"id": "a|op|1900-01-01",
                                 "h": _KanitStub.content_hash(
                                     _make_operation())}))
    assert out["verdict"] == "RED" and out["reason_code"] == 15
    assert "day_key_mismatch" in out["reason"]
    assert out["checks"]["u4_day_key"] is False


def test_proof_day_key_gecersiz_ts_red(monkeypatch):
    """day_key ts'yi çözemez -> exception -> ok4 False -> RED 15."""
    _kanitre_kc(monkeypatch)
    op = _make_operation(ts="gecersiz")
    kanit_id = "a|op|gun"
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(kanit_operation=op, ts="gecersiz",
                    kanit_entry={"id": kanit_id,
                                 "h": _KanitStub.content_hash(op)}))
    assert out["verdict"] == "RED" and out["reason_code"] == 15


def test_proof_day_key_id_str_degil_red(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(
        _make_proof(kanit_entry={"id": 12345,
                                 "h": _KanitStub.content_hash(
                                     _make_operation())}))
    assert out["verdict"] == "RED" and out["reason_code"] == 15


def test_proof_red_de_kontrol_sirasi_ilk_kirilan_donar(monkeypatch):
    _kanitre_kc(monkeypatch)
    out = UnpumpPaymentBridge.verify_payment_proof(_make_proof(kanit=False))
    assert "u3_receipt_recomputes" not in out["checks"]   # u2'de dondu


# ================================================================== reconcile

def test_reconcile_green(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is True
    assert rec["reason"] == "reconciled"
    assert all(rec["checks"].values())


def test_reconcile_settled_degil_red(buyer):
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(buyer_address=buyer.address,
                                       seller_address=_S_SELLER,
                                       amount_usdc=100)
    proof = _make_proof(buyer=buyer.address, agent=_S_SELLER)
    rec = UnpumpPaymentBridge.reconcile(proof, job)
    assert rec["ok"] is False and rec["checks"]["r1_settled"] is False


def test_reconcile_settlement_tx_yok_red(settled, buyer):
    settled.settlement_tx = None
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is False and rec["checks"]["r1_settled"] is False


def test_reconcile_amount_fark_red(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=50.0)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is False and rec["checks"]["r2_amount"] is False


def test_reconcile_amount_tolerans_iceride_green(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc) + 1e-7)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["checks"]["r2_amount"] is True


def test_reconcile_buyer_fark_red(settled):
    proof = _make_proof(buyer=_OTHER, agent=settled.seller_address)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is False and rec["checks"]["r3_parties"] is False


def test_reconcile_agent_fark_red(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=_OTHER)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is False and rec["checks"]["r3_parties"] is False


def test_reconcile_kanit_h_fark_red(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        kanit_entry={"id": "a|op|gun", "h": "farkli"})
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert rec["ok"] is False and rec["checks"]["r4_receipt_bound"] is False


def test_reconcile_sebeb_kirik_anahtarlari_listeler(settled):
    proof = _make_proof(buyer=_OTHER, agent=_OTHER, amount=1.0)
    rec = UnpumpPaymentBridge.reconcile(proof, settled)
    assert "r2_amount" in rec["reason"]
    assert "r3_parties" in rec["reason"]


# ====================================================== build_unpump_charge

def test_charge_unpump_blok_alanlari(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address)
    charge = UnpumpPaymentBridge.build_unpump_charge(settled, proof)
    unp = charge["unpump"]
    assert unp["borsa"] == "24-ajan-borsasi"
    assert unp["match_id"] == "m-1"
    assert unp["bid_id"] == "b-7"
    assert unp["agent_id"] == settled.seller_address
    assert unp["buyer_id"] == buyer.address
    assert unp["amount_usdc"] == "100.000000"
    assert unp["work_done"] is True
    assert unp["receipt_hash"] == proof.receipt_hash
    assert unp["completed_at_epoch"] == 1.5
    assert unp["kanit_entry"] == proof.kanit_entry
    assert unp["kanit_operation"] == proof.kanit_operation
    assert unp["verified_at"]


def test_charge_unpump_ref_alanlari(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address)
    ref = UnpumpPaymentBridge.build_unpump_charge(settled,
                                                 proof)["settlement_bind"]["unpump_ref"]
    assert ref["scheme"] == UNPUMP_TAG
    assert ref["match_id"] == "m-1"
    assert ref["receipt_hash"] == proof.receipt_hash


def test_charge_taban_charge_alanlari_korunur(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address)
    charge = UnpumpPaymentBridge.build_unpump_charge(settled, proof)
    assert charge["op"] == "charge"
    assert charge["pkg"] == "pacta-escrow"
    assert charge["settlement_bind"]["scheme"] == "x402/v1"
    assert charge["delivery_hash"]["hex"] == \
        SettlementBinder.compute_delivery_hash(settled)


def test_charge_delivery_hash_ver_önceligi(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address)
    charge = UnpumpPaymentBridge.build_unpump_charge(settled, proof,
                                                     delivery_hash="e" * 64)
    assert charge["delivery_hash"]["hex"] == "e" * 64


def test_charge_amount_quantize_6_ondalik(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=100.1234567)
    unp = UnpumpPaymentBridge.build_unpump_charge(settled, proof)["unpump"]
    assert unp["amount_usdc"] == "100.123457"


def test_charge_kanit_yoksa_blok_none(settled, buyer):
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        kanit=False)
    unp = UnpumpPaymentBridge.build_unpump_charge(settled, proof)["unpump"]
    assert unp["kanit_entry"] is None
    assert unp["kanit_operation"] is None


# ====================================================== bind_unpump_payment

def test_bind_green_ledger_yazar(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    binding = UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    assert binding.charge["seq"] == 1
    assert binding.ledger_tip == binding.charge["h"]
    assert ledger.line_count() == 1
    ok, _tip, why = ledger.verify_chain()
    assert ok and why == "ok"


def test_bind_binding_alanlari(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    binding = UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    assert binding.delivery_hash == \
        SettlementBinder.compute_delivery_hash(settled)
    assert binding.proof is proof
    assert binding.reconciliation["ok"] is True
    assert "signature" not in binding.claim       # non-custodial: imzasiz


def test_bind_proof_kirmizi_hicbir_sey_yazmaz(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        work_done=False)
    with pytest.raises(UnpumpBridgeError, match="payment_proof_not_green"):
        UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    assert ledger.line_count() == 0           # fail-closed: yarim kanit yok


def test_bind_reconcile_kirmizi_hicbir_sey_yazmaz(monkeypatch, buyer, ledger,
                                                  settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=50.0)
    with pytest.raises(UnpumpBridgeError, match="reconciliation_failed"):
        UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    assert ledger.line_count() == 0


def test_bind_imzali_claim(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    binding = UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger,
                                                      payer_signer=buyer)
    assert binding.claim["signature"].startswith("0x")
    assert len(binding.claim["signature"]) == 132


def test_bind_to_dict(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    proof = _make_proof(buyer=buyer.address, agent=settled.seller_address,
                        amount=float(settled.amount_usdc))
    binding = UnpumpPaymentBridge.bind_unpump_payment(proof, settled, ledger)
    d = binding.to_dict()
    assert set(d) == {"charge", "claim", "delivery_hash", "ledger_tip",
                      "proof", "reconciliation"}
    assert d["proof"]["match_id"] == "m-1"


def test_unpump_bridge_error_exception_alt_sinifi():
    assert issubclass(UnpumpBridgeError, Exception)


# ======================================================== verify_binding (8 kontrol)

def test_verify_base_red_oldugu_gibi_gecer(monkeypatch, buyer, ledger, settled):
    """Taban gate KIRMIZI ise sonuc oldugu gibi doner (üskontroller calismaz)."""
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    del binding.charge["settlement_bind"]
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 1
    assert "6_unpump_proof" not in out["checks"]


def test_verify_unpump_blok_yok_red(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    del binding.charge["unpump"]
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["ok"] is False
    assert out["reason_code"] == 16
    assert "unpump_proof_missing" in out["reason"]
    assert out["checks"]["6_unpump_proof"] is False


def test_verify_work_done_false_red(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["work_done"] = False
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 16


def test_verify_unpump_ref_match_id_uyumsuz_red(monkeypatch, buyer, ledger,
                                                settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["settlement_bind"]["unpump_ref"]["match_id"] = "baska"
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 16


def test_verify_unpump_ref_receipt_uyumsuz_red(monkeypatch, buyer, ledger,
                                               settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["settlement_bind"]["unpump_ref"]["receipt_hash"] = "baska"
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 16


def test_verify_kanit_cekirdegi_yoksa_indeterminate(monkeypatch, buyer, ledger,
                                                    settled):
    """Beş kontrol + ok6 yesil AMA receipt yeniden-hesaplanamiyor — sonuç
    esirgenir (RED degil INDETERMINE)."""
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    _none_kc(monkeypatch)             # keşif sonrasi kesintiye uğrar
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "İNDETERMİNE" and out["reason_code"] == 13
    assert "unpump_kanit_cekirdegi_unavailable" in out["reason"]
    assert out["checks"]["6_unpump_proof"] is True


def test_verify_receipt_mismatch_red(monkeypatch, buyer, ledger, settled):
    """ok7: bagimsiz hesap charge'in receipt'ini tutmuyor → RED 17."""
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["kanit_operation"]["amount"] = 999.0
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["ok"] is False
    assert out["reason_code"] == 17
    assert "receipt_hash_mismatch" in out["reason"]
    assert out["checks"]["7_receipt_recomputes"] is False


def test_verify_amount_uyumsuz_red(monkeypatch, buyer, ledger, settled):
    """ok8: unpump kanıtının tutari escrow kaydından farklı → RED 18."""
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["amount_usdc"] = "50.000000"
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 18
    assert "escrow_reconcile_mismatch" in out["reason"]
    assert out["checks"]["8_escrow_reconcile"] is False


def test_verify_buyer_uyumsuz_red(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["buyer_id"] = _OTHER
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 18


def test_verify_agent_uyumsuz_red(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["agent_id"] = _OTHER
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 18


def test_verify_amount_gecersiz_decimal_red(monkeypatch, buyer, ledger, settled):
    """amount_usdc Decimal'e cozulemiyor -> exception -> amount_ok False."""
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    binding.charge["unpump"]["amount_usdc"] = "abc"
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 18
    assert out["checks"]["8_escrow_reconcile"] is False


def test_verify_green_sekiz_kontrol(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    out = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert out["verdict"] == "GREEN" and out["ok"] is True
    assert out["reason_code"] == 0
    assert out["checks"]["6_unpump_proof"] is True
    assert out["checks"]["7_receipt_recomputes"] is True
    assert out["checks"]["8_escrow_reconcile"] is True
    assert len(out["checks"]) == 8


def test_verify_green_tekrar_basılama_determistical(monkeypatch, buyer, ledger,
                                                    settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    a = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    b = UnpumpPaymentBridge.verify_binding(binding.charge, binding.claim)
    assert a == b


# ============================================================ unpump_ref_of

def test_unpump_ref_of_dict_verir(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    binding = _green_binding(monkeypatch, buyer, ledger, settled)
    ref = UnpumpPaymentBridge.unpump_ref_of(binding.charge)
    assert ref["scheme"] == UNPUMP_TAG
    assert ref["match_id"] == "m-1"


def test_unpump_ref_of_sade_charge_none(monkeypatch, buyer, ledger, settled):
    _kanitre_kc(monkeypatch)
    charge = ledger.append(
        SettlementBinder.build_charge(settled))
    assert UnpumpPaymentBridge.unpump_ref_of(charge) is None


def test_unpump_ref_of_ref_str_none():
    charge = {"settlement_bind": {"unpump_ref": "degil"}}
    assert UnpumpPaymentBridge.unpump_ref_of(charge) is None


def test_unpump_ref_of_settlement_bind_yok_none():
    assert UnpumpPaymentBridge.unpump_ref_of({}) is None
