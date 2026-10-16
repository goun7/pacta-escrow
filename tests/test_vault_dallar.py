"""pacta.core.vault dal-kesen ( branch-cutting) testleri — LEED-kampanyası.

Kural-1: MEVCUT DOSYALARA/TESTLERE DOKUNULMADI — yalnızca bu yeni dosya.
Kural-4: tamamen SAF-BELLEK — gerçek ağ/RPC/subprocess YOK. Zaman,
``vault.time.time`` monkeypatch ile dondurulur ( deterministik SLA/pencere
sınırları); ``chain_adapter``/``d5_ledger`` duck-typed sahte-nesnelerdir;
``SettlementBinder`` ``sys.modules``-stub'ı ile değiştirilir.

KAPSAN — PactaEscrowVault'un HER public metodunun başarı/başarısızlık/sınır
dalları: get_job, check_solvency_invariant, create_and_lock_escrow,
submit_output, mark_verified_ok, settle_escrow, anchor_job,
verify_chain_anchors, refund_timeout, refund_quality_failure, raise_dispute,
resolve_arbitration, get_vault_stats + özel-durum hiyerarşisi.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import pacta.core.vault as vault_mod
from pacta.chain import ChainUnavailableError
from pacta.core.fsm import InvalidStateTransitionError
from pacta.core.vault import (
    EscrowAuthorizationError,
    EscrowNotFoundError,
    InvariantViolationError,
    PactaEscrowVault,
)
from pacta.models import (
    ArbitrationVote,
    DisputeClaim,
    EscrowJob,
    EscrowPolicy,
    EscrowStatus,
    TamgaExecutionReceipt,
    ZkTLSCertificate,
)

# ------------------------------------------------------------------ sabitler
ALICI = "0x1111111111111111111111111111111111111111"
SATICI = "0x2222222222222222222222222222222222222222"
YABANCI = "0x3333333333333333333333333333333333333333"
HAKEM1 = "0xaaaa1aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1aa"
HAKEM2 = "0xbbbb2bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2b"
HAKEM3 = "0xcccc3cccccccccccccccccccccccccccccccccc3c"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


# ------------------------------------------------------------------ yardımcı
@pytest.fixture
def kasa() -> PactaEscrowVault:
    """Taze-boş kasa ( her-testte-bağımsız)."""
    return PactaEscrowVault()


@pytest.fixture
def saat(monkeypatch):
    """``vault`` modülündeki ``time.time``'ı dondurur.

    Dallar: ``kutu["su_an"]``-değeri-değiştirilerek SLA/dispute-pencere
    sınırları ( tam-eşitlik vs +1ms) deterministik-test-edilir.
    """
    kutu = {"su_an": 1_000_000.0}
    monkeypatch.setattr(vault_mod.time, "time", lambda: kutu["su_an"])
    return kutu


class _SahteAdapter:
    """Duck-typed chain-adapter ( gerçek RPC YOK)."""

    def __init__(self, bag_yaniti: Any = "0xBAG0000000000000000000000000000000000B"):
        self.yanit = bag_yaniti
        self.anchor_cagrilari: List[Dict[str, Any]] = []
        self.verify_cagrilari: List[Any] = []

    def anchor(self, **kw) -> Any:
        self.anchor_cagrilari.append(kw)
        return self.yanit

    def verify_anchor(self, anchor: Any) -> bool:
        self.verify_cagrilari.append(anchor)
        return True


class _SahteBaglayici:
    """pacta.integrations.tamga_d5.SettlementBinder stub'u."""

    def __init__(self) -> None:
        self.cagrilar: List[Any] = []

    def bind_settled_job(self, job: Any, ledger: Any, payer_signer: Any = None):
        self.cagrilar.append((job.job_id, ledger))
        return SimpleNamespace(to_dict=lambda: {"charge": "ok", "job_id": job.job_id})


def _kilitle(kasa: PactaEscrowVault, amount: Any = Decimal("100"),
             policy: Optional[EscrowPolicy] = None, **kw) -> EscrowJob:
    return kasa.create_and_lock_escrow(ALICI, SATICI, amount, policy=policy, **kw)


def _dogrulanmis_is(kasa: PactaEscrowVault, amount: Any = Decimal("100"),
                    policy: Optional[EscrowPolicy] = None) -> EscrowJob:
    """lock → submit → verified_ok tamamlanmış iş döndürür."""
    is_ = kasa.create_and_lock_escrow(
        ALICI, SATICI, amount, policy=policy or EscrowPolicy(timeout_ms=5000))
    kasa.submit_output(is_.job_id, {"cikti": "tamam"})
    kasa.mark_verified_ok(is_.job_id)
    return is_


def _itiraz_ac(kasa: PactaEscrowVault, job_id: str,
               claimant: str = ALICI) -> DisputeClaim:
    """raise_dispute ancak OUTPUT_SUBMITTED'den-geçerli-olduğu-için-gerekirse
    önce submit-output-yapılır ( FSM: ESCROW_LOCKED → DISPUTED yasak).
    Idempotent: zaten-submit-edilmişse-tekrar-etmez ( çift-submit-FSM-hatası)."""
    is_ = kasa.jobs[job_id]
    if is_.status == EscrowStatus.ESCROW_LOCKED:
        kasa.submit_output(job_id, {"cikti": "tamam"})
    return kasa.raise_dispute(job_id, claimant, "kalite-kotu", "0xKANIT")


def _oy(adres: str, buyer_lehine: bool) -> ArbitrationVote:
    return ArbitrationVote(
        arbitrator_address=adres, vote_favor_buyer=buyer_lehine,
        rationale_hash="0x0y")


# ================================================================== get_job
class TestGetJob:
    """get_job dalları: mevcut-iş-döner / yoksa-None / aynı-nesne."""

    def test_mevcut_is_donulur(self, kasa):
        olustu = _kilitle(kasa)
        assert kasa.get_job(olustu.job_id) is olustu

    @pytest.mark.parametrize("job_id", ["yok", "", "0x1234", "job-1"])
    def test_yoksa_none_donulur(self, kasa, job_id):
        assert kasa.get_job(job_id) is None

    def test_jobs_sozlugu_ayni_nesne(self, kasa):
        is_ = _kilitle(kasa)
        assert kasa.jobs[is_.job_id] is kasa.get_job(is_.job_id)


