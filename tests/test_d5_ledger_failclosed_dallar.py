"""tamga_d5 D5Ledger + SettlementBinder dal-kesen testleri (LEED).

Kapsanan modul: pacta/integrations/tamga_d5.py
  - D5Ledger: append/head/verify_chain/records/line_count fail-closed dallari
  - SettlementBinder: delivery_artifact/build_charge/build_claim/sign_claim/
    bind_settled_job/_recover_signer/_d5_triple_ok/verify_binding (RFC-010
    bes-kontrol + submitter kontrolu) tum basari/basarisiz/sinir dallari

Kural-1: mevcut testlere/conftest'e/uretime DOKUNULMADI — SADECE bu yeni
dosya eklendi.
Saf-bellek: yerel eth_account/eth_keys anahtarlari + D5Ledger(tmp_path) —
ag/DNS/socket/gercek-subprocess YOK.
"""
import hashlib
import json
from pathlib import Path

import pytest
from eth_account import Account
from eth_keys import keys as eth_keys

from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import (
    DELIVERY_ALG,
    GENESIS_PREV,
    PACTA_SCHEME,
    SUPPORTED_SCHEMES,
    D5Ledger,
    D5LedgerError,
    SettlementBinder,
    _signer_address,
)
from pacta.integrations.tamga_jcs import jcs
from pacta.models import EscrowStatus, TamgaExecutionReceipt

_SELLER = "0x" + "22" * 20
_OTHER = "0x" + "33" * 20


# ---------------------------------------------------------------- fiksler

@pytest.fixture
def buyer() -> Account:
    return Account.create()


@pytest.fixture
def ledger(tmp_path) -> D5Ledger:
    return D5Ledger(Path(tmp_path) / "d5.jsonl")


def _settled_job(buyer: Account, amount: float = 100.0):
    """Saf-bellek solve: vault uzerinde tam akis — settled is uretir."""
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(
        buyer_address=buyer.address, seller_address=_SELLER,
        amount_usdc=amount, idempotency_key="k-" + buyer.address[-8:])
    vault.submit_output(job.job_id, {"res": "ok"})
    vault.mark_verified_ok(job.job_id)
    settled, _tx = vault.settle_escrow(job.job_id, caller_address=buyer.address)
    return settled


@pytest.fixture
def settled(buyer):
    return _settled_job(buyer)


@pytest.fixture
def green(buyer, ledger, settled):
    """旗舰店 GREEN bag: ucretlendirilmis charge + imzali claim (ledger'da)."""
    binding = SettlementBinder.bind_settled_job(settled, ledger,
                                                payer_signer=buyer)
    return binding


def _receipt(job_id="j1") -> TamgaExecutionReceipt:
    return TamgaExecutionReceipt(
        job_id=job_id, program_hash="p" * 64, input_commitment="i" * 64,
        output_hash="o" * 64, wasi_trace_root="w" * 64, instruction_count=7,
        timestamp_epoch=1, signature="s" * 130)


def _write_raw(path: Path, lines):
    """Ledger dosyasina birkac satir yaz (dict -> jcs-benzeri json)."""
    with open(path, "a", encoding="utf-8") as f:
        for ln in lines:
            f.write((json.dumps(ln, sort_keys=True) if isinstance(ln, dict)
                     else ln) + "\n")


def _recompute_h(rec: dict) -> str:
    no_h = {k: v for k, v in rec.items() if k not in ("h", "node_sig")}
    return hashlib.sha256(rec["prev"].encode("utf-8") + jcs(no_h)).hexdigest()


# ================================================================ D5Ledger
# --- append: temel ----------------------------------------------------------------

def test_append_ilk_kayit_seq_1(ledger):
    rec = ledger.append({"op": "charge", "kind": "settlement"})
    assert rec["seq"] == 1


def test_append_ilk_kayit_prev_genesis(ledger):
    rec = ledger.append({"op": "charge"})
    assert rec["prev"] == GENESIS_PREV
    assert rec["prev"] == "0" * 64


def test_append_h_64_hex_kucuk(ledger):
    rec = ledger.append({"op": "charge"})
    assert isinstance(rec["h"], str)
    assert len(rec["h"]) == 64
    assert all(c in "0123456789abcdef" for c in rec["h"])


def test_append_ikinci_kayit_onceki_h_ya_zincirlenir(ledger):
    first = ledger.append({"op": "charge"})
    second = ledger.append({"op": "verify"})
    assert second["seq"] == 2
    assert second["prev"] == first["h"]


def test_append_ucuncu_kayit_zinciri_korur(ledger):
    a = ledger.append({"op": "a"})
    b = ledger.append({"op": "b"})
    c = ledger.append({"op": "c"})
    assert c["prev"] == b["h"] and b["prev"] == a["h"]


