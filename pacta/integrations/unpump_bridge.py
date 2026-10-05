"""
Pacta ↔ Unpump ( 01_unicorn/24-ajan-borsasi) ödeme-kanıtı köprüsü —

    ödeme ( Unpump Match + kanit_cekirdegi zincir-girişi)
      → escrow settlement ( Pacta EscrowJob=SETTLED, settlement_tx)
        → D5 kanıtı ( Tamga D5-ledger'a-yazılan charge)

MESH-BAĞLANTISI ( 03-Pacta ↔ 24-ajan-borsasi):

Unpump'un-borsası-bir-ödeme-kanıtı-üretir — ``borsa_core.Match.work_done`` +
``receipt_hash`` ( ``kanit_cekirdegi``'nin Delilix-SHA-256-zincirinden) — AMA-o-
kanıt-Unpump'un-kendi-zincirinde-kalır-ve-Pacta'nın-escrow-kararına-BAĞLI-
DEĞİLDİR. Alıcı-için-"ben-ödeme-yaptım"-Unpump'un-sözü-kadar-iyidir; escrow'un-
"TESLİMAT-kanıtlandı"-kararından-bağımsızdır. Bu-modül-o-uçağı-kapatır: iki-
kanıtı-çapraz-uzlaştırır-ve-ortak-sonucu-D5'e-sabitler.

Üretilen-charge, RFC-010'ın-beş-kontrolünü-GEÇEN-bir-**üstkümesidir** ( additive-
alanlar-şema-değişikliği-YAPMAZ — tıpkı-``SettlementBinder.build_charge``'ın-
docstring'indeki-kural-gibi). Yani-Tamga'nın-KENDİ-gate'i-onu-kabul-eder ve
üç-yönlü-bir-çapraz-test-doğar:

    Unpump-kanıtı ↔ Pacta-escrow'u ↔ Tamga-D5'i

EK-KONTROLLAR ( RFC-010'ın-beşinin-üzerine; fail-closed — biri-RED → tümü-RED):

  6. unpump-proof      — charge ``unpump``-bloğu-var, work_done=true,
                         ``unpump_ref``-ile-eşleşir
  7. receipt-recomputes — receipt_hash bağımsız-yeniden-hesaplanır ( Unpump'un-
                         KENDİ ``kanit_cekirdegi.content_hash``'i-ile; sender'in-
                         sözüne-güvenilmez) ve match'e-yazılan-değerle-bire-bir
  8. escrow-reconcile  — kanıt-tutarı/tarafları == escrow-tutarı/tarafları

BAĞIMSIZLIK ( dürüst-sınır): ``kanit_cekirdegi``-checkout'u-erişilemezse-
receipt'in-Delilix-hash'i-HESAPLANAMAZ ( o-sözleşme-Unpump'un-kendi-modülüdür;
``tamga/native``-için-Pacta'nın-İNDETERMİNE-dönmesinin-aynı-dürüstlüğü). O-
durumda-köprü-RED-değil-**İNDETERMİNE**-verir — sonuç-esirgenir, gizlice-
"geçti"-denmez. Çapraz-testler-checkout-varken-koşulur ( yoksa-skip).

DEĞER-TRANSFERİ-YOK ( ``tamga_d5``-ile-aynı): bağ-kararların-taahhüdünü-sabitler;
fon-akışı-hâlâ-vault-ledger'ındadır.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from pacta.integrations.tamga_d5 import (
    D5Ledger,
    SettlementBinder,
)
from pacta.models import EscrowJob, EscrowStatus

UNPUMP_TAG = "unpump/v1"            # additive-etiket ( settlement_bind.içinde)
AMOUNT_TOLERANCE = 1e-6             # USD — Decimal-quantizasyon payı


class UnpumpBridgeError(Exception):
    """Köprü-hatası — ödeme-kanıtı-veya-uzlaşı-reddedildi ( fail-closed-sinyali)."""


# ------------------------------------------------------------------ modeller


@dataclass
class UnpumpPaymentProof:
    """Unpump-ödeme-kanıtı — ``borsa_core.Match``'in kanıt-şekli ( duck-typed).

    ``kanit_entry``/``kanit_operation``-olmazsa-receipt-**bağımsız-doğrulanamaz**:
    hash'-in-machine-checkable-olması-için-gönderenin-sözü-değil, kanıtlanan-
    olgu-lar ( kanonik-6-alan) gerekir. Bu-sebeple-``verify_payment_proof``-
    onları-zorunlu-tutar.
    """

    match_id: str
    agent_id: str                       # Unpump-ajanı == Pacta-satıcı ( merchant)
    buyer_id: str                       # Unpump-alıcı == Pacta-alıcı ( payer)
    amount: float                       # USD
    work_done: bool                     # ⭐⭐⭐ iş-tamamlandı-mı ( borsa-core)
    receipt_hash: str                   # complete_work'ün-kanıt-token'ı
    bid_id: Optional[str] = None
    completed_at: Optional[float] = None
    kanit_entry: Optional[Dict[str, Any]] = None        # {id, h, prev}
    kanit_operation: Optional[Dict[str, Any]] = None    # 6-alan-kanonik

    @classmethod
    def from_match(cls, match: Any, *, buyer_id: Optional[str] = None,
                   kanit_entry: Optional[Dict[str, Any]] = None,
                   kanit_operation: Optional[Dict[str, Any]] = None
                   ) -> "UnpumpPaymentProof":
        """``borsa_core.Match``'ten-kanıt-üret ( Match-buyer-tutmaz — Bid'den-gelir).

        ``buyer_id``-verilmezse-``match.buyer_id``'den-okunur ( duck-typing);
        yoksa-reddeder — alıcı-sız-uzlaşı-mümkün-değildir.
        """
        eksik = [a for a in ("match_id", "agent_id", "amount", "work_done")
                 if not hasattr(match, a)]
        if eksik:
            raise TypeError(f"match benzemiyor — eksik alanlar: {', '.join(eksik)}")
        by = buyer_id if buyer_id is not None else getattr(match, "buyer_id", None)
        if not by:
            raise ValueError("buyer_id gerekli — Match tutmaz, Bid'den verilmeli")
        rh = getattr(match, "receipt_hash", None)
        if not rh:
            raise ValueError("receipt_hash yok — complete_work çağrılmamış "
                             "(kanıtsız tamamlama reddedilir)")
        return cls(
            match_id=str(match.match_id),
            agent_id=str(match.agent_id),
            buyer_id=str(by),
            amount=float(match.amount),
            work_done=bool(match.work_done),
            receipt_hash=str(rh),
            bid_id=str(getattr(match, "bid_id", "") or "") or None,
            completed_at=(float(match.completed_at)
                          if getattr(match, "completed_at", None) is not None else None),
            kanit_entry=kanit_entry,
            kanit_operation=kanit_operation,
        )


@dataclass
class UnpumpBinding:
    """Unpump-ödemesinin-D5-sabitleme-sonucu ( charge-escrow, claim-alıcı)."""

    charge: Dict[str, Any]
    claim: Dict[str, Any]
    delivery_hash: str
    ledger_tip: Optional[str]
    proof: UnpumpPaymentProof
    reconciliation: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "charge": self.charge,
            "claim": self.claim,
            "delivery_hash": self.delivery_hash,
            "ledger_tip": self.ledger_tip,
            "proof": self.proof.__dict__,
            "reconciliation": self.reconciliation,
        }


# -------------------------------------------------------------------- köprü


class UnpumpPaymentBridge:
    """Ödeme-kanıtı → escrow-settlement → D5-kanıtı köprüsü ( RFC-010-üstkümesi)."""

    # --- Unpump-keşfi ------------------------------------------------------
    @staticmethod
    def unpump_root() -> Optional[Path]:
        """24-ajan-borsasi-checkout'u veya None ( yoksa-çapraz-testler-skip).

        Sıra: ``UNPUMP_ROOT``-env → paket-iki-üst-klasörünün-kardeş-dizini →
        bilinen-kurulum-yolu. Her-ikisi-de-eksikse-yok-deme ( ağır-bağımlılık-YOK).
        """
        here = Path(__file__).resolve().parents[2]            # .../03-Pacta
        cands = [
            os.environ.get("UNPUMP_ROOT"),
            str(here.parent / "24-ajan-borsasi"),             # .../01_unicorn/…
            "/home/gokun/projects/01_unicorn/24-ajan-borsasi",
        ]
        for c in cands:
            if not c:
                continue
            root = Path(c).expanduser().resolve()
            if (root / "kanit_cekirdegi.py").is_file() \
                    and (root / "borsa_core.py").is_file():
                return root
        return None

    @staticmethod
    def _kanit_cekirdegi():
        """Unpump'un-kanıt-çekirdeğini-yükle ( hash-sözleşmesi-için) veya None.

        Load-once; ``sys.path``-i-almadan-sonra-temizler ( ``tamga_canon``-
        importundaki-aynı-disiplin) — modülün-kendisi-``sys.modules``'de-kalır.
        """
        root = UnpumpPaymentBridge.unpump_root()
        if root is None:
            return None
        mod = sys.modules.get("kanit_cekirdegi")
        if mod is not None:
            return mod
        inserted = str(root) not in sys.path
        if inserted:
            sys.path.insert(0, str(root))
        try:
            import kanit_cekirdegi                      # yerel-import ( keşif)
        except Exception:
            return None
        finally:
            if inserted and str(root) in sys.path:
                sys.path.remove(str(root))
        return kanit_cekirdegi

    @staticmethod
    def _kanonik_islem(kc, operation: Dict[str, Any]) -> Dict[str, Any]:
        """Hash-için-kanonik-sıraya-düzelt ( jcs-saklamadan-sonra-bile-sağlam).

        D5-``jcs``-anahtarları-sıralar ( RFC-8785) — ``content_hash``-ise-gönderen-
        sırasını-okur ( Delilix-sözleşmesi). Bu-yardımcı-her-iki-yoldan-gelen-
        operation'ı-aynı-bytes'a-getirir; hash'in-tekrar-üretilebilirliği-bunu-ister.
        """
        return {a: operation.get(a) for a in kc.CANONICAL_ALANLAR}

    # --- 1) ödeme-kanıtı doğrulama -----------------------------------------
    @staticmethod
    def verify_payment_proof(proof: UnpumpPaymentProof) -> Dict[str, Any]:
        """Unpump-ödeme-kanıtını-bağımsız-doğrula ( GREEN/RED/İNDETERMİNE).

        Gönderenin-sözüne-güvenilmez: ``receipt_hash``-i-Unpump'un-KENDİ-kanonik-
        serileştirmesiyle-baştan-hesaplar-ve-match'e-yazılan-değerle-karşılaştırır.
        """
        out: Dict[str, Any] = {"ok": False, "verdict": None, "reason": None,
                               "reason_code": None, "checks": {}}

        # u1) iş-tamamlandı + receipt-var ( bool-sarmalı: ``and``-son-operandı-
        # döndürür — string-receipt'i-True-gibi-saklamaz)
        ok1 = bool(proof.work_done is True and isinstance(proof.receipt_hash, str)
                   and proof.receipt_hash)
        out["checks"]["u1_work_done"] = ok1
        if not ok1:
            out.update(verdict="RED", reason_code=11,
                       reason="work_not_done: ödeme kanıtı tamamlanmamış iş "
                              "(complete_work çağrılmamış)")
            return out

        # u2) kanıt-zincir-girişi-var-ve-match'in-receipt'ına-eşit
        ke = proof.kanit_entry
        ok2 = (isinstance(ke, dict) and isinstance(ke.get("h"), str)
               and ke["h"] == proof.receipt_hash)
        out["checks"]["u2_kanit_entry"] = ok2
        if not ok2:
            out.update(verdict="RED", reason_code=12,
                       reason="kanit_entry_missing: receipt'ın zincir-girişi yok "
                              "veya h ≠ receipt_hash (machine-checkable değil)")
            return out

        # u3) receipt bağımsız-yeniden-hesaplanabilir ( Unpump'un-sözleşmesiyle)
        kc = UnpumpPaymentBridge._kanit_cekirdegi()
        if kc is None:
            out.update(verdict="İNDETERMİNE", reason_code=13,
                       reason="unpump_kanit_cekirdegi_unavailable: Delilix "
                              "hash-sözleşmesi erişilemez — receipt-esirgenir")
            return out
        op = proof.kanit_operation
        if not isinstance(op, dict):
            out.update(verdict="RED", reason_code=12,
                       reason="kanit_operation_missing: 6-alan-kanonik yok — "
                              "receipt bağımsız doğrulanamaz")
            return out
        recomputed = kc.content_hash(UnpumpPaymentBridge._kanonik_islem(kc, op))
        ok3 = recomputed == proof.receipt_hash
        out["checks"]["u3_receipt_recomputes"] = ok3
        if not ok3:
            out.update(verdict="RED", reason_code=14,
                       reason=f"receipt_hash_mismatch: bağımsız hesap "
                              f"{recomputed[:24]}… ≠ match {proof.receipt_hash[:24]}…")
            return out

        # u4) gün-anahtarı-tutarlı ( Delilix idempotency-şeması; id-günü==ts-günü)
        try:
            gun = kc.day_key(str(op.get("ts")))
            ok4 = isinstance(ke.get("id"), str) and ke["id"].endswith("|" + gun)
        except Exception:
            ok4 = False
        out["checks"]["u4_day_key"] = ok4
        if not ok4:
            out.update(verdict="RED", reason_code=15,
                       reason="day_key_mismatch: kanıt-id'nin günü ts ile uyuşmuyor")
            return out

        out.update(ok=True, verdict="GREEN", reason_code=0,
                   reason="ödeme kanıtı doğrulandı: work_done + receipt bağımsız "
                          "yeniden üretilebilir")
        return out

    # --- 2) ödeme ↔ escrow uzlaşı ------------------------------------------
    @staticmethod
    def reconcile(proof: UnpumpPaymentProof, job: EscrowJob) -> Dict[str, Any]:
        """Unpump-ödeme-kanıtı ile Pacta-escrow-settlement'ını-çapraz-uzlaştır.

        İki-bağımsız-sistem-aynı-iş-iddia-ediyorsa-tutar/parti/sonuç-uymak-zorunda;
        uymazlarsa-bağ-yanlış-kanıt-üretir-ve-reddedilir ( fail-closed).
        """
        checks = {
            "r1_settled": (job.status == EscrowStatus.SETTLED
                           and job.settlement_tx is not None),
            "r2_amount": (abs(float(job.amount_usdc) - float(proof.amount))
                          <= AMOUNT_TOLERANCE),
            "r3_parties": (str(proof.buyer_id).lower()
                           == str(job.buyer_address).lower()
                           and str(proof.agent_id).lower()
                           == str(job.seller_address).lower()),
            "r4_receipt_bound": (proof.kanit_entry or {}).get("h")
                                == proof.receipt_hash,
        }
        bad = [k for k, v in checks.items() if not v]
        return {
            "ok": not bad,
            "checks": checks,
            "reason": ("reconciled" if not bad
                       else f"unpump_escrow_mismatch: {', '.join(bad)}"),
        }

    # --- 3) D5-kayıt-üretimi ------------------------------------------------
    @classmethod
    def build_unpump_charge(cls, job: EscrowJob, proof: UnpumpPaymentProof,
                            delivery_hash: Optional[str] = None) -> Dict[str, Any]:
        """D5-ledger'a-yazılacak-charge — RFC-010-üstkümesi ( additive).

        Taban-``SettlementBinder.build_charge``'tır ( beş-kontrolü-geçer); üzerine
        ``settlement_bind.unpump_ref``-ve-``unpump``-bloğu-eklenir. Şema-
        değişikliği-YOK: bilinmeyen-alanları-Tamga'nın-gate'i-görmezden-gelendir.
        """
        dh = delivery_hash or SettlementBinder.compute_delivery_hash(job)
        charge = SettlementBinder.build_charge(job, dh)

        charge["settlement_bind"]["unpump_ref"] = {
            "scheme": UNPUMP_TAG,
            "match_id": proof.match_id,
            "receipt_hash": proof.receipt_hash,     # Unpump-native: "sha256:<hex>"
        }
        charge["unpump"] = {
            "borsa": "24-ajan-borsasi",
            "match_id": proof.match_id,
            "bid_id": proof.bid_id,
            "agent_id": proof.agent_id,
            "buyer_id": proof.buyer_id,
            "amount_usdc": str(Decimal(str(proof.amount))
                               .quantize(Decimal("0.000001"))),
            "work_done": proof.work_done,
            "receipt_hash": proof.receipt_hash,
            "completed_at_epoch": proof.completed_at,
            "kanit_entry": proof.kanit_entry,
            "kanit_operation": proof.kanit_operation,
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        return charge

    @classmethod
    def bind_unpump_payment(cls, proof: UnpumpPaymentProof, job: EscrowJob,
                            ledger: D5Ledger, *,
                            payer_signer: Optional[Any] = None) -> UnpumpBinding:
        """Ödeme-kanıtı → escrow-settlement → D5-kanıtı ( ana-boru).

        Sıra-önemli: önce-kanıt-doğrulanır,-sonra-uzlaşı; ikisi-de-yeşil-olmadan
        **hiçbir-şey-zincire-yazılmaz** ( fail-closed — yarım-kanıt-üretme).
        """
        v = cls.verify_payment_proof(proof)
        if v["verdict"] != "GREEN":
            raise UnpumpBridgeError(
                f"payment_proof_not_green: {v['verdict']} — {v['reason']}")
        rec = cls.reconcile(proof, job)
        if not rec["ok"]:
            raise UnpumpBridgeError(f"reconciliation_failed: {rec['reason']}")

        dh = SettlementBinder.compute_delivery_hash(job)
        charge = ledger.append(cls.build_unpump_charge(job, proof, dh))
        claim = SettlementBinder.build_claim(job, dh, payer_signer=payer_signer)
        return UnpumpBinding(charge=charge, claim=claim, delivery_hash=dh,
                             ledger_tip=charge["h"], proof=proof,
                             reconciliation=rec)

    # --- 4) doğrulama-kapısı ------------------------------------------------
    @classmethod
    def verify_binding(cls, charge: Dict[str, Any],
                       claim: Dict[str, Any]) -> Dict[str, Any]:
        """RFC-010-beşi + unpump-üçü ( 6/7/8) — ilk-RED'de-döner ( fail-closed).

        Sözlük-``SettlementBinder.verify_binding``-ile-aynıdır- böylece-iki-gate
        aynı-girdide-aynı-sonuç-verir; unpump-kontrolleri-ancak-beşi-yeşil-ise
        çalışır ( kapı-zaten-KIRMIZI-ise-onu-olduğu-gibi-iade-eder).
        """
        base = SettlementBinder.verify_binding(charge, claim)
        if base.get("verdict") != "GREEN":
            return base

        out = dict(base)
        out["checks"] = dict(base["checks"])
        unp = charge.get("unpump")
        bind = charge.get("settlement_bind") or {}
        ref = bind.get("unpump_ref") or {}

        # 6) unpump-proof-bloğu
        ok6 = bool(isinstance(unp, dict) and unp.get("work_done") is True
                   and isinstance(unp.get("receipt_hash"), str) and unp["receipt_hash"]
                   and ref.get("match_id") == unp.get("match_id")
                   and ref.get("receipt_hash") == unp.get("receipt_hash"))
        out["checks"]["6_unpump_proof"] = ok6
        if not ok6:
            out.update(ok=False, verdict="RED", reason_code=16,
                       reason="unpump_proof_missing: charge unpump-bloğu yok, "
                              "work_done değil veya unpump_ref ile çelişiyor")
            return out

        # 7) receipt bağımsız-yeniden-hesaplanır ( gönderene-güvenmeden)
        kc = cls._kanit_cekirdegi()
        if kc is None:
            out.update(verdict="İNDETERMİNE", reason_code=13,
                       reason="unpump_kanit_cekirdegi_unavailable: receipt "
                              "yeniden hesaplanamıyor — sonuç esirgenir")
            return out
        recomputed = kc.content_hash(cls._kanonik_islem(kc, unp.get("kanit_operation") or {}))
        ok7 = recomputed == unp["receipt_hash"]
        out["checks"]["7_receipt_recomputes"] = ok7
        if not ok7:
            out.update(ok=False, verdict="RED", reason_code=17,
                       reason=f"receipt_hash_mismatch: bağımsız hesap "
                              f"{recomputed[:24]}… ≠ charge "
                              f"{unp['receipt_hash'][:24]}…")
            return out

        # 8) kanıt ↔ escrow-uzlaşı ( D5-içinde-taşınan-fakatlar)
        esc = charge.get("escrow") or {}
        try:
            amount_ok = (Decimal(str(unp.get("amount_usdc")))
                         == Decimal(str(esc.get("amount_usdc"))))
        except Exception:
            amount_ok = False
        ok8 = (amount_ok
               and str(unp.get("buyer_id", "")).lower()
               == str(bind.get("payer", "")).lower()
               and str(unp.get("agent_id", "")).lower()
               == str(bind.get("payee", "")).lower())
        out["checks"]["8_escrow_reconcile"] = ok8
        if not ok8:
            out.update(ok=False, verdict="RED", reason_code=18,
                       reason="escrow_reconcile_mismatch: unpump kanıtının "
                              "tutarı/tarafları escrow kaydıyla uyuşmuyor")
            return out

        out.update(ok=True, verdict="GREEN", reason_code=0,
                   reason="sekiz-kontrol doğru: RFC-010 beşi + unpump kanıtı, "
                          "receipt-yeniden-üretimi, escrow-uzlaşı")
        return out

    # --- 5) D5 → Unpup geri-okuma -------------------------------------------
    @staticmethod
    def unpump_ref_of(charge: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """D5-charge'ından-Unpump-ödeme-referansını-oku ( D5 → öpde geri-gezinme).

        ``None`` → bu-charge-bir-Unpump-ödeme-bağı-değil ( sade-escrow-settlement).
        """
        ref = (charge.get("settlement_bind") or {}).get("unpump_ref")
        return ref if isinstance(ref, dict) else None