# ================================================ check_solvency_invariant
class TestSolvencyInvariant:
    """check_solvency_invariant dalları:
    * boş-kasa → True
    * yeterli-bakiye → True
    * TAM-EŞİTLİK ( balance == required) → True ( sınır: < karşılanmaz)
    * yetersiz → InvariantViolationError + mesaj-formatı
    * aktiv-durum-kümesi ( LOCKED/OUTPUT_SUBMITTED/VERIFIED_OK/
      OPTIMISTIC_SETTLED/DISPUTED/ARBITRATION_IN_PROGRESS) kilitli-sayılır
    * aktiv-OLMAYAN durumlar ( INITIALIZED/SETTLED/SLASHED_REFUNDED/
      AUTO_REFUNDED_TIMEOUT) sayılmaz
    * bond'lar yalnızca DISPUTED/ARBITRATION_IN_PROGRESS işlerinde sayılır
    * PACTA-VLT-1: yetim-dispute ( job_id jobs'te yok) → fail-closed-
      InvariantViolationError ( eskiden-ham-KeyError-üretim-hatasıydı)
    * PACTA-VLT-3-TAMAMLAMA: kasa-bakiye-kaydı-EKSİK ( kirilmis-defter) →
      ham-KeyError-DEĞİL, fail-closed-InvariantViolationError
    * get_vault_stats yoluyla de aynı karar-verilir
    """

    def test_bos_kasa_true(self, kasa):
        assert kasa.check_solvency_invariant() is True

    def test_kilitli_is_yeterli_true(self, kasa):
        _kilitle(kasa, Decimal("100"))
        assert kasa.check_solvency_invariant() is True

    def test_tam_esitlikte_true(self, kasa):
        """Sınır: actual == required → '<' DALINA-GİRİLMEZ."""
        _kilitle(kasa, Decimal("100"))
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_yetersizde_invariant_hatasi(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        kasa.ledger_balances[is_.deposit_token] = Decimal("99.999999")
        with pytest.raises(InvariantViolationError) as hb:
            kasa.check_solvency_invariant()
        assert "99.999999" in hb.value.message
        assert "100.000000" in hb.value.message

    @pytest.mark.parametrize("durum", [
        EscrowStatus.SETTLED, EscrowStatus.SLASHED_REFUNDED,
        EscrowStatus.AUTO_REFUNDED_TIMEOUT, EscrowStatus.INITIALIZED,
    ])
    def test_aktiv_olmayan_durumlar_sayilmaz(self, kasa, durum):
        is_ = _kilitle(kasa, Decimal("100"))
        is_.status = durum
        # ledger'da 100-var-AMA-gereksinim 0 → hala-solvent
        assert kasa.check_solvency_invariant() is True

    @pytest.mark.parametrize("durum", [
        EscrowStatus.ESCROW_LOCKED, EscrowStatus.OUTPUT_SUBMITTED,
        EscrowStatus.VERIFIED_OK, EscrowStatus.OPTIMISTIC_SETTLED,
        EscrowStatus.DISPUTED, EscrowStatus.ARBITRATION_IN_PROGRESS,
    ])
    def test_aktiv_durumlar_kilitli_sayilir(self, kasa, durum):
        is_ = _kilitle(kasa, Decimal("100"))
        is_.status = durum
        # 100'i-aşan-eksiltme-ancak-aktiv-iş-varsa-yakalanır
        kasa.ledger_balances[USDC] = Decimal("50")
        with pytest.raises(InvariantViolationError):
            kasa.check_solvency_invariant()

    def test_bondlar_arbitration_durumunda_sayilir(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        _itiraz_ac(kasa, is_.job_id)
        assert kasa.ledger_balances[USDC] == Decimal("120.000000")
        # gereksinim = 100 ( kilitli-iş) + 20 ( bond) = 120 → tam-eşitlik-True
        assert kasa.check_solvency_invariant() is True

    def test_bondlar_disputed_durumunda_da_sayilir(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        _itiraz_ac(kasa, is_.job_id)
        is_.status = EscrowStatus.DISPUTED  # FSM-gerçek-yol-değil-AMA-dal-testi
        kasa.ledger_balances[USDC] = Decimal("110")
        with pytest.raises(InvariantViolationError) as hb:
            kasa.check_solvency_invariant()
        assert "120.000000" in hb.value.message

    def test_bondlar_terminal_durumda_sayilmaz(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        _itiraz_ac(kasa, is_.job_id)
        is_.status = EscrowStatus.SETTLED  # terminal → bond-artık-gereksinimde-YOK
        kasa.ledger_balances[USDC] = Decimal("100")
        assert kasa.check_solvency_invariant() is True

    def test_yetim_dispute_invariant_hatasi(self, kasa):
        """BULGU (DUZELTILDI PACTA-VLT-1): check_solvency_invariant,
        ``self.disputes``-içindeki-bir-dispute'un ``job_id``'si
        ``self.jobs``'te-YOKSA artik **fail-closed InvariantViolationError**
        firlatir (eskiden ham KeyError-cokusu). Graceful-atlama yerine
        fail-closed-sectik: bag-eksik-saymak-invariant'i-zayiflatirdi."""
        kasa.disputes["d1"] = DisputeClaim(
            job_id="yok-boyle-is", claimant_address=ALICI,
            bond_amount_usdc=Decimal("1"), reason="sebep", evidence_hash="0xK")
        with pytest.raises(InvariantViolationError) as hb:
            kasa.check_solvency_invariant()
        assert "Orphan dispute" in hb.value.message

    def test_bakiye_kaydi_eksik_invariant_hatasi(self, kasa):
        """BULGU (DUZELTILDI PACTA-VLT-3-TAMAMLAMA): denetlenen-token'in-KASA-
        KAYDI-eksikse ( kirilmis-bakiye-defteri) eskiden HAM ``KeyError`` dışarı
        sızıyordu — ne yetersizlik-ne-yetim-dispute dalına-girerdi. Artık
        fail-closed ``InvariantViolationError`` ( PACTA-VLT-1 örneği: kayıt-
        bütünlüğü-ihlali-kendi-başına-bir-invariant-bozukluğudur; bakiyeyi-
        sessizce-0-saymak-invariant'i-zayiflatirdi)."""
        _kilitle(kasa, Decimal("100"))
        del kasa.ledger_balances[USDC]
        with pytest.raises(InvariantViolationError) as hb:
            kasa.check_solvency_invariant()
        assert "Solvency Invariant Broken" in hb.value.message
        assert "Kasa-bakiye-kaydı-EKSİK" in hb.value.message

    def test_bakiye_kaydi_mevcut_normal_yol_bozuk_degil(self, kasa):
        """Koruma-pin: onarım-normal-yolu-BOZMAZ — taze-kasa-defterinde-USDC-
        kaydı-vardır ( 0.000000) ve invariant-True-döner ( KeyError-yok)."""
        assert USDC in kasa.ledger_balances
        assert kasa.check_solvency_invariant() is True


# ================================================ create_and_lock_escrow
class TestCreateAndLockEscrow:
    """create_and_lock_escrow dalları:
    * başarı: iş-oluşur + ledger'a-deposit + ESCROW_LOCKED + locked_at-dolu
    * policy=None → varsayılan-EscrowPolicy / policy-aktarılır
    * adres-doğrulama ( AT-169): non-str / 0x-önek-YOK / len<4 / hex-OLAYAN
      → ValueError; 2-hex-karakter-sınırı ( "0x12"-geçerli); büyük-hex-geçerli
    * amount: int/str/float/Decimal kabul; 6-desimal-quantize ROUND_HALF_UP;
      0/negatif → ValueError ( model); toz-miktar ( 1e-7) → 0'a-yuvarlanıp-RED
    * job_id: None → uuid4; boş-string → ValueError; null-byte → ValueError;
      çakışma → ValueError ( ledger-DOKUNULMAMLIŞ)
    * idempotency_key ( AT-184): aynı-anahtar → MEVCUT-iş-döner ( para-hareket-
      ETMEZ); farklı-anahtarlar → yeni-iş; boş-string-anahtarı-None-DEĞİL;
      anahtar-silinmiş-işe-bağlıysa → yeni-iş-oluşur-anahtar-yeniden-bağlanır
    """

    def test_basari_temel(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        assert is_.buyer_address == ALICI
        assert is_.seller_address == SATICI
        assert is_.amount_usdc == Decimal("100.000000")
        assert is_.status == EscrowStatus.ESCROW_LOCKED
        assert is_.locked_at_epoch_ms is not None
        assert kasa.jobs[is_.job_id] is is_
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    @pytest.mark.parametrize("amount,beklenen", [
        (100, "100.000000"),
        ("100", "100.000000"),
        (Decimal("99.9999995"), "100.000000"),
        ("10.1234565", "10.123457"),   # ROUND_HALF_UP-7.-hanede-5-yukarı
        (1.5, "1.500000"),
    ])
    def test_amount_quantize(self, kasa, amount, beklenen):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, amount)
        assert is_.amount_usdc == Decimal(beklenen)
        assert kasa.ledger_balances[USDC] == Decimal(beklenen)

    @pytest.mark.parametrize("amount", [0, -1, Decimal("-0.5"), "0"])
    def test_sifir_ve_negatif_reddedilir(self, kasa, amount):
        with pytest.raises(ValueError, match="strictly positive"):
            kasa.create_and_lock_escrow(ALICI, SATICI, amount)
        assert len(kasa.jobs) == 0
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")

    def test_toz_miktar_yuvarlanip_reddedilir(self, kasa):
        """Sınır: 0.0000001 → quantize-0.000000 → model 'strictly positive'-RED."""
        with pytest.raises(ValueError, match="strictly positive"):
            kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("0.0000001"))

    def test_policy_varsayilan_ve_ozel(self, kasa):
        o = kasa.create_and_lock_escrow(ALICI, SATICI, 1)
        assert isinstance(o.policy, EscrowPolicy)
        assert o.policy.timeout_ms == 5000  # varsayılan
        ozel = EscrowPolicy(timeout_ms=99, fee_rate_basis_points=100)
        o2 = kasa.create_and_lock_escrow(ALICI, SATICI, 1, policy=ozel)
        assert o2.policy is ozel
        assert o2.policy.timeout_ms == 99

    @pytest.mark.parametrize("etiket,adres", [
        ("buyer", None),       # non-str
        ("buyer", 1234),       # non-str
        ("buyer", b"0x1234"),  # non-str
        ("buyer", "0x"),       # len<4 ( 0-hex-karakter)
        ("buyer", "0x1"),      # len<4 ( 1-hex-karakter)
        ("buyer", "0xZZ12"),   # hex-OLMAYAN-karakter
        ("buyer", "1x1234"),   # 0x-önek-YOK
        ("seller", None),
        ("seller", "0x"),
        ("seller", "0xGG"),
    ])
    def test_gecersiz_adres_reddedilir(self, kasa, etiket, adres):
        buyer = adres if etiket == "buyer" else ALICI
        seller = adres if etiket == "seller" else SATICI
        with pytest.raises(ValueError) as hb:
            kasa.create_and_lock_escrow(buyer, seller, 1)
        assert f"Invalid {etiket} address" in str(hb.value)
        assert "AT-169" in str(hb.value)
        assert len(kasa.jobs) == 0
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")

    @pytest.mark.parametrize("adres", ["0x12", "0xAbCdEf", "0x" + "a" * 40])
    def test_sinir_gecerli_adresler(self, kasa, adres):
        """Sınır: tam-2-hex-karakter ( len=4) ve büyük-harf-geçerli."""
        is_ = kasa.create_and_lock_escrow(adres, adres, 1)
        assert is_.buyer_address == adres

    def test_job_id_none_uuid_uretilir(self, kasa):
        is_ = _kilitle(kasa)
        assert is_.job_id is not None
        assert len(is_.job_id) == 36  # uuid4-formatı

    def test_job_id_ozel_kullanilir(self, kasa):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, 1, job_id="ozel-1")
        assert is_.job_id == "ozel-1"
        assert "ozel-1" in kasa.jobs

    def test_job_id_bos_string_reddedilir(self, kasa):
        with pytest.raises(ValueError, match="job_id-empty"):
            kasa.create_and_lock_escrow(ALICI, SATICI, 1, job_id="")
        assert len(kasa.jobs) == 0

    def test_job_id_null_byte_reddedilir(self, kasa):
        with pytest.raises(ValueError, match="job_id-invalid"):
            kasa.create_and_lock_escrow(ALICI, SATICI, 1, job_id="a\x00b")
        assert len(kasa.jobs) == 0

    def test_job_id_cakismasi_reddedilir(self, kasa):
        """AT-182: mevcut-job'ı-sessizce-üzerine-yazmak-YASAK ( fon-kaybı)."""
        kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"), job_id="j1")
        with pytest.raises(ValueError, match="job_id_collision") as hb:
            kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("50"), job_id="j1")
        assert "j1" in str(hb.value)
        # ledger'a-50-eklenmemiş-olmalı ( reddin-önce-deposit-öncesi)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")
        assert len(kasa.jobs) == 1

    def test_idempotency_ayni_anahtar_mevcut_donulur(self, kasa):
        """AT-184: aynı-anahtar-ikinci-çağrıda MEVCUT-iş-döner ( para-2x-HAREKET-ETMEZ)."""
        ilk = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          idempotency_key="k1")
        ikinci = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                             idempotency_key="k1")
        assert ikinci is ilk
        assert len(kasa.jobs) == 1
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_idempotency_farkli_anahtarlar_yeni_is(self, kasa):
        kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="k1")
        iki = kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="k2")
        assert len(kasa.jobs) == 2
        assert kasa._idempotency_keys["k2"] == iki.job_id

    def test_idempotency_bos_string_anahtar_none_degildir(self, kasa):
        """Sınır: ""-anahtarı None-DEĞİL — bir-anahtar-gibi-davranır."""
        ilk = kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="")
        assert kasa._idempotency_keys[""] == ilk.job_id
        iki = kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="")
        assert iki is ilk

    def test_idempotency_silinmis_ise_yeniden_baglanir(self, kasa):
        ilk = kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="k1")
        del kasa.jobs[ilk.job_id]
        # anahtar-hâlâ-kayıtlı-AMA-iş-silinmiş → yeni-iş-oluşmalı
        iki = kasa.create_and_lock_escrow(ALICI, SATICI, 1, idempotency_key="k1")
        assert iki is not ilk
        assert kasa._idempotency_keys["k1"] == iki.job_id
        assert iki.job_id in kasa.jobs

    def test_deposit_token_ledgerda(self, kasa):
        is_ = _kilitle(kasa)
        assert is_.deposit_token == USDC
        assert USDC in kasa.ledger_balances