def test_append_h_bagimsiz_yeniden_hesaplanir(ledger):
    rec = ledger.append({"op": "charge", "job_id": "j-1", "ts": "2020-01-01"})
    no_h = {k: v for k, v in rec.items() if k not in ("h", "node_sig")}
    assert rec["h"] == hashlib.sha256(
        rec["prev"].encode("utf-8") + jcs(no_h)).hexdigest()


def test_append_cagirani_mutasyona_uğratmaz(ledger):
    girdi = {"op": "charge", "job_id": "j-1"}
    ledger.append(girdi)
    assert girdi == {"op": "charge", "job_id": "j-1"}
    assert "seq" not in girdi and "h" not in girdi


# --- append: fail-closed ----------------------------------------------------------

def test_append_op_olmazsa_reddeder(ledger):
    with pytest.raises(D5LedgerError, match="op_required"):
        ledger.append({"kind": "settlement"})


def test_append_bos_op_reddeder(ledger):
    with pytest.raises(D5LedgerError, match="op_required"):
        ledger.append({"op": ""})


def test_append_dict_degilse_reddeder(ledger):
    with pytest.raises(D5LedgerError, match="record_not_dict"):
        ledger.append(["op"])
    with pytest.raises(D5LedgerError, match="record_not_dict"):
        ledger.append("op")


def test_append_ts_yoksa_varsayilan_atar(ledger):
    rec = ledger.append({"op": "charge"})
    assert "ts" in rec and isinstance(rec["ts"], str) and rec["ts"]


def test_append_cagirandan_ts_korur(ledger):
    rec = ledger.append({"op": "charge", "ts": "2020-02-02T00:00:00+0000"})
    assert rec["ts"] == "2020-02-02T00:00:00+0000"


def test_append_node_sig_hashlenmez(ledger):
    """node_alanı h-disinde degil — imza alani olsa zincir bozulmaz."""
    rec = ledger.append({"op": "charge", "node_sig": "sig-abc"})
    no_h = {k: v for k, v in rec.items() if k not in ("h", "node_sig")}
    exp = hashlib.sha256(rec["prev"].encode("utf-8") + jcs(no_h)).hexdigest()
    assert rec["h"] == exp
    tip, why = ledger.head()
    assert why == "ok" and tip == rec["h"]


def test_append_olmayan_ust_klasoru_olusturur(tmp_path):
    hedef = Path(tmp_path) / "a" / "b" / "ledger.jsonl"
    lg = D5Ledger(hedef)
    rec = lg.append({"op": "charge"})
    assert hedef.exists()
    assert rec["seq"] == 1


def test_append_dosyaya_satir_yazar(ledger):
    rec = ledger.append({"op": "charge"})
    icerik = ledger.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(icerik) == 1
    assert json.loads(icerik[0])["h"] == rec["h"]


# --- append: kuyruk tarama --------------------------------------------------------

def test_append_bos_satirlari_atlar_saymaz(ledger):
    """Tarama bos satirlari saymaz — yeni kayit seq=2 olur."""
    ledger.append({"op": "charge"})
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("\n")
    assert ledger.append({"op": "verify"})["seq"] == 2


def test_append_bos_dosyadan_seq_1(ledger):
    ledger.path.write_text("", encoding="utf-8")
    assert ledger.append({"op": "charge"})["seq"] == 1


def test_append_bos_satirlar_dosyasi_bos_kabul(ledger):
    """Yalnizca bos satirlar -> n=0 -> prev=genesis."""
    ledger.path.write_text("\n\n\n", encoding="utf-8")
    rec = ledger.append({"op": "charge"})
    assert rec["seq"] == 1 and rec["prev"] == GENESIS_PREV


def test_append_bosuk_satir_sayilir_ama_h_yok(ledger):
    """Bosuk json satiri: n artar, son-gecerli-kayit onceki gecerli h olur."""
    gecerli = ledger.append({"op": "charge"})
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("BOSUK-JSON{\n")
    rec = ledger.append({"op": "verify"})
    assert rec["seq"] == 3          # 1 gecerli + 1 bosuk sayildi
    assert rec["prev"] == gecerli["h"]


def test_append_tumu_bosuk_tail_fail_closed(ledger):
    """Kuyrukta gecerli h yok (n>0, last=None) -> D5LedgerError (kirma-yok)."""
    ledger.path.write_text("BOSUK1\nBOSUK2\n", encoding="utf-8")
    with pytest.raises(D5LedgerError, match="ledger_broken"):
        ledger.append({"op": "charge"})


