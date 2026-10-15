"""
Pacta ↔ Tamga D5-ledger bridge — RFC-010 cross-artifact settlement binding.

MESH-BAĞLANTISI ( 03-Pacta ↔ 05_acik_kaynak/TamgaProtocol):

Pacta'nın-escrow-FSM'i fon-akışını-korur-AMA-kararlar **saf-bellekte**-durur
( README-çoğu-sınırlar: "restart-kaybeder; kalıcı-kanıt-katmanı tamga D5'tir").
Bu-modül o-sınırı-kapatır: bir-settlement-tamamlandığında, karar-bir **D5
hash-chain**'ine-sabitlenir ( RFC-003 D5/D7/D8 zincir-kuralı, RFC-8785/JCS
canonicalization-ile) ve ortaya-çıkan **charge**-kaydı + alıcı-taraflı-imzalı
**claim**, RFC-010'ın-beş-kontrolü-ile-bağımsız-olarak-doğrulanabilir:

  1. receipt-verifies        — charge'ın-D5-üçlüsü ( seq/prev/h) + delivery_hash
  2. claim-verifies          — claim-imzası-buyerAddress'e-çözümlenir ( x402/v1)
  3. settlementRef-resolves  — claim.settlementRef == bind.payment_id
  4. payer/payee-match       — claim-tarafları == escrow-tarafları
  5. evidenceHash == receiptHash — bayt-eşit teslimat-özeti

Hiçbiri-tek-başına-yeterli-değil; biri-RED → tümü-RED ( fail-closed; RFC-010-§3).
Bu-"Escrow-FSM-No-Verified-Delivery"-deseninin-kapanışıdır: settlement-artık
"para-hareket-etti"-demek-değil, "TESLİMAT-kanıtlandı-ve-sabitle"-demektir.

UYGULAMA-NOTLARI ( dürüst):
  * Yalnızca-``x402/v1``-üretilir-ve-doğrulanır ( EVM-benzeri-adresler-imzalar).
    ``tamga/native``-ve-``erc8004/v1``-için-Pacta'nın-gate'i-İNDETERMİNE-döner —
    o-kanalların-doğrulama-sözleşmeleri-Tamga'nın-kendi-gate'indedir
    ( tools/settlement_bind_verify.py); tekrar-etmek-yerine-onu-kullanın.
  * Değer-transferi-YOK: bağ-**kararın-taahhüdünü**-sabitler ( tıpkı-ChainAnchor
    gibi); fon-akışı-hâlâ-vault-ledger'ındadır.
  * Vault-müşterinin-özel-anahtarını-TUTMAZ ( non-custodial): charge-kaydını
    yazar; claim'i-alıcı-imzalar ( ``build_claim(..., payer_signer=...)``).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple, Union

from pacta.integrations.tamga_jcs import jcs
from pacta.models import EscrowJob, EscrowStatus

GENESIS_PREV = "0" * 64
SUPPORTED_SCHEMES = ("x402/v1", "tamga/native", "erc8004/v1")
PACTA_SCHEME = "x402/v1"          # EVM-benzeri-adresler-için-RFC-010-kanalı
DELIVERY_ALG = "sha256"


class D5LedgerError(Exception):
    """D5-ledger yazım/hata-kapasitesi-hatası ( fail-closed-sinyali)."""


class D5Ledger:
    """Tamga D5 hash-chain ledger ( RFC-003 D5/D7/D8) — append + streaming-verify.

    Zincir-kuralı, Tamga'nın-``tamga_runner._verify_chain``'i ile-BİREBİT:

        h = sha256( prev ‖ jcs( kayıt, h-ve-node_sig-hariç) )
        seq = 1-based-satır-numarası ,  prev("0"*64) = genesis

    Append fail-closed'dur: dosyada-satır-var-AMA-geçerli-bir-head-yoksa
    ( kırık-zincir) ekleme-RED — kırık-kuyruğun-ardına-eklemek-zinciri-gizlice
    "tamir-etmiş"-gibi-görünürdü. Aynı-sebepten-dosya-başına-lock ile-oku→belirle→
    yaz-atomik-tutulur ( paralel-çağrılar-AYNI-seq+prev'i-yazamaz).
    """

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # --- okuma-yolu ------------------------------------------------------
    def records(self) -> Iterator[dict]:
        """Ledger'ı-akış-olarak-oku ( tamdosya-yükleme-YOK — F19-disiplini).

        Bozuk/çok-büyük-satır → ``{}``-sentineli: prev/seq-kontrolü-onu-kırık
        işaretler ( fail-closed), bellek-sınırlı-kalır. Dosya-yoksa-boş-akış
        ( mevcut-olmayan-ledger = geçerli-pre-genesis-durumu — Tamga-D7-ile-aynı).
        """
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    yield {}

    def head(self) -> Tuple[Optional[str], str]:
        """Zinciri-streaming-doğrula → ( tip-h|None, reason). reason=="ok" ⇒ sağlam."""
        prev_h, n = GENESIS_PREV, 0
        try:
            for rec in self.records():
                n += 1
                no_h = {k: v for k, v in rec.items() if k not in ("h", "node_sig")}
                exp = hashlib.sha256(
                    str(rec.get("prev", "")).encode("utf-8") + jcs(no_h)).hexdigest()
                if (rec.get("prev") != prev_h or rec.get("h") != exp
                        or rec.get("seq") != n):
                    return None, f"broken@{n}"
                prev_h = rec["h"]
        except Exception:
            return None, f"broken@{n}"
        return prev_h, "ok"

    def verify_chain(self) -> Tuple[bool, Optional[str], str]:
        """Denetim-için-kısa-yol: ( sağlam-mı, tip, reason)."""
        tip, why = self.head()
        return (why == "ok"), tip, why

    # --- yazma-yolu ------------------------------------------------------
    def append(self, rec: dict) -> dict:
        """Kaydı-zincire-ekle ( seq+prev+h-atar); yazılan-satırı-döndürür.

        ``op``-alanı-zorunludur ( RFC-003-op-taksonomisi; op'suz-kayıt-opaktır).
        Kırık-kuyruk → ``D5LedgerError`` ( fail-closed).
        """
        if not isinstance(rec, dict):
            raise D5LedgerError(f"record_not_dict: {type(rec).__name__}")
        if not rec.get("op"):
            raise D5LedgerError("op_required: RFC-003 kayıtları bir op taşır")
        with self._lock:
            last_rec, prev_rec, n = None, None, 0
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        n += 1
                        try:
                            cand = json.loads(line)
                            if cand.get("h"):
                                prev_rec = last_rec
                                last_rec = cand
                        except Exception:
                            pass            # sayılır-AMA-h-yok → son-geçerli-kalır
            if last_rec is None and n > 0:
                raise D5LedgerError(
                    "ledger_broken: kuyrukta geçerli head yok — kırık zincirin "
                    "ardına eklenmez (fail-closed)")
            # PACTA-1 (DUZELTILDI): docstring-'kırık-zincirin-ardına-eklenmez'
            # sozunu-eski-kod-sadece-'h'-varligina-bakarak-ihlal-ediyordu —
            # elle-kirik-prev'li-ama-'h'-tasiyan-kuyruk-geciyordu. Artik-son-
            # kaydinin-h-degeri-yeniden-hesaplanip-karsilastirilir ( self-
            # consistent-head-yoksa-fail-closed).
            if last_rec is not None:
                _l_no_h = {k: v for k, v in last_rec.items()
                           if k not in ("h", "node_sig")}
                _l_h = hashlib.sha256(
                    str(last_rec.get("prev", "")).encode("utf-8")
                    + jcs(_l_no_h)).hexdigest()
                _l_prev_expected = (prev_rec["h"] if prev_rec else GENESIS_PREV)
                if (_l_h != last_rec.get("h")
                        or last_rec.get("prev") != _l_prev_expected):
                    raise D5LedgerError(
                        "ledger_broken: kuyruk-head tutarsız — prev/h zinciri "
                        "kirik (fail-closed)")
            rec = dict(rec)                  # çağıranı-mutasyona-uğratma
            rec["seq"] = n + 1
            rec["prev"] = last_rec["h"] if last_rec else GENESIS_PREV
            rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            no_h = {k: v for k, v in rec.items() if k not in ("h", "node_sig")}
            rec["h"] = hashlib.sha256(
                rec["prev"].encode("utf-8") + jcs(no_h)).hexdigest()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(jcs(rec).decode("utf-8") + "\n")
            os.chmod(self.path, 0o600)
            return rec

    def line_count(self) -> int:
        return sum(1 for _ in self.records())


@dataclass
class SettlementBinding:
    """Bir-settlement'ın-D5-sabitleme-sonucu ( charge-escrow-tarafı, claim-alıcı-tarafı)."""

    charge: Dict[str, Any]
    claim: Dict[str, Any]
    delivery_hash: str
    ledger_tip: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "charge": self.charge,
            "claim": self.claim,
            "delivery_hash": self.delivery_hash,
            "ledger_tip": self.ledger_tip,
        }


def _signer_address(signer: Any) -> str:
    """``payer_signer``'dan-EVM-adresi-çöz ( eth-keys/eth-account/bytes kabul)."""
    from eth_keys import keys as _eth_keys
    key_bytes: bytes
    if isinstance(signer, (bytes, bytearray)):
        key_bytes = bytes(signer)
    elif hasattr(signer, "key"):             # eth_account.Account
        key_bytes = bytes(signer.key)
    elif isinstance(signer, _eth_keys.PrivateKey):
        key_bytes = signer.to_bytes()
    else:
        raise TypeError(f"unsupported_signer: {type(signer).__name__} "
                        "(bytes | eth_account.Account | eth_keys.PrivateKey)")
    return _eth_keys.PrivateKey(key_bytes).public_key.to_address()


class SettlementBinder:
    """RFC-010-beş-kontrol-sözleşmesinin-Pacta-tarafı-üreticisi-ve-doğrulayıcısı."""

    # --- teslimat-kanıtı ---------------------------------------------------
    @staticmethod
    def delivery_artifact(job: EscrowJob) -> Dict[str, Any]:
        """Kanıtlanan-şey: teslim-edilen-iş-+-settlement-olguları ( delivery).

        Deterministiktir — alıcı-bağımsız-olarak-aynı-bytes'ı-üretüp-hash'i
        teyit-edebilir ( öz-hizalama-YOK; ``evidenceHash``-bayt-eşitliği-bunu-ister).
        """
        from decimal import Decimal
        art: Dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status.value,
            "amount_usdc": str(job.amount_usdc),
            "fee_usdc": str(job.fee_collected_usdc
                            if job.fee_collected_usdc is not None else Decimal("0")),
            "output_payload": job.output_payload,
            "settlement_tx": job.settlement_tx,
            "settled_at_epoch_ms": job.settled_at_epoch_ms,
        }
        receipt = job.tamga_receipt
        if receipt is not None:
            # Tier-2-teslimat-kanıtı-varsa-bağa-kat ( "verified-delivery"-özü)
            art["tamga_output_hash"] = receipt.output_hash
            art["tamga_wasi_trace_root"] = receipt.wasi_trace_root
            art["tamga_instruction_count"] = receipt.instruction_count
        return art

    @classmethod
    def compute_delivery_hash(cls, job: EscrowJob) -> str:
        """``delivery_hash = sha256(jcs(delivery_artifact))`` — etiket-zorunlu ( RFC-007 R2)."""
        return hashlib.sha256(jcs(cls.delivery_artifact(job))).hexdigest()

    # --- RFC-010-kayıt-üretimi ---------------------------------------------
    @classmethod
    def build_charge(cls, job: EscrowJob,
                     delivery_hash: Optional[str] = None) -> Dict[str, Any]:
        """D5-ledger'a-yazılacak-charge-kaydı ( escrow'un-kendi-artefaktı).

        ``settlement_bind``-RFC-010-şekline-uyar: additive-alan, şema-değişikliği-YOK.
        """
        dh = delivery_hash or cls.compute_delivery_hash(job)
        # PACTA-2 (DUZELTILDI): '.lower()'-gizlemesi-BUYUK-harfi-geciriyordu —
        # _d5_triple_ok-ve-verify_binding-her-downstream-kapi-kucuk-har-
        # bekler ( 'AB'*32-burada-gecipte-ileride-receipt_invalid-cakis-
        # yordu). Artik-tum-protokol-arisinda-sadece-kucuk-hex-gecerlidir.
        if len(dh) != 64 or any(c not in "0123456789abcdef" for c in dh):
            raise ValueError(f"delivery_hash_invalid: 64-hex-beklendi ( {dh!r})")
        return {
            "op": "charge",
            "pkg": "pacta-escrow",
            "kind": "settlement",
            "job_id": job.job_id,
            "delivery_hash": {"alg": DELIVERY_ALG, "hex": dh},
            "settlement_bind": {
                "scheme": PACTA_SCHEME,
                "payment_id": job.job_id,
                "claim_evidence_hash": {"alg": DELIVERY_ALG, "hex": dh},
                "payer": job.buyer_address,
                "payee": job.seller_address,
                "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            "escrow": {
                "amount_usdc": str(job.amount_usdc),
                "fee_usdc": str(job.fee_collected_usdc
                                if job.fee_collected_usdc is not None else "0"),
                "settlement_tx": job.settlement_tx,
                "status": job.status.value,
            },
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

    @classmethod
    def build_claim(cls, job: EscrowJob,
                    delivery_hash: Optional[str] = None,
                    payer_signer: Optional[Any] = None) -> Dict[str, Any]:
        """Alıcı-taraflı-claim ( ödeme-yetkisi). ``payer_signer``-verilirse-imzalanır.

        İmza-sözleşmesi ( RFC-010-§3b, x402/v1): imza, claim-gövdesinin
        ( ``signature``-dışında) sha256-özününin **ham-bytes'ı**-üzerinedir —
        EIP-191-öneki-YOK; bu-Tamga'nın-gate'i-ile-birebir-aynı-kuraldır.
        """
        dh = delivery_hash or cls.compute_delivery_hash(job)
        claim: Dict[str, Any] = {
            "buyerAddress": job.buyer_address,
            "sellerAddress": job.seller_address,
            "settlementRef": job.job_id,
            "evidenceHash": {"alg": DELIVERY_ALG, "hex": dh},
        }
        if payer_signer is not None:
            addr = _signer_address(payer_signer)
            if addr.lower() != str(job.buyer_address).lower():
                raise ValueError(
                    f"signer_mismatch: imzalayan {addr} işin-alıcısı "
                    f"{job.buyer_address} değil — alıcı-imzalamalı (fail-closed)")
            claim["signature"] = cls.sign_claim(claim, payer_signer)
        return claim

    @staticmethod
    def sign_claim(claim: Dict[str, Any], payer_signer: Any) -> str:
        """Claim-gövdesinin-sha256-özütünü-ham-imzalar → ``0x`` + 65-byte-hex ( v=27|28)."""
        from eth_keys import keys as _eth_keys
        if isinstance(payer_signer, (bytes, bytearray)):
            key = _eth_keys.PrivateKey(bytes(payer_signer))
        elif hasattr(payer_signer, "key"):
            key = _eth_keys.PrivateKey(bytes(payer_signer.key))
        elif isinstance(payer_signer, _eth_keys.PrivateKey):
            key = payer_signer
        else:
            raise TypeError(f"unsupported_signer: {type(payer_signer).__name__}")
        digest = hashlib.sha256(
            json.dumps({k: v for k, v in claim.items() if k != "signature"},
                       sort_keys=True).encode("utf-8")).digest()
        sig = key.sign_msg_hash(digest)
        return ("0x" + sig.r.to_bytes(32, "big").hex()
                + sig.s.to_bytes(32, "big").hex()
                + bytes([sig.v if sig.v in (0, 1) else sig.v - 27]).hex())

    @classmethod
    def bind_settled_job(cls, job: EscrowJob, ledger: D5Ledger,
                         payer_signer: Optional[Any] = None) -> SettlementBinding:
        """Settled-bir-işin-kararını-D5-zincirine-sabitle ( escrow-FSM-entegrasyonu).

        Yalnızca-terminal-SETTLED-işler-bağlanabilir ( fail-closed: henüz-sonuçlan-
        mamış-işin-kararını-sabitlemek-yanlış-kanıt-üretir).
        """
        if job.status != EscrowStatus.SETTLED:
            raise ValueError(
                f"not_settled: iş {job.job_id} durum={job.status.value} — yalnızca "
                f"SETTLED işler D5'e sabitlenir (fail-closed)")
        if job.settlement_tx is None:
            raise ValueError(
                f"no_settlement_tx: iş {job.job_id} için settlement-tx yok — "
                f"önce settle_escrow çağrılmalı")
        dh = cls.compute_delivery_hash(job)
        charge = ledger.append(cls.build_charge(job, dh))
        claim = cls.build_claim(job, dh, payer_signer=payer_signer)
        return SettlementBinding(charge=charge, claim=claim, delivery_hash=dh,
                                 ledger_tip=charge["h"])

    # --- RFC-010-doğrulama-kapısı -------------------------------------------
    @staticmethod
    def _recover_signer(digest_hex: str, sig_hex: str) -> Optional[str]:
        """x402/v1: ham-özüt-imzasından-EVM-adresini-çöz ( EIP-191-öneki-YOK)."""
        from eth_keys.datatypes import Signature
        try:
            raw = bytes.fromhex(sig_hex[2:] if sig_hex.startswith("0x") else sig_hex)
        except Exception:
            return None
        if len(raw) != 65:
            return None
        v = raw[64]
        rec_id = v - 27 if v >= 27 else v
        if rec_id not in (0, 1):
            return None
        try:
            sig = Signature(vrs=(rec_id, int.from_bytes(raw[0:32], "big"),
                                 int.from_bytes(raw[32:64], "big")))
            return sig.recover_public_key_from_msg_hash(
                bytes.fromhex(digest_hex)).to_address()
        except Exception:
            return None

    @staticmethod
    def _claim_digest(claim: Dict[str, Any]) -> str:
        """Tamga-gate'i-ile-birebir-gövde-özütü ( sort_keys=True, ham-json)."""
        body = {k: v for k, v in claim.items() if k != "signature"}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    def _d5_triple_ok(rec: Dict[str, Any]) -> bool:
        """Kontrol-1-yardımcısı: seq-tamsayı + prev/h-64-hex ( RFC-010-_d5_chain_ok)."""
        seq = rec.get("seq")
        if not (isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1):
            return False
        for k in ("prev", "h"):
            v = rec.get(k)
            if not (isinstance(v, str) and len(v) == 64
                    and all(c in "0123456789abcdef" for c in v)):
                return False
        return True

    @classmethod
    def verify_binding(cls, charge: Dict[str, Any],
                       claim: Dict[str, Any]) -> Dict[str, Any]:
        """Beş-kontrolü-çalıştırır; ilk-RED'de-döner ( fail-closed; RFC-010-§3).

        Dönüş-sözleşmesi-Tamga'nın-``tools/settlement_bind_verify.py``'si-ile
        aynı-sözlüktür ( GREEN/RED/İNDETERMİNE + reason + reason_code + checks)
        böylece-iki-gate-aynı-girdide-aynı-sonuç-verir.
        """
        out: Dict[str, Any] = {"ok": False, "verdict": None, "reason": None,
                               "reason_code": None, "checks": {}}

        bind = charge.get("settlement_bind")
        if not isinstance(bind, dict):
            out.update(verdict="RED", reason_code=1,
                       reason="settlement_bind_missing: dikiş-alanı-yok")
            return out
        scheme = bind.get("scheme", "")
        if scheme not in SUPPORTED_SCHEMES:
            out.update(verdict="İNDETERMİNE", reason_code=2,
                       reason=f"unknown_scheme: {scheme!r} ( desteklenen: "
                              f"{SUPPORTED_SCHEMES}) — sonuç-esirgenir")
            return out
        if scheme != PACTA_SCHEME:
            # Dürüst-sınır: tamga/native-(ed25519)-ve-erc8004-(merkle)-sözleşmeleri
            # Tamga'nın-kendi-gate'indedir; Pacta-onları-tekrar-etmez.
            out.update(verdict="İNDETERMİNE", reason_code=2,
                       reason=f"pacta_gate_only_x402v1: {scheme!r}-doğrulaması "
                              f"Tamga'nın-tools/settlement_bind_verify.py'sinde")
            return out

        # --- 1) receipt-verifies: D5-üçlüsü + delivery_hash
        dh = charge.get("delivery_hash")
        ok1 = (cls._d5_triple_ok(charge)
               and isinstance(dh, dict) and set(dh) == {"alg", "hex"}
               and dh["alg"] in ("sha256", "keccak256")
               and isinstance(dh["hex"], str) and len(dh["hex"]) == 64
               and all(c in "0123456789abcdef" for c in dh["hex"]))
        out["checks"]["1_receipt"] = ok1
        if not ok1:
            out.update(verdict="RED", reason_code=3, reason="receipt_invalid")
            return out

        # --- 2) claim-verifies: imza-buyerAddress'e-çözümlenir
        sig, buyer = claim.get("signature"), claim.get("buyerAddress")
        ok2 = isinstance(sig, str) and isinstance(buyer, str)
        if ok2:
            got = cls._recover_signer(cls._claim_digest(claim), sig)
            ok2 = got is not None and got.lower() == str(buyer).lower()
        out["checks"]["2_claim_sig"] = ok2
        if not ok2:
            out.update(verdict="RED", reason_code=4, reason="claim_signature_invalid")
            return out

        # --- 3) settlementRef-resolves
        ref = claim.get("settlementRef")
        ok3 = isinstance(ref, str) and ref == bind.get("payment_id")
        out["checks"]["3_settlement_ref"] = ok3
        if not ok3:
            out.update(verdict="RED", reason_code=5, reason="settlement_ref_mismatch")
            return out

        # --- 4) payer/payee-match
        ok4 = (str(claim.get("buyerAddress", "")).lower()
               == str(bind.get("payer", "")).lower()
               and str(claim.get("sellerAddress", "")).lower()
               == str(bind.get("payee", "")).lower())
        out["checks"]["4_parties"] = ok4
        if not ok4:
            out.update(verdict="RED", reason_code=6, reason="party_mismatch")
            return out

        # --- 5) evidenceHash == receiptHash ( bayt-eşit)
        ev = claim.get("evidenceHash")
        ok5 = (isinstance(ev, dict) and set(ev) == {"alg", "hex"}
               and ev["alg"] == dh["alg"] and ev["hex"] == dh["hex"])
        out["checks"]["5_evidence_hash"] = ok5
        if not ok5:
            out.update(verdict="RED", reason_code=7, reason="evidence_hash_mismatch")
            return out

        # --- 7) submitter/payee-ayrımı ( x402#2887; additive — yoksa-eski-davranış)
        sub = bind.get("submitter")
        if isinstance(sub, str) and sub:
            payee = bind.get("payee")
            ok7 = isinstance(payee, str) and payee and sub.lower() != str(payee).lower()
            out["checks"]["7_submitter_payee"] = ok7
            if not ok7:
                out.update(verdict="RED", reason_code=9,
                           reason="submitter_payee_conflation: facilitator (tx.from) "
                                  "== payee — #2887: merchant-payee-asla-facilitator")
                return out

        out.update(ok=True, verdict="GREEN", reason_code=0,
                   reason="beş-kontrol-doğru: receipt+claim+ref+parties+evidenceHash")
        return out