# ============================================================ submit_output
class TestSubmitOutput:
    """submit_output dalları:
    * iş-yok → EscrowNotFoundError
    * SLA-içinde → OUTPUT_SUBMITTED + payload/receipt/ Sertifikalar-kayıtlanır
    * TAM-EŞİTLİK ( diff == timeout_ms) → zaman-aşımı-YOK ( sınır)
    * +1ms-aşım → AUTO_REFUNDED_TIMEOUT + ledger'dan-iade + payload-AYARLANMAZ
      + BULGU: settled_at_epoch_ms-AYARLANMAZ ( denetim-zamanı-kaybı)
    * locked_at=None → zaman-aşımı-kontrolü-ATLANIR ( falsy-dal)
    * terminal-durum + aşım → InvalidStateTransitionError ( ledger-DOKUNULMAMIŞ)
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.submit_output("yok", {})

    def test_basari_payload_kayitlanir(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, 1,
                                          policy=EscrowPolicy(timeout_ms=1000))
        receipt = TamgaExecutionReceipt(
            job_id=is_.job_id, program_hash="p", input_commitment="i",
            output_hash="o", wasi_trace_root="w", instruction_count=1,
            timestamp_epoch=1, signature="s")
        sertifika = ZkTLSCertificate(
            session_id="s", server_name="n", data_hash="h",
            zk_proof_snark="x" * 32, attestation_key="k")
        dönen = kasa.submit_output(is_.job_id, {"cikti": 1},
                                   tamga_receipt=receipt, zktls_cert=sertifika)
        assert dönen.status == EscrowStatus.OUTPUT_SUBMITTED
        assert dönen.output_payload == {"cikti": 1}
        assert dönen.tamga_receipt is receipt
        assert dönen.zktls_cert is sertifika
        assert dönen.submitted_at_epoch_ms == int(saat["su_an"] * 1000)
        assert kasa.ledger_balances[USDC] == Decimal("1.000000")

    def test_sla_tam_esitlikte_zaman_asimi_yok(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, 1,
                                          policy=EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 1.0  # diff = 1000ms == timeout → AŞIM-YOK
        dönen = kasa.submit_output(is_.job_id, {"cikti": 1})
        assert dönen.status == EscrowStatus.OUTPUT_SUBMITTED

    def test_sla_asiminda_otomatik_iade(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 2.0  # diff = 2000ms > 1000ms
        dönen = kasa.submit_output(is_.job_id, {"cikti": 1})
        assert dönen.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")
        assert dönen.output_payload is None  # payload-kayıtlanmamış-döner

    def test_sla_asiminda_settled_at_doludur(self, kasa, saat):
        """BULGU (DUZELTILDI PACTA-VLT-2): submit_output'un zaman-aşımı-dalı
        artik ``settled_at_epoch_ms``'i-AYARLAR — terminal-iaudenin-zaman-
        damgasi-denetim-kaydında-kayıp-degil (diger-settle-dalları-gibi)."""
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, 1,
                                          policy=EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 2.0
        dönen = kasa.submit_output(is_.job_id, {"cikti": 1})
        assert dönen.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
        assert dönen.settled_at_epoch_ms is not None
        assert dönen.settled_at_epoch_ms > 0

    def test_locked_at_yoksa_asim_kontrolu_atlanir(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, 1,
                                          policy=EscrowPolicy(timeout_ms=1))
        is_.locked_at_epoch_ms = None  # falsy → aşım-dalına-GİRİLMEZ
        saat["su_an"] = 1_000_000.0 + 100.0
        dönen = kasa.submit_output(is_.job_id, {"cikti": 1})
        assert dönen.status == EscrowStatus.OUTPUT_SUBMITTED

    def test_terminal_durum_asimda_fsm_hatasi(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1000))
        is_.status = EscrowStatus.SETTLED
        saat["su_an"] = 1_000_000.0 + 2.0
        with pytest.raises(InvalidStateTransitionError):
            kasa.submit_output(is_.job_id, {"cikti": 1})
        # FSM-geçişi-para-akışından-ÖNCE-kontrol-edilir → ledger-DOKUNULMAMIŞ
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")


# ========================================================= mark_verified_ok
class TestMarkVerifiedOk:
    """mark_verified_ok dalları:
    * iş-yok → EscrowNotFoundError
    * OUTPUT_SUBMITTED → VERIFIED_OK ( başarı)
    * GEÇERSİZ-geçişler ( ESCROW_LOCKED/VERIFIED_OK/terminal) →
      InvalidStateTransitionError + ledger-DOKUNULMAMIŞ
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.mark_verified_ok("yok")

    def test_basari_output_submitted_verified_ok(self, kasa):
        is_ = _kilitle(kasa)
        kasa.submit_output(is_.job_id, {"cikti": 1})
        dönen = kasa.mark_verified_ok(is_.job_id)
        assert dönen.status == EscrowStatus.VERIFIED_OK

    @pytest.mark.parametrize("durum", [
        EscrowStatus.ESCROW_LOCKED,   # ara-atla-yasak
        EscrowStatus.VERIFIED_OK,     # zaten-doğrulandı
        EscrowStatus.SETTLED,         # terminal
        EscrowStatus.AUTO_REFUNDED_TIMEOUT,
    ])
    def test_gecersiz_gecis_hatasi(self, kasa, durum):
        is_ = _kilitle(kasa, Decimal("100"))
        is_.status = durum
        with pytest.raises(InvalidStateTransitionError):
            kasa.mark_verified_ok(is_.job_id)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")