def test_append_h_var_ama_prev_kirik_ekler_dokumanda_kirik_kalir(ledger):
    """GERCEK DAVRANIS (bulgu PACTA-1): append yalnizca 'h' varligina bakar —
    prev-zincirini DOGRULAMAZ. Docstring'i ('kırık zincirin ardına eklenmez')
    ile celisir: kirik kuyruk 'h' tasiyorsa ekleme yapilir ve head() yine
    'broken' raporlar. Bu test mevcut davranisi sabitler (uretime DOKUNMA)."""
    rec = ledger.append({"op": "charge"})
    kirik = dict(rec)
    kirik["prev"] = "f" * 64
    kirik["h"] = _recompute_h(kirik)
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write(json.dumps(kirik, sort_keys=True) + "\n")
    yeni = ledger.append({"op": "verify"})
    assert yeni["seq"] == 2 and yeni["prev"] == kirik["h"]
    _, why = ledger.head()
    assert why == "broken@1"   # append kirik zinciri 'tamir etmedi' — izin verdi


def test_append_h_yok_tum_bosuk_tail_fail_closed_kesin(ledger):
    """h-icermeyen bosuk kayitlar (n>0, last=None) -> D5LedgerError (gerçek
    fail-closed; usttekinin aksine burada docstring ile uyumlu)."""
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write('{"op":"charge"}\n')            # h YOK -> last_rec None
        f.write('{"op":"verify"}\n')
    with pytest.raises(D5LedgerError, match="ledger_broken"):
        ledger.append({"op": "charge"})


# --- records / head / verify_chain / line_count ------------------------------------

def test_records_olmayan_dosya_bos_akis(tmp_path):
    lg = D5Ledger(tmp_path / "yok.jsonl")
    assert list(lg.records()) == []


def test_records_bos_satirlari_atlar(ledger):
    ledger.append({"op": "charge"})
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("\n\n")
    assert len(list(ledger.records())) == 1


def test_records_bosuk_satir_sentineI(ledger):
    """Bosuk json -> {} sentinel ( bellek sinirli; fail-closed head'te kirilir)."""
    ledger.append({"op": "charge"})
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("{BOSUK\n")
    recs = list(ledger.records())
    assert recs[0].get("op") == "charge"
    assert recs[1] == {}


def test_head_saglam_zincir_tipi_verir(ledger):
    a = ledger.append({"op": "charge"})
    tip, why = ledger.head()
    assert tip == a["h"] and why == "ok"


def test_head_bos_dosya_ok(ledger):
    ledger.path.write_text("", encoding="utf-8")
    tip, why = ledger.head()
    assert tip == GENESIS_PREV and why == "ok"


def test_head_olmayan_dosya_ok(ledger):
    tip, why = ledger.head()
    assert tip == GENESIS_PREV and why == "ok"


def test_head_prev_uyumsuz_kirma(ledger):
    rec = ledger.append({"op": "charge"})
    kirik = dict(rec)
    kirik["prev"] = "e" * 64
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write(json.dumps(kirik, sort_keys=True) + "\n")
    tip, why = ledger.head()
    assert tip is None and why == "broken@1"


def test_head_h_uyumsuz_kirma(ledger):
    rec = ledger.append({"op": "charge"})
    kirik = dict(rec)
    kirik["kind"] = "degisti"      # no_h icine girer -> exp degisir, h eski
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write(json.dumps(kirik, sort_keys=True) + "\n")
    assert ledger.head() == (None, "broken@1")


def test_head_seq_uyumsuz_kirma(ledger):
    rec = ledger.append({"op": "charge"})
    kirik = dict(rec)
    kirik["seq"] = 99
    kirik["h"] = _recompute_h(kirik)
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write(json.dumps(kirik, sort_keys=True) + "\n")
    assert ledger.head() == (None, "broken@1")


def test_head_ikinci_satirda_kirma_raporu(ledger):
    a = ledger.append({"op": "charge"})
    b = ledger.append({"op": "verify"})
    kirik = dict(b)
    kirik["prev"] = "d" * 64
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write(json.dumps(a, sort_keys=True) + "\n"
                + json.dumps(kirik, sort_keys=True) + "\n")
    assert ledger.head() == (None, "broken@2")


def test_head_dict_olmayan_satir_exception_dali(ledger):
    """json listesi -> rec.get AttributeError -> except -> broken@n."""
    with open(ledger.path, "w", encoding="utf-8") as f:
        f.write("[1, 2, 3]\n")
    assert ledger.head() == (None, "broken@1")


def test_verify_chain_saglam(ledger):
    ledger.append({"op": "charge"})
    ok, tip, why = ledger.verify_chain()
    assert ok is True and why == "ok" and tip is not None


def test_verify_chain_kirik(ledger):
    ledger.path.write_text("corrupt\n", encoding="utf-8")
    ok, tip, why = ledger.verify_chain()
    assert ok is False and tip is None and why == "broken@1"


def test_line_count_bos(ledger):
    assert ledger.line_count() == 0


def test_line_count_kayit_sayar(ledger):
    ledger.append({"op": "charge"})
    ledger.append({"op": "verify"})
    assert ledger.line_count() == 2


def test_line_count_bosuk_satiri_sayar(ledger):
    """Bosuk satir {} sentinel olarak sayilir (line_count records uzerinden)."""
    ledger.append({"op": "charge"})
    with open(ledger.path, "a", encoding="utf-8") as f:
        f.write("{BOSUK\n")
    assert ledger.line_count() == 2


def test_iki_ledger_ayni_dosyada_sirali_zincir(tmp_path):
    """Ayrı D5Ledger ornekleri ayni dosyaya sirayla yazar — seq cakismaz."""
    yol = tmp_path / "paylasim.jsonl"
    a = D5Ledger(yol).append({"op": "charge"})
    b = D5Ledger(yol).append({"op": "charge"})
    assert (a["seq"], b["seq"]) == (1, 2)
    assert b["prev"] == a["h"]


# ====================================================== SettlementBinder
# --- delivery_artifact / compute_delivery_hash --------------------------------------

def test_delivery_artifact_alanlari(buyer, settled):
    art = SettlementBinder.delivery_artifact(settled)
    assert art["job_id"] == settled.job_id
    assert art["status"] == "SETTLED"
    assert art["amount_usdc"] == str(settled.amount_usdc)
    assert art["output_payload"] == {"res": "ok"}
    assert art["settlement_tx"] == settled.settlement_tx
    assert art["settled_at_epoch_ms"] == settled.settled_at_epoch_ms


def test_delivery_artifact_ucret_none_sifir(buyer):
    job = _settled_job(buyer)          # fee_collected dolu olur
    art = SettlementBinder.delivery_artifact(job)
    assert art["fee_usdc"] == str(job.fee_collected_usdc)
    job.fee_collected_usdc = None
    assert SettlementBinder.delivery_artifact(job)["fee_usdc"] == "0"


def test_delivery_artifact_receipt_yoksa_tamga_yok(buyer, settled):
    assert "tamga_output_hash" not in SettlementBinder.delivery_artifact(settled)


def test_delivery_artifact_receipt_varsa_katar(buyer, settled):
    settled.tamga_receipt = _receipt(settled.job_id)
    art = SettlementBinder.delivery_artifact(settled)
    assert art["tamga_output_hash"] == "o" * 64
    assert art["tamga_wasi_trace_root"] == "w" * 64
    assert art["tamga_instruction_count"] == 7


def test_compute_delivery_hash_determinist(buyer, settled):
    h1 = SettlementBinder.compute_delivery_hash(settled)
    h2 = SettlementBinder.compute_delivery_hash(settled)
    assert h1 == h2 and len(h1) == 64


def test_compute_delivery_hash_payload_degisince_degisir(buyer, settled):
    h1 = SettlementBinder.compute_delivery_hash(settled)
    settled.output_payload = {"res": "baska"}
    assert SettlementBinder.compute_delivery_hash(settled) != h1


def test_compute_delivery_hash_jcs_ile_ayni(buyer, settled):
    beklenen = hashlib.sha256(
        jcs(SettlementBinder.delivery_artifact(settled))).hexdigest()
    assert SettlementBinder.compute_delivery_hash(settled) == beklenen


# --- build_charge -------------------------------------------------------------------

def test_build_charge_alanlari(buyer, settled):
    c = SettlementBinder.build_charge(settled)
    assert c["op"] == "charge"
    assert c["pkg"] == "pacta-escrow"
    assert c["kind"] == "settlement"
    assert c["job_id"] == settled.job_id
    assert c["delivery_hash"]["alg"] == DELIVERY_ALG
    assert c["settlement_bind"]["scheme"] == PACTA_SCHEME


def test_build_charge_hash_compute_ile_uyusur(buyer, settled):
    c = SettlementBinder.build_charge(settled)
    assert c["delivery_hash"]["hex"] == \
        SettlementBinder.compute_delivery_hash(settled)
    assert c["settlement_bind"]["claim_evidence_hash"]["hex"] == \
        c["delivery_hash"]["hex"]


def test_build_charge_payment_id_job_id(buyer, settled):
    assert SettlementBinder.build_charge(settled)["settlement_bind"]["payment_id"] \
        == settled.job_id