# ============================================================ settle_escrow
class TestSettleEscrow:
    """settle_escrow dalları:
    * iş-yok → EscrowNotFoundError
    * caller=None → UserWarning + PACTA_REQUIRE_CALLER_ROLE-ortam-kapısı:
      her-değer ( "0"/"false"-dahil) RED, yalnızca-BOŞ/setting-YOK geçer
    * caller alıcı/satıcı → geçer ( büyük-küçük-harf-duyarsız)
    * caller yabancı → EscrowAuthorizationError ( AT-180)
    * VERIFIED_OK → OPTIMISTIC_SETTLED → SETTLED + fee/net/ledger-muhasebesi
      + EIP-1559-benzeri-keccak256-tx-hash
    * VERIFIED_OK-DEĞİL → doğrudan-SETTLED ( OPTIMISTIC_SETTLED'den) /
      InvalidStateTransitionError ( OUTPUT_SUBMITTED'den)
    * SLA-aşımı-settle-kapısında-reddedilir ( AT-165) — TAM-EŞİTLİK-geçer
    * chain_adapter → anchor-çağrısı + terms-doğruluğu
    * d5_ledger → SettlementBinder.bind_settled_job-çağrısı
    * çift-settle → InvalidStateTransitionError ( ledger-DOKUNULMAMIŞ)
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.settle_escrow("yok")

    def test_basari_tam_muhasebe(self, kasa, saat):
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        job, tx = kasa.settle_escrow(is_.job_id)
        assert job.status == EscrowStatus.SETTLED
        assert job.settled_at_epoch_ms == int(saat["su_an"] * 1000)
        assert job.fee_collected_usdc == Decimal("0.750000")  # 75bps
        assert job.net_seller_amount() == Decimal("99.250000")
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")
        assert kasa.total_protocol_revenue_usdc == Decimal("0.750000")
        assert job.settlement_tx == tx
        assert tx.startswith("0x") and len(tx) == 66  # keccak256-hex

    def test_tx_hash_deterministik_ve_essiz(self, kasa):
        a = _dogrulanmis_is(kasa, Decimal("100"), EscrowPolicy(timeout_ms=5000))
        b = _dogrulanmis_is(kasa, Decimal("100"), EscrowPolicy(timeout_ms=5000))
        _, tx_a = kasa.settle_escrow(a.job_id)
        _, tx_b = kasa.settle_escrow(b.job_id)
        assert tx_a != tx_b  # farklı-job_id → farklı-hash

    def test_caller_none_uyari_verir_ve_settler(self, kasa):
        is_ = _dogrulanmis_is(kasa)
        with pytest.warns(UserWarning, match="caller-missing"):
            job, _ = kasa.settle_escrow(is_.job_id)
        assert job.status == EscrowStatus.SETTLED

    @pytest.mark.parametrize("deger", ["1", "0", "false", "yes"])
    def test_caller_none_ortam_kapisi_reddeder(self, kasa, monkeypatch, deger):
        """AT-184: PACTA_REQUIRE_CALLER_ROLE her-DOĞRULU-string-değerde-RED
        ( '0'/'false'-dahil — boş-string-AYRI; ortam-değeri-truthy-string)."""
        monkeypatch.setenv("PACTA_REQUIRE_CALLER_ROLE", deger)
        is_ = _dogrulanmis_is(kasa)
        with pytest.warns(UserWarning, match="caller-missing"):
            with pytest.raises(EscrowNotFoundError, match="caller-required"):
                kasa.settle_escrow(is_.job_id)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    @pytest.mark.parametrize("caller", [ALICI, SATICI, ALICI.upper(), SATICI.upper()])
    def test_caller_taraf_gecerli(self, kasa, caller):
        is_ = _dogrulanmis_is(kasa)
        job, _ = kasa.settle_escrow(is_.job_id, caller_address=caller)
        assert job.status == EscrowStatus.SETTLED

    def test_caller_yabanci_reddedilir(self, kasa):
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        with pytest.raises(EscrowAuthorizationError) as hb:
            kasa.settle_escrow(is_.job_id, caller_address=YABANCI)
        assert "neither buyer nor seller" in hb.value.message
        assert "AT-180" in hb.value.message
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")
        assert kasa.total_protocol_revenue_usdc == Decimal("0.000000")

    def test_rol_kontrolu_durum_kontrolunden_once(self, kasa):
        """Sıra-dalı: yabancı-çağıran-ÖNCE-reddedilir ( durum-geçersiz-bile-olsa)."""
        is_ = _kilitle(kasa)  # INITIALIZED → SETTLED-geçersiz-AMA-rol-önce
        with pytest.raises(EscrowAuthorizationError):
            kasa.settle_escrow(is_.job_id, caller_address=YABANCI)

    def test_optimistik_settled_den_settled(self, kasa):
        is_ = _dogrulanmis_is(kasa)
        is_.status = EscrowStatus.OPTIMISTIC_SETTLED
        job, _ = kasa.settle_escrow(is_.job_id)
        assert job.status == EscrowStatus.SETTLED

    def test_output_submitted_den_settle_gecersiz(self, kasa):
        is_ = _kilitle(kasa)
        kasa.submit_output(is_.job_id, {"cikti": 1})
        with pytest.raises(InvalidStateTransitionError):
            kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_sla_asiminda_settle_kapida_reddedilir(self, kasa, saat):
        """AT-165: SLA-aşan-satıcı-settle'ı-alamaz ( refund_timeout'a-yönlendir)."""
        is_ = _dogrulanmis_is(kasa, Decimal("100"), EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 2.0  # diff 2000ms > 1000ms
        with pytest.raises(EscrowNotFoundError) as hb:
            kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert "settle-refused" in hb.value.message
        assert "exceeded timeout SLA" in hb.value.message
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_sla_tam_esitlikte_settle_gecerli(self, kasa, saat):
        is_ = _dogrulanmis_is(kasa, Decimal("100"), EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 1.0  # diff == timeout → AŞIM-YOK
        job, _ = kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert job.status == EscrowStatus.SETTLED

    def test_chain_adapter_anchor_cagrilir(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        job, _ = kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert len(adapter.anchor_cagrilari) == 1
        cagri = adapter.anchor_cagrilari[0]
        assert cagri["job_id"] == is_.job_id
        assert cagri["anchor_kind"] == "settlement"
        assert cagri["to_address"] == SATICI
        terms = cagri["terms"]
        assert terms["amount_usdc"] == "100.000000"
        assert terms["fee_usdc"] == "0.750000"
        assert terms["net_seller_usdc"] == "99.250000"
        assert terms["buyer"] == ALICI
        assert terms["seller"] == SATICI
        assert terms["settled_at_ms"] == str(job.settled_at_epoch_ms)
        assert job.chain_anchor == adapter.yanit

    def test_chain_adapter_yoksa_anchor_yok(self, kasa):
        is_ = _dogrulanmis_is(kasa)
        job, _ = kasa.settle_escrow(is_.job_id)
        assert job.chain_anchor is None

    def test_d5_ledger_binding_yazilir(self, kasa, monkeypatch):
        baglayici = _SahteBaglayici()
        monkeypatch.setitem(sys.modules, "pacta.integrations.tamga_d5",
                            SimpleNamespace(SettlementBinder=baglayici))
        ledger = object()
        kasa = PactaEscrowVault(d5_ledger=ledger)
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        job, _ = kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert len(baglayici.cagrilar) == 1
        assert baglayici.cagrilar[0][0] == is_.job_id
        assert baglayici.cagrilar[0][1] is ledger
        assert job.settlement_binding == {"charge": "ok", "job_id": is_.job_id}

    def test_d5_ledger_yoksa_binding_yok(self, kasa):
        is_ = _dogrulanmis_is(kasa)
        job, _ = kasa.settle_escrow(is_.job_id)
        assert job.settlement_binding is None

    def test_cift_settle_reddedilir(self, kasa):
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        with pytest.raises(InvalidStateTransitionError):
            kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")
        assert kasa.total_protocol_revenue_usdc == Decimal("0.750000")


# ============================================================== anchor_job
class TestAnchorJob:
    """anchor_job dalları:
    * chain_adapter=None → ChainUnavailableError ( AT-194 dürüst-hata)
    * iş-yok → EscrowNotFoundError
    * başarı: terms-alanları + anchor-aktarılır + job.chain_anchor-ayarlanır
    * PACTA-VLT-4: fee_collected None ( settle-öncesi-varsayılan) →
      terms'te fee_usdc YOK / settle-sonrası-gerçek-değer → eklenir
    * settled_at_epoch_ms YOK/0 → terms'te YOK / VAR → eklenir
    * anchor_kind-çağrıya-aktarılır ( varsayılan: settlement)
    """

    def test_adapter_yoksa_chain_hatasi(self, kasa):
        with pytest.raises(ChainUnavailableError) as hb:
            kasa.anchor_job("herhangi")
        assert "no-chain-adapter" in str(hb.value)
        assert "connect_in_memory_evm" in str(hb.value)

    def test_is_yok_hatasi(self, kasa):
        kasa = PactaEscrowVault(chain_adapter=_SahteAdapter())
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.anchor_job("yok")

    def test_basari_terms_ve_anchor(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        is_ = _kilitle(kasa, Decimal("100"))
        anchor = kasa.anchor_job(is_.job_id)
        assert anchor == adapter.yanit
        assert is_.chain_anchor == adapter.yanit
        cagri = adapter.anchor_cagrilari[0]
        assert cagri["anchor_kind"] == "settlement"
        assert cagri["to_address"] == SATICI
        terms = cagri["terms"]
        assert terms["amount_usdc"] == "100.000000"
        assert terms["status"] == "ESCROW_LOCKED"
        assert terms["buyer"] == ALICI
        assert terms["seller"] == SATICI
        # BULGU (DUZELTILDI PACTA-VLT-4): fee_collected_usdc varsayılanı artık
        # None ("henüz-tahsil-edilmedi") — settle-ÖNCESİ-bir-işin-zincir-bağı-
        # terms'ine sahte "fee_usdc=0.000000" sabitlenMEZ ( sessiz-sıfır-ücret).
        assert "fee_usdc" not in terms
        assert "settled_at_ms" not in terms

    def test_fee_settled_olunca_terms_eklenir(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        is_ = _dogrulanmis_is(kasa, Decimal("100"))
        kasa.settle_escrow(is_.job_id, caller_address=ALICI)
        kasa.anchor_job(is_.job_id, anchor_kind="refund")
        cagri = adapter.anchor_cagrilari[-1]
        assert cagri["anchor_kind"] == "refund"
        assert cagri["terms"]["fee_usdc"] == "0.750000"
        assert cagri["terms"]["settled_at_ms"] == str(is_.settled_at_epoch_ms)
        assert cagri["terms"]["status"] == "SETTLED"

    def test_settled_at_sifir_eklenmez(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        is_ = _kilitle(kasa)
        is_.settled_at_epoch_ms = 0  # falsy → terms'te-YOK
        kasa.anchor_job(is_.job_id)
        assert "settled_at_ms" not in adapter.anchor_cagrilari[0]["terms"]


# ==================================================== verify_chain_anchors
class TestVerifyChainAnchors:
    """verify_chain_anchors dalları:
    * chain_adapter=None → boş-sözlük
    * bağı-YOK-işler-hariç-tutulur
    * bağı-OLAN-işler → verify_anchor-sonucu
    * karışık ( bazı-var/bazı-yok) → yalnızca-bağı-olanlar
    """

    def test_adapter_yoksa_bos(self, kasa):
        _kilitle(kasa)
        assert kasa.verify_chain_anchors() == {}

    def test_bag_yoksa_haric(self, kasa):
        kasa = PactaEscrowVault(chain_adapter=_SahteAdapter())
        a = _kilitle(kasa)
        b = _kilitle(kasa)
        assert kasa.verify_chain_anchors() == {}
        assert a.chain_anchor is None and b.chain_anchor is None

    def test_bag_olanlar_dogrulanir(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        is_ = _kilitle(kasa)
        kasa.anchor_job(is_.job_id)
        sonuc = kasa.verify_chain_anchors()
        assert sonuc == {is_.job_id: True}
        assert len(adapter.verify_cagrilari) == 1

    def test_karisik_bazi_var_bazi_yok(self, kasa):
        adapter = _SahteAdapter()
        kasa = PactaEscrowVault(chain_adapter=adapter)
        a = _kilitle(kasa)
        b = _kilitle(kasa)
        kasa.anchor_job(a.job_id)
        sonuc = kasa.verify_chain_anchors()
        assert list(sonuc.keys()) == [a.job_id]
        assert b.job_id not in sonuc


# ========================================================== refund_timeout
class TestRefundTimeout:
    """refund_timeout dalları:
    * iş-yok → EscrowNotFoundError
    * SLA-içinde → EscrowNotFoundError('refund-refused') ( AT-165)
    * TAM-EŞİTLİK ( diff == timeout) → hala-reddedilir ( '>'-sınırı)
    * locked_at=None/YOK → reddedilir ( falsy-dal)
    * SLA-aşımı → AUTO_REFUNDED_TIMEOUT + ledger-iade + settled_at-dolu
    * terminal-durum + aşım → InvalidStateTransitionError ( ledger-DOKUNULMAMIŞ)
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.refund_timeout("yok")

    def test_sla_icinde_reddedilir(self, kasa):
        is_ = _kilitle(kasa)
        with pytest.raises(EscrowNotFoundError) as hb:
            kasa.refund_timeout(is_.job_id)
        assert "refund-refused" in hb.value.message
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_sla_tam_esitlikte_reddedilir(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 1.0  # diff == timeout → '>'-SAĞLANMAZ
        with pytest.raises(EscrowNotFoundError, match="refund-refused"):
            kasa.refund_timeout(is_.job_id)

    def test_locked_at_yoksa_reddedilir(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1))
        is_.locked_at_epoch_ms = None
        saat["su_an"] = 1_000_000.0 + 100.0
        with pytest.raises(EscrowNotFoundError, match="refund-refused"):
            kasa.refund_timeout(is_.job_id)

    def test_sla_asiminda_iade_edilir(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1000))
        saat["su_an"] = 1_000_000.0 + 2.0
        dönen = kasa.refund_timeout(is_.job_id)
        assert dönen.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
        assert dönen.settled_at_epoch_ms == int(saat["su_an"] * 1000)
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")

    def test_terminal_durum_asimda_fsm_hatasi(self, kasa, saat):
        is_ = kasa.create_and_lock_escrow(ALICI, SATICI, Decimal("100"),
                                          policy=EscrowPolicy(timeout_ms=1000))
        is_.status = EscrowStatus.SETTLED
        saat["su_an"] = 1_000_000.0 + 2.0
        with pytest.raises(InvalidStateTransitionError):
            kasa.refund_timeout(is_.job_id)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")