def test_build_charge_taraflar(buyer, settled):
    bind = SettlementBinder.build_charge(settled)["settlement_bind"]
    assert bind["payer"] == buyer.address
    assert bind["payee"] == _SELLER


def test_build_charge_escrow_blok(buyer, settled):
    esc = SettlementBinder.build_charge(settled)["escrow"]
    assert esc["amount_usdc"] == str(settled.amount_usdc)
    assert esc["settlement_tx"] == settled.settlement_tx
    assert esc["status"] == "SETTLED"


def test_build_charge_63_hex_reddeder(buyer, settled):
    with pytest.raises(ValueError, match="delivery_hash_invalid"):
        SettlementBinder.build_charge(settled, "a" * 63)


def test_build_charge_hex_olmayan_reddeder(buyer, settled):
    with pytest.raises(ValueError, match="delivery_hash_invalid"):
        SettlementBinder.build_charge(settled, "z" * 64)


def test_build_charge_buyuk_hex_kabul(buyer, settled):
    """Dogrulama .lower() uzerinden — BUYUK harf kabul edilir."""
    c = SettlementBinder.build_charge(settled, "AB" * 32)
    assert c["delivery_hash"]["hex"] == "AB" * 32


# --- build_claim / sign_claim / _signer_address -------------------------------------

def test_build_claim_imzasiz_alanlar(buyer, settled):
    claim = SettlementBinder.build_claim(settled)
    assert claim["buyerAddress"] == buyer.address
    assert claim["sellerAddress"] == _SELLER
    assert claim["settlementRef"] == settled.job_id
    assert claim["evidenceHash"]["hex"] == \
        SettlementBinder.compute_delivery_hash(settled)
    assert "signature" not in claim


def test_build_claim_account_ile_imzalar(buyer, settled):
    claim = SettlementBinder.build_claim(settled, payer_signer=buyer)
    assert claim["signature"].startswith("0x")
    assert len(claim["signature"]) == 132


def test_build_claim_bytes_anahtar_ile_imzalar(buyer, settled, ledger):
    raw = bytes(buyer.key)
    claim = SettlementBinder.build_claim(settled, payer_signer=raw)
    assert len(claim["signature"]) == 132
    assert _signer_address(raw).lower() == buyer.address.lower()


def test_build_claim_private_key_ile_imzalar(buyer, settled):
    pk = eth_keys.PrivateKey(bytes(buyer.key))
    claim = SettlementBinder.build_claim(settled, payer_signer=pk)
    assert len(claim["signature"]) == 132


def test_build_claim_yanlis_imzalayan_reddeder(buyer, settled):
    baska = Account.create()
    with pytest.raises(ValueError, match="signer_mismatch"):
        SettlementBinder.build_claim(settled, payer_signer=baska)


def test_sign_claim_desteklenmeyen_tip(buyer, settled):
    with pytest.raises(TypeError, match="unsupported_signer"):
        SettlementBinder.sign_claim({"a": 1}, "anahtar-degil")


def test_sign_claim_bytes_govdesi(buyer, settled):
    claim = SettlementBinder.build_claim(settled)
    sig = SettlementBinder.sign_claim(claim, bytes(buyer.key))
    digest = SettlementBinder._claim_digest(claim)
    assert SettlementBinder._recover_signer(digest, sig).lower() == buyer.address.lower()


def test_sign_claim_eip191_onsekis_yok(buyer, settled):
    """Sözlesme: imza sha256-ozutunun HAM 字節leri uzerinde — EIP-191 prefix YOK."""
    claim = SettlementBinder.build_claim(settled)
    sig = SettlementBinder.sign_claim(claim, buyer)
    beklenen = hashlib.sha256(
        json.dumps({k: v for k, v in claim.items() if k != "signature"},
                   sort_keys=True).encode("utf-8")).hexdigest()
    assert SettlementBinder._claim_digest(claim) == beklenen
    assert SettlementBinder._recover_signer(beklenen, sig).lower() == buyer.address.lower()


def test_signer_address_hesap_tipi_desteklenmez():
    with pytest.raises(TypeError, match="unsupported_signer"):
        _signer_address(12345)


def test_signer_address_bytes_32(buyer):
    assert _signer_address(bytes(buyer.key)).lower() == buyer.address.lower()


# --- bind_settled_job ----------------------------------------------------------------

def test_bind_settled_not_settled_reddeder(buyer, ledger):
    vault = PactaEscrowVault()
    job = vault.create_and_lock_escrow(buyer_address=buyer.address,
                                       seller_address=_SELLER, amount_usdc=10)
    with pytest.raises(ValueError, match="not_settled"):
        SettlementBinder.bind_settled_job(job, ledger)


def test_bind_settled_settlement_tx_yok_reddeder(buyer, ledger, settled):
    settled.settlement_tx = None
    with pytest.raises(ValueError, match="no_settlement_tx"):
        SettlementBinder.bind_settled_job(settled, ledger)


def test_bind_settled_ledgera_yazar(buyer, ledger, settled):
    binding = SettlementBinder.bind_settled_job(settled, ledger)
    assert binding.charge["seq"] == 1
    assert binding.ledger_tip == binding.charge["h"]
    assert binding.ledger_tip is not None
    ok, _tip, why = ledger.verify_chain()
    assert ok and why == "ok"


def test_bind_settled_charge_h_ledgerda(ledger, settled, buyer):
    binding = SettlementBinder.bind_settled_job(settled, ledger, payer_signer=buyer)
    satir = list(ledger.records())[0]
    assert satir["h"] == binding.charge["h"]
    assert satir["op"] == "charge"


def test_bind_settled_imzasiz_claim(buyer, ledger, settled):
    binding = SettlementBinder.bind_settled_job(settled, ledger)
    assert "signature" not in binding.claim


def test_bind_settled_imzali_claim_green_verir(buyer, ledger, settled):
    binding = SettlementBinder.bind_settled_job(settled, ledger,
                                                payer_signer=buyer)
    sonuc = SettlementBinder.verify_binding(binding.charge, binding.claim)
    assert sonuc["verdict"] == "GREEN" and sonuc["ok"] is True


def test_settlement_binding_to_dict(buyer, ledger, settled):
    binding = SettlementBinder.bind_settled_job(settled, ledger,
                                                payer_signer=buyer)
    d = binding.to_dict()
    assert set(d) == {"charge", "claim", "delivery_hash", "ledger_tip"}
    assert d["delivery_hash"] == binding.delivery_hash


# --- _recover_signer / _d5_triple_ok (birim) ------------------------------------------

def test_recover_signer_kotu_hex_none():
    assert SettlementBinder._recover_signer("ab" * 32, "0xZZZZ") is None


def test_recover_signer_tek_hane_hex_none():
    assert SettlementBinder._recover_signer("ab" * 32, "0xabc") is None


def test_recover_signer_kisa_imza_none():
    assert SettlementBinder._recover_signer("ab" * 32, "0x" + "cd" * 64) is None


def test_recover_signer_kotu_v_none():
    """v=0xff -> rec_id 228 -> gecersiz."""
    sig = "0x" + "ab" * 32 + "cd" * 32 + "ff"
    assert SettlementBinder._recover_signer("ab" * 32, sig) is None


def test_recover_signer_gerversiz_rvs_none():
    """r=0 -> BadSignature (recover exception dalini keser)."""
    sig = ("0x" + (0).to_bytes(32, "big").hex() + (1).to_bytes(32, "big").hex()
           + "1b")
    assert SettlementBinder._recover_signer("ab" * 32, sig) is None


def test_recover_signer_gecerli_imza_adres_verir(buyer, settled):
    claim = SettlementBinder.build_claim(settled, payer_signer=buyer)
    d = SettlementBinder._claim_digest(claim)
    assert SettlementBinder._recover_signer(d, claim["signature"]).lower() \
        == buyer.address.lower()


def test_d5_triple_ok_gecerli():
    rec = {"seq": 1, "prev": "a" * 64, "h": "b" * 64}
    assert SettlementBinder._d5_triple_ok(rec) is True


def test_d5_triple_ok_seq_bool_true():
    """bool bir int'tir AMA seq=True gecersiz (tip-siniri)."""
    assert SettlementBinder._d5_triple_ok(
        {"seq": True, "prev": "a" * 64, "h": "b" * 64}) is False


def test_d5_triple_ok_seq_sifir():
    assert SettlementBinder._d5_triple_ok(
        {"seq": 0, "prev": "a" * 64, "h": "b" * 64}) is False


def test_d5_triple_ok_prev_str_degil():
    assert SettlementBinder._d5_triple_ok({"seq": 1, "prev": None,
                                           "h": "b" * 64}) is False


def test_d5_triple_ok_h_kisa():
    assert SettlementBinder._d5_triple_ok(
        {"seq": 1, "prev": "a" * 64, "h": "b" * 63}) is False


def test_d5_triple_ok_h_buyuk_harf():
    assert SettlementBinder._d5_triple_ok(
        {"seq": 1, "prev": "a" * 64, "h": "B" * 64}) is False


def test_d5_triple_ok_prev_harfsiz():
    assert SettlementBinder._d5_triple_ok(
        {"seq": 1, "prev": "z" * 64, "h": "b" * 64}) is False


# --- verify_binding: sart/bytes-öncesi dallar ----------------------------------------