# =================================================== refund_quality_failure
class TestRefundQualityFailure:
    """refund_quality_failure dalları:
    * iş-yok → EscrowNotFoundError
    * SLA-KONTROLÜ-YOK ( AT-165 rol-ayrımı: kalite-başarısızlığı-zamanında-da-iade)
    * caller=None → UserWarning + PACTA_REQUIRE_CALLER_ROLE-kapısı
    * caller alıcı/satıcı → geçer / yabancı → EscrowAuthorizationError ( AT-180)
    * terminal-durum → InvalidStateTransitionError ( ledger-DOKUNULMAMIŞ)
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.refund_quality_failure("yok")

    def test_sla_kontrolu_yok_iade_edilir(self, kasa):
        """refund_timeout'tan-FARKI: kalite-iadesinde-SLA-kapısı-YOK."""
        is_ = _kilitle(kasa, Decimal("100"))
        dönen = kasa.refund_quality_failure(is_.job_id)
        assert dönen.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")
        assert dönen.settled_at_epoch_ms is not None

    def test_caller_none_uyari_verir(self, kasa):
        is_ = _kilitle(kasa)
        with pytest.warns(UserWarning, match="caller-missing"):
            dönen = kasa.refund_quality_failure(is_.job_id)
        assert dönen.status == EscrowStatus.AUTO_REFUNDED_TIMEOUT

    @pytest.mark.parametrize("deger", ["1", "0", "false"])
    def test_caller_none_ortam_kapisi_reddeder(self, kasa, monkeypatch, deger):
        monkeypatch.setenv("PACTA_REQUIRE_CALLER_ROLE", deger)
        is_ = _kilitle(kasa, Decimal("100"))
        with pytest.warns(UserWarning, match="caller-missing"):
            with pytest.raises(EscrowNotFoundError, match="caller-required"):
                kasa.refund_quality_failure(is_.job_id)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    @pytest.mark.parametrize("caller", [ALICI, SATICI])
    def test_caller_taraf_gecerli(self, kasa, caller):
        is_ = _kilitle(kasa)
        assert kasa.refund_quality_failure(is_.job_id,
                                           caller_address=caller).status \
            == EscrowStatus.AUTO_REFUNDED_TIMEOUT

    def test_caller_yabanci_reddedilir(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        with pytest.raises(EscrowAuthorizationError) as hb:
            kasa.refund_quality_failure(is_.job_id, caller_address=YABANCI)
        assert "neither buyer nor seller" in hb.value.message
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_terminal_durum_fsm_hatasi(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        is_.status = EscrowStatus.SETTLED
        with pytest.raises(InvalidStateTransitionError):
            kasa.refund_quality_failure(is_.job_id, caller_address=ALICI)
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")


# ============================================================= raise_dispute
class TestRaiseDispute:
    """raise_dispute dalları:
    * iş-yok → EscrowNotFoundError
    * claimant alıcı/satıcı → geçer ( büyük-küçük-harf-duyarsız);
      yabancı → EscrowAuthorizationError ( AT-166)
    * dispute-penceresi ( AT-165): pencere-içi-geçer / TAM-EŞİTLİK-geçer /
      +1s-aşım → EscrowNotFoundError('dispute-window-expired');
      dispute_window_sec=0 → pencere-kontrolü-YOK
    * pencere-kontrolü-ÖNCE-FSM'den: terminal-iş + eski-zaman → pencere-hatası
    * FSM-geçersiz ( ESCROW_LOCKED/terminal) → InvalidStateTransitionError +
      bond-TOPLANMAMIŞ ( AT-171: para-akışı-ancak-geçerli-geçişte)
    * başarı: bond=amount*ratio quantize + ledger'a-eklenir + DISPUTED →
      ARBITRATION_IN_PROGRESS + DisputeClaim-alanları
    * çift-itiraz → InvalidStateTransitionError
    """

    def test_is_yok_hatasi(self, kasa):
        with pytest.raises(EscrowNotFoundError, match="not found"):
            kasa.raise_dispute("yok", ALICI, "s", "0xK")

    @pytest.mark.parametrize("claimant", [ALICI, SATICI, ALICI.upper()])
    def test_claimant_taraf_gecerli(self, kasa, claimant):
        is_ = _kilitle(kasa)
        d = _itiraz_ac(kasa, is_.job_id, claimant)
        assert d.claimant_address == claimant
        assert is_.status == EscrowStatus.ARBITRATION_IN_PROGRESS

    def test_claimant_yabanci_reddedilir(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        with pytest.raises(EscrowAuthorizationError) as hb:
            kasa.raise_dispute(is_.job_id, YABANCI, "sebep", "0xK")
        assert "neither buyer nor seller" in hb.value.message
        assert "AT-166" in hb.value.message
        assert len(kasa.disputes) == 0
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_basari_bond_ve_durum(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        assert d.job_id == is_.job_id
        assert d.bond_amount_usdc == Decimal("20.000000")  # %20
        assert d.reason == "kalite-kotu"
        assert d.evidence_hash == "0xKANIT"
        assert kasa.ledger_balances[USDC] == Decimal("120.000000")
        assert is_.status == EscrowStatus.ARBITRATION_IN_PROGRESS
        assert kasa.disputes[d.dispute_id] is d

    def test_pencere_icinde_gecerli(self, kasa, saat):
        is_ = _kilitle(kasa, policy=EscrowPolicy(timeout_ms=10_000))
        kasa.submit_output(is_.job_id, {"cikti": 1})  # submitted_at = şimdi
        saat["su_an"] = 1_000_000.0 + 30.0  # 30s < 60s-pencere
        assert _itiraz_ac(kasa, is_.job_id) is not None

    def test_pencere_tam_esitlikte_gecerli(self, kasa, saat):
        is_ = _kilitle(kasa, policy=EscrowPolicy(timeout_ms=10_000))
        kasa.submit_output(is_.job_id, {"cikti": 1})
        saat["su_an"] = 1_000_000.0 + 60.0  # elapsed == 60 → '>'-SAĞLANMAZ
        assert _itiraz_ac(kasa, is_.job_id) is not None

    def test_pencere_asiminda_reddedilir(self, kasa, saat):
        is_ = _kilitle(kasa, policy=EscrowPolicy(timeout_ms=10_000))
        kasa.submit_output(is_.job_id, {"cikti": 1})
        saat["su_an"] = 1_000_000.0 + 61.0  # 61s > 60s
        with pytest.raises(EscrowNotFoundError) as hb:
            kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")
        assert "dispute-window-expired" in hb.value.message
        assert len(kasa.disputes) == 0

    def test_pencere_sifirsa_kontrol_yok(self, kasa, saat):
        is_ = _kilitle(kasa, policy=EscrowPolicy(timeout_ms=10_000,
                                                 dispute_window_sec=0))
        kasa.submit_output(is_.job_id, {"cikti": 1})
        saat["su_an"] = 1_000_000.0 + 9_999.0
        assert _itiraz_ac(kasa, is_.job_id) is not None

    def test_ref_noktasi_settled_tercih_edilir(self, kasa, saat):
        """ref_ms = settled_at OR submitted_at — settled-önce-kullanılır."""
        is_ = _kilitle(kasa, policy=EscrowPolicy(timeout_ms=10_000))
        kasa.submit_output(is_.job_id, {"cikti": 1})
        is_.settled_at_epoch_ms = 1  # çok-eski-kesin-zaman → pencere-aşımı
        with pytest.raises(EscrowNotFoundError, match="dispute-window-expired"):
            kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")

    def test_pencere_kontrolu_fsm_den_once(self, kasa):
        """Sıra-dalı: terminal-iş + eski-settled → pencere-hatası
        ( InvalidStateTransitionError-DEĞİL)."""
        is_ = _kilitle(kasa)
        is_.status = EscrowStatus.SETTLED
        is_.settled_at_epoch_ms = 1
        with pytest.raises(EscrowNotFoundError, match="dispute-window-expired"):
            kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")

    def test_fsm_gecersiz_bond_toplanmamis(self, kasa):
        """AT-171: ESCROW_LOCKED → DISPUTED yasak; para-akışı-ÖNCESİ-kontrol."""
        is_ = _kilitle(kasa, Decimal("100"))
        with pytest.raises(InvalidStateTransitionError) as hb:
            kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")
        assert "no bond collected" in hb.value.message
        assert len(kasa.disputes) == 0
        assert kasa.ledger_balances[USDC] == Decimal("100.000000")

    def test_output_submitted_den_itiraz_gecerli(self, kasa):
        is_ = _kilitle(kasa)
        kasa.submit_output(is_.job_id, {"cikti": 1})
        d = kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")
        assert is_.status == EscrowStatus.ARBITRATION_IN_PROGRESS
        assert d.bond_amount_usdc == Decimal("20.000000")

    def test_cift_itiraz_reddedilir(self, kasa):
        is_ = _kilitle(kasa)
        kasa.submit_output(is_.job_id, {"cikti": 1})
        kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")
        with pytest.raises(InvalidStateTransitionError):
            kasa.raise_dispute(is_.job_id, ALICI, "s", "0xK")
        assert len(kasa.disputes) == 1
        assert kasa.ledger_balances[USDC] == Decimal("120.000000")

    @pytest.mark.parametrize("oran,beklenen", [
        (Decimal("0.0"), "0.000000"),
        (Decimal("0.20"), "20.000000"),
        (Decimal("1.0"), "100.000000"),
        (Decimal("0.125"), "12.500000"),
    ])
    def test_bond_orani_quantize(self, kasa, oran, beklenen):
        is_ = _kilitle(kasa, Decimal("100"),
                       policy=EscrowPolicy(dispute_bond_ratio=oran))
        d = _itiraz_ac(kasa, is_.job_id)
        assert d.bond_amount_usdc == Decimal(beklenen)


# ======================================================== resolve_arbitration
class TestResolveArbitration:
    """resolve_arbitration dalları:
    * dispute-yok → ValueError
    * boş-oy-listesi → ValueError ( AT-166)
    * hakem-işin-taraflarından → ValueError ( AT-166 kendi-davasına-bakamaz)
    * oylama: alıcı-çoğunluk / TAM-BERABERLİK alıcıya / satıcı-çoğunluk
    * alıcı-lehine: SLASHED_REFUNDED + tam-iade + bond'un-yarısı-kesilir +
      ledger'dan ( amount+bond) düşülür + ödüller-dağıtılır
    * satıcı-lehine: SETTLED + net-satıcı + bond'un-yarısı + ödeller-0
    * ödül-havuzu ( AT-172): quantize-kalanı-son-çoğunluk-hakemine-eklenir;
      havuz TAMAMEN-dağıtılır ( toplam == bond*0.5)
    * azınlık-oycuları 0-alır / karar outcomes'a-kayıtlanır
    """

    def test_dispute_yok_hatasi(self, kasa):
        with pytest.raises(ValueError, match="Dispute ID"):
            kasa.resolve_arbitration("yok", [_oy(HAKEM1, True)])

    def test_bos_oy_listesi_hatasi(self, kasa):
        is_ = _kilitle(kasa)
        d = _itiraz_ac(kasa, is_.job_id)
        with pytest.raises(ValueError) as hb:
            kasa.resolve_arbitration(d.dispute_id, [])
        assert "at least one vote" in str(hb.value)

    @pytest.mark.parametrize("hakem", [ALICI, SATICI])
    def test_hakem_taraf_olamaz(self, kasa, hakem):
        is_ = _kilitle(kasa)
        d = _itiraz_ac(kasa, is_.job_id)
        with pytest.raises(ValueError) as hb:
            kasa.resolve_arbitration(d.dispute_id, [_oy(hakem, True)])
        assert "is a party of the escrow" in str(hb.value)
        assert kasa.outcomes == {}

    def test_alici_lehine_tam_iade(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, True), _oy(HAKEM2, True),
                           _oy(HAKEM3, False)])
        assert sonuc.buyer_favored is True
        assert sonuc.votes_for_buyer == 2
        assert sonuc.votes_for_seller == 1
        assert sonuc.refunded_to_buyer_usdc == Decimal("100.000000")
        assert sonuc.slashed_seller_bond_usdc == Decimal("10.000000")
        assert sonuc.paid_to_seller_usdc == Decimal("0.000000")
        assert is_.status == EscrowStatus.SLASHED_REFUNDED
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")
        assert kasa.outcomes[d.dispute_id] is sonuc

    def test_beraberlikte_alici_lehine(self, kasa):
        """Sınır: buyer_votes == seller_votes → '>= '-dalı → alıcı-lehine."""
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, True), _oy(HAKEM2, False)])
        assert sonuc.buyer_favored is True
        assert sonuc.votes_for_buyer == 1
        assert sonuc.votes_for_seller == 1

    def test_satici_lehine_odeme(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, False), _oy(HAKEM2, False)])
        assert sonuc.buyer_favored is False
        assert sonuc.refunded_to_buyer_usdc == Decimal("0.000000")
        assert sonuc.slashed_seller_bond_usdc == Decimal("0.000000")
        # net-satıcı 99.25 + bond'un-yarısı 10
        assert sonuc.paid_to_seller_usdc == Decimal("109.250000")
        assert is_.status == EscrowStatus.SETTLED
        assert kasa.ledger_balances[USDC] == Decimal("0.000000")

    def test_oduller_cogunluk_azinlik(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, True), _oy(HAKEM2, True),
                           _oy(HAKEM3, False)])
        # havuz = bond*0.5 = 10 → 2-çoğunluk → 5'er
        assert sonuc.arbitrator_rewards[HAKEM1] == Decimal("5.000000")
        assert sonuc.arbitrator_rewards[HAKEM2] == Decimal("5.000000")
        assert sonuc.arbitrator_rewards[HAKEM3] == Decimal("0.000000")

    def test_kalansiz_bolunme(self, kasa):
        """Bölünme-tam-bölünürse-kalan 0 ( son-hakem-normal-pay-alır)."""
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, True), _oy(HAKEM2, True)])
        havuz = Decimal("10.000000")
        assert sum(sonuc.arbitrator_rewards.values()) == havuz

    def test_kalan_son_cogunluk_hakemine(self, kasa):
        """AT-172: 0.1-havuz/3-hakem → 0.033333+0.033333+0.033334 ( kalan-ek)."""
        is_ = _kilitle(kasa, Decimal("1"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, True), _oy(HAKEM2, True),
                           _oy(HAKEM3, True)])
        assert sonuc.arbitrator_rewards[HAKEM1] == Decimal("0.033333")
        assert sonuc.arbitrator_rewards[HAKEM2] == Decimal("0.033333")
        assert sonuc.arbitrator_rewards[HAKEM3] == Decimal("0.033334")  # kalan
        # HAVUZ-TAMAMEN-DAĞITILIR ( hiçbir-mikro-olarak-YAKILMAZ)
        havuz = (d.bond_amount_usdc * Decimal("0.5")).quantize(
            Decimal("0.000001"))
        assert sum(sonuc.arbitrator_rewards.values()) == havuz
        assert havuz == Decimal("0.100000")

    def test_satici_lehine_azinlik_sifir_alir(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        sonuc = kasa.resolve_arbitration(
            d.dispute_id, [_oy(HAKEM1, False), _oy(HAKEM2, False),
                           _oy(HAKEM3, True)])
        assert sonuc.arbitrator_rewards[HAKEM1] == Decimal("5.000000")
        assert sonuc.arbitrator_rewards[HAKEM3] == Decimal("0.000000")

    def test_solvency_korunur(self, kasa):
        """Karar-sonrası-solvensiz- invariant-çalışır."""
        is_ = _kilitle(kasa, Decimal("100"))
        d = _itiraz_ac(kasa, is_.job_id)
        kasa.resolve_arbitration(d.dispute_id, [_oy(HAKEM1, True)])
        assert kasa.check_solvency_invariant() is True


# =========================================================== get_vault_stats
class TestGetVaultStats:
    """get_vault_stats dalları:
    * boş-kasa → sıfır-sayılar + bakiye-str + is_solvent True
    * dolu-kasa → iş/dispute/karar-sayıları + bakiye-str-olarak
    * PACTA-VLT-3: yetersiz-kasa/yetim-dispute → ÇÖKME-YOK; is_solvent=False
      + solvency_error-mesajı + açık-uyarı ( raporlama-okuması-her-zaman-
      okunabilir-kalır; gerçeği-saklamaz)
    * PACTA-VLT-3-TAMAMLAMA: kasa-bakiye-kaydı-EKSİK ( kirilmis-defter) de
      ÇÖKMEZ — aynı-durum-raporu ( eskiden-ham-KeyError-metriği-500-yapardı)
    """

    def test_bos_kasa(self, kasa):
        istatistik = kasa.get_vault_stats()
        assert istatistik["total_jobs"] == 0
        assert istatistik["total_disputes"] == 0
        assert istatistik["total_resolved_outcomes"] == 0
        assert istatistik["balances"][USDC] == "0.000000"
        assert istatistik["is_solvent"] is True

    def test_dolu_kasa(self, kasa):
        is_ = _kilitle(kasa, Decimal("100"))
        kasa.submit_output(is_.job_id, {"cikti": 1})
        d = _itiraz_ac(kasa, is_.job_id)
        kasa.resolve_arbitration(d.dispute_id, [_oy(HAKEM1, True)])
        istatistik = kasa.get_vault_stats()
        assert istatistik["total_jobs"] == 1
        assert istatistik["total_disputes"] == 1
        assert istatistik["total_resolved_outcomes"] == 1
        assert istatistik["balances"][USDC] == "0.000000"
        assert istatistik["is_solvent"] is True

    def test_bakiye_str_olarak(self, kasa):
        _kilitle(kasa, Decimal("100"))
        assert kasa.get_vault_stats()["balances"][USDC] == "100.000000"
        assert isinstance(kasa.get_vault_stats()["balances"][USDC], str)

    def test_yetersizlikte_durum_raporlanir(self, kasa):
        """BULGU (DUZELTILDI PACTA-VLT-3): get_vault_stats-artık-yetersiz-
        kasada-InvariantViolationError-FIRLATMAZ; solvensizlik-bir-DURUM-
        olarak-döner (is_solvent=False + solvency_error) + açık-uyarı.
        Eskiden-raporlama-amaçlı-okuma-çöküyordu (monitoring-endpoint'i-500)."""
        is_ = _kilitle(kasa, Decimal("100"))
        kasa.ledger_balances[USDC] = Decimal("50")
        with pytest.warns(UserWarning, match="solvency-invariant-BOZUK"):
            istatistik = kasa.get_vault_stats()
        assert istatistik["is_solvent"] is False
        assert "Solvency Invariant Broken" in istatistik["solvency_error"]
        assert istatistik["total_jobs"] == 1
        # Gerçek-bakiye-gizlenmez ( sıfıra-maskelenmez):
        assert istatistik["balances"][USDC] == "50"

    def test_yetim_dispute_durum_raporlanir(self, kasa):
        """PACTA-VLT-3: VLT-1-in-yetim-dispute-invariant-hatası-da-stats-
        okumasını-çökertmez; aynı-durum-raporu-ile-döner."""
        kasa.disputes["d1"] = DisputeClaim(
            job_id="yok-boyle-is", claimant_address=ALICI,
            bond_amount_usdc=Decimal("1"), reason="sebep", evidence_hash="0xK")
        with pytest.warns(UserWarning, match="solvency-invariant-BOZUK"):
            istatistik = kasa.get_vault_stats()
        assert istatistik["is_solvent"] is False
        assert "Orphan dispute" in istatistik["solvency_error"]
        assert istatistik["total_disputes"] == 1

    def test_kirilmis_defter_cokmez_durum_raporlanir(self, kasa):
        """BULGU (DUZELTILDI PACTA-VLT-3-TAMAMLAMA): kasa-bakiye-kaydı-EKSİKSE
        ( kirilmis-defter) eskiden ``get_vault_stats``-içinden-ham-KeyError-
        çıkardı — yani-metrik/monitoring-okuması-500'e-düşerdi ( VLT-3'ün-
        ikinci-çöküş-yolu, ilk-onarımda-yakalanmamıştı). Artık-aynı-durum-
        raporu ( is_solvent=False + solvency_error + uyarı)."""
        _kilitle(kasa, Decimal("100"))
        del kasa.ledger_balances[USDC]
        with pytest.warns(UserWarning, match="solvency-invariant-BOZUK"):
            istatistik = kasa.get_vault_stats()
        assert istatistik["is_solvent"] is False
        assert "Kasa-bakiye-kaydı-EKSİK" in istatistik["solvency_error"]
        assert istatistik["total_jobs"] == 1
        # Eksik-kayıd-sessizce-"0"a-maskeLENMEZ — balances-da-gerçeği-gösterir:
        assert USDC not in istatistik["balances"]


# ====================================================== özel-durum hiyerarşisi
class TestOzelDurumHiyerarsisi:
    """Exception-dalları: InvariantViolationError/EscrowNotFoundError ayrı;
    EscrowAuthorizationError, EscrowNotFoundError'nın-ALT-SINIFIDIR ( AT-192:
    additive — mevcut 'except EscrowNotFoundError' çağrıları-kırılmaz) +
    .message-özniteliği-taşınır."""

    def test_authorization_not_found_alt_sinif(self):
        assert issubclass(EscrowAuthorizationError, EscrowNotFoundError)

    def test_invariant_ayri(self):
        assert not issubclass(InvariantViolationError, EscrowNotFoundError)

    @pytest.mark.parametrize("hata", [
        InvariantViolationError("m1"), EscrowNotFoundError("m2"),
        EscrowAuthorizationError("m3"),
    ])
    def test_message_oznititigi(self, hata):
        assert hata.message == str(hata)

    def test_authorization_except_not_found_yakalanir(self):
        """AT-192-additif: eski-tüketici-kodu-hâlâ-çalışır."""
        with pytest.raises(EscrowNotFoundError):
            raise EscrowAuthorizationError("rol-reddi")