def test_verify_settlement_bind_yoksa_red(buyer, settled, ledger):
    charge = ledger.append(SettlementBinder.build_charge(settled))
    del charge["settlement_bind"]
    out = SettlementBinder.verify_binding(charge, {})
    assert out["verdict"] == "RED" and out["reason_code"] == 1
    assert out["reason"].startswith("settlement_bind_missing")


def test_verify_settlement_bind_str_red(buyer, settled, ledger):
    charge = ledger.append(SettlementBinder.build_charge(settled))
    charge["settlement_bind"] = "degil"
    out = SettlementBinder.verify_binding(charge, {})
    assert out["verdict"] == "RED" and out["reason_code"] == 1


def test_verify_bilinmeyen_scheme_indeterminate(buyer, settled, ledger):
    charge = ledger.append(SettlementBinder.build_charge(settled))
    charge["settlement_bind"]["scheme"] = "bilinmeyen/v9"
    out = SettlementBinder.verify_binding(charge, {})
    assert out["verdict"] == "İNDETERMİNE" and out["reason_code"] == 2
    assert out["reason"].startswith("unknown_scheme")


@pytest.mark.parametrize("scheme", ["tamga/native", "erc8004/v1"])
def test_verify_scheme_disindakiler_indeterminate(buyer, settled, ledger, scheme):
    """Pacta'nin gate'i yalnizca x402/v1 — digerleri Tamga'nin gate'inde."""
    charge = ledger.append(SettlementBinder.build_charge(settled))
    charge["settlement_bind"]["scheme"] = scheme
    out = SettlementBinder.verify_binding(charge, {})
    assert out["verdict"] == "İNDETERMİNE" and out["reason_code"] == 2
    assert out["reason"].startswith("pacta_gate_only_x402v1")


def test_supported_schemes_listesi():
    assert PACTA_SCHEME in SUPPORTED_SCHEMES
    assert "tamga/native" in SUPPORTED_SCHEMES
    assert "erc8004/v1" in SUPPORTED_SCHEMES


# --- verify_binding: kontrol-1 receipt ----------------------------------------------

def _green_charge_claim(buyer, ledger, settled):
    binding = SettlementBinder.bind_settled_job(settled, ledger,
                                                payer_signer=buyer)
    return binding.charge, binding.claim


def test_verify_kontrol1_seq_yoksa_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    del charge["seq"]
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 3
    assert out["reason"] == "receipt_invalid"
    assert out["checks"]["1_receipt"] is False


def test_verify_kontrol1_dh_alg_tanimsiz_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["delivery_hash"]["alg"] = "md5"
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 3


def test_verify_kontrol1_dh_hex_buyuk_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["delivery_hash"]["hex"] = charge["delivery_hash"]["hex"].upper()
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 3


def test_verify_kontrol1_dh_fazla_alan_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["delivery_hash"]["fazla"] = 1
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 3


def test_verify_kontrol1_dh_str_degil_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["delivery_hash"] = "q" * 64
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 3


# --- verify_binding: kontrol-2 claim imza -------------------------------------------

def test_verify_kontrol2_imza_yoksa_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    del claim["signature"]
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4
    assert out["reason"] == "claim_signature_invalid"


def test_verify_kontrol2_imza_str_degil_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["signature"] = 123
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


def test_verify_kontrol2_buyer_str_degil_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["buyerAddress"] = 999
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


def test_verify_kontrol2_yanlis_imzalayan_red(buyer, ledger, settled):
    """Imza gecerli AMA cozulen adres alici degil — fail-closed."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    satici = Account.create()
    claim["signature"] = SettlementBinder.sign_claim(claim, satici)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


def test_verify_kontrol2_imza_kisa_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["signature"] = "0x" + "ab" * 64
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


def test_verify_kontrol2_imza_kotu_v_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["signature"] = "0x" + "ab" * 32 + "cd" * 32 + "ff"
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


def test_verify_kontrol2_imza_gerversiz_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["signature"] = ("0x" + (0).to_bytes(32, "big").hex()
                          + (1).to_bytes(32, "big").hex() + "1b")
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 4


# --- verify_binding: kontrol-3 settlementRef ----------------------------------------

def test_verify_kontrol3_ref_uyumsuz_red(buyer, ledger, settled):
    """Claim govdesi degistinca imza da yenilenmeli — yoksa kontrol-2 RED verir."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["settlementRef"] = "baska-is"
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 5
    assert out["reason"] == "settlement_ref_mismatch"


def test_verify_kontrol3_ref_str_degil_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["settlementRef"] = 123
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 5


def test_verify_kontrol3_ref_yoksa_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    del claim["settlementRef"]
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 5


# --- verify_binding: kontrol-4 taraflar ---------------------------------------------

def test_verify_kontrol4_buyer_uyumsuz_red(buyer, ledger, settled):
    """Buyer-tarafi degistirilmis claim: imza YENI buyer'a cozulur (kontrol-2
    gecer) AMA bind.payer ile uyumsuz → kontrol-4 RED (party_mismatch)."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    diger = Account.create()
    claim["buyerAddress"] = diger.address
    claim["signature"] = SettlementBinder.sign_claim(claim, diger)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 6
    assert out["reason"] == "party_mismatch"


def test_verify_kontrol4_seller_uyumsuz_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["sellerAddress"] = _OTHER
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 6


def test_verify_kontrol4_buyer_buyuk_harf_esnek(buyer, ledger, settled):
    """Karsilastirma .lower() ile — BUYUK harfli adres GREEN kalir."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["buyerAddress"] = claim["buyerAddress"].upper()
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "GREEN"


# --- verify_binding: kontrol-5 evidenceHash -----------------------------------------

def test_verify_kontrol5_alg_uyumsuz_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["evidenceHash"]["alg"] = "keccak256"
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 7
    assert out["reason"] == "evidence_hash_mismatch"


def test_verify_kontrol5_hex_uyumsuz_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["evidenceHash"]["hex"] = "c" * 64
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 7


def test_verify_kontrol5_evidence_yoksa_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    del claim["evidenceHash"]
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 7


def test_verify_kontrol5_evidence_fazla_alan_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["evidenceHash"]["fazla"] = 1
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 7


# --- verify_binding: kontrol-7 submitter --------------------------------------------

def test_verify_kontrol7_submitter_payee_eslesirse_red(buyer, ledger, settled):
    """x402#2887: submitter == payee -> facilitator-merchant conflation RED."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["settlement_bind"]["submitter"] = _SELLER
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 9
    assert "submitter_payee_conflation" in out["reason"]
    assert out["checks"]["7_submitter_payee"] is False


def test_verify_kontrol7_submitter_payee_buyuk_harf_red(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["settlement_bind"]["submitter"] = _SELLER.upper()
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "RED" and out["reason_code"] == 9


def test_verify_kontrol7_submitter_baska_olunca_green(buyer, ledger, settled):
    """submitter != payee (facilitator ayri) -> GREEN + 6 kontrol."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["settlement_bind"]["submitter"] = _OTHER
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "GREEN" and out["ok"] is True
    assert out["checks"]["7_submitter_payee"] is True
    assert len(out["checks"]) == 6


def test_verify_kontrol7_submitter_bos_str_gorulmez(buyer, ledger, settled):
    """submitter="" -> additive-gap: kontrol calismaz, GREEN (5 kontrol)."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["settlement_bind"]["submitter"] = ""
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "GREEN"
    assert "7_submitter_payee" not in out["checks"]


def test_verify_kontrol7_submitter_str_degil_gorulmez(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    charge["settlement_bind"]["submitter"] = None
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["verdict"] == "GREEN"
    assert "7_submitter_payee" not in out["checks"]


# --- verify_binding: GREEN tam akis +Dict dusmesi -----------------------------------

def test_verify_green_bes_kontrol_isaretli(buyer, ledger, settled):
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["checks"] == {"1_receipt": True, "2_claim_sig": True,
                             "3_settlement_ref": True, "4_parties": True,
                             "5_evidence_hash": True}
    assert out["reason_code"] == 0


def test_verify_green_deger_0_kontrol_sirasi(buyer, ledger, settled):
    """fail-closed: ilk RED'de doner — sirali kontrol numaralari teyidi."""
    charge, claim = _green_charge_claim(buyer, ledger, settled)
    claim["sellerAddress"] = _OTHER            # kontrol-4 kirmizi
    claim["evidenceHash"]["hex"] = "c" * 64    # kontrol-5 de kirmizi
    claim["signature"] = SettlementBinder.sign_claim(claim, buyer)
    out = SettlementBinder.verify_binding(charge, claim)
    assert out["reason_code"] == 6             # 4 once dondu, 5 gorulmedi
    assert "5_evidence_hash" not in out["checks"]


def test_verify_cikti_sozlugu_baslangic_hali(buyer, settled, ledger):
    """Hicbir kontrol calismadan once alan hazir (ok=False, verdict=None)."""
    charge = ledger.append(SettlementBinder.build_charge(settled))
    charge["settlement_bind"] = 0              # isinstance False -> RED 1
    out = SettlementBinder.verify_binding(charge, {})
    assert out["ok"] is False and out["checks"] == {}


def test_ledger_error_mesaji():
    with pytest.raises(D5LedgerError):
        raise D5LedgerError("test")
