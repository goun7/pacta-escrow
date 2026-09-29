"""Pacta on-chain emanet yaşam-döngüsü — CANLI anvil entegrasyon testleri.

DÜRÜST-SINIR: bu-testler-gerçek-bir-EVM-zincirinde ( anvil — mainnet DEĞİL,
PRIVATE_KEY YOK, gerçek-para YOK) ``PactaEscrowVault``-yaşam-döngüsünü-çalıştırır.

TEŞHİS-GEÇMİŞİ ( önceki-ekibin-bulduğu-job_id-çakışması + web3-8.x-kırılmaları):
  * ``run_happy_path`` job_id'yi ``len(res.steps)``-ile-hesaplıyordu; her-runda
    0-olduğu-için-aynı-``pacta-happy-31337-0``-slot'una-yazıyordu → ikinci-run
    ``InvalidStatus``-revert'i + eski-slot-okunması.
  * web3-8.x struct'ı-pozisyonel-liste-döner; eski-kod ``raw[6]``-(outputHash)
    okuyup-ValueError'da-``idx=6``-atadığı-için-her-sonuç-"Refunded"-dönüyordu.
  * ``contract.events.process_log`` web3-8.x'te-yok → ``events=[]``.

ÇÖZÜM: uuid4-ile-UNIQUE-job_id + ABI'dan-çıkarılan-status-indeksi + doğru-event-
decode-API'si + her-testte-``anvil_reset``-ile-zincir-izolasyonu.
"""
from __future__ import annotations

import pytest

from pacta.chain.adapter import ChainUnavailableError, ChainProbeError, connect_anvil
from pacta.chain.onchain import OnchainContractError, OnchainEscrowRunner

# AT-195-sınırları: MAINNET-YASAK — yalnızca-anvil-benzeri-yerel-zincir.
_ANVIL_URL = "http://127.0.0.1:8545"


def _anvil_reachable() -> bool:
    """Anvil-ayakta-mı? Yoksa-testler-atlanır ( 57-testin-CI'da-bozulmaması-için)."""
    try:
        connect_anvil(_ANVIL_URL, timeout=2.0)
        return True
    except (ChainUnavailableError, ChainProbeError, Exception):
        return False


_ANVIL_LIVE = _anvil_reachable()
pytestmark = pytest.mark.skipif(
    not _ANVIL_LIVE,
    reason=f"anvil {_ANVIL_URL} ayakta değil — 'anvil --port 8545' ile başlatın "
           f"( mainnet/YASAK; bu-testler-yalnızca-anvil'de-çalışır)")


@pytest.fixture
def runner() -> OnchainEscrowRunner:
    """Her-testte-TAZE-anvil: ``anvil_reset``-ile-önceki-job-slotları-biter.

    Bu-fixture-olmadan-bir önceki-test'in-bıraktığı-state-okunabilir ( job_id-
    çakışması-teşhisinin-temeli-buydu).
    """
    adapter = connect_anvil(_ANVIL_URL, timeout=10.0)
    r = OnchainEscrowRunner(adapter)
    r.reset_chain()  # genesis'e-dön + deploy-cache'i-boşalt
    return r


# ---------------------------------------------------------------- 1) happy-path

def test_happy_path_settles_not_refunded(runner: OnchainEscrowRunner):
    """lock → submit → settle: on-chain-status ``Settled``-olmalı ( Refunded DEĞİL).

    Bu-test-teşhisin-1.numaralı-semptomunu-kapatır: eskiden-her-adımda
    "Refunded"-(status-6)-görünüyordu ( web3-8.x-struct-okuma-hatası).
    """
    accts = runner.w3.eth.accounts
    res = runner.run_happy_path(accts[1], accts[2])

    assert res.chain_id in (1337, 31337, 31338, 1234, 8545)
    # yaşam-döngüsü-ilerler: Locked → OutputSubmitted → Settled
    statuses = [s.onchain_status for s in res.steps]
    assert statuses == ["Locked", "OutputSubmitted", "Settled"], statuses
    # settled-job ASLA Refunded-dönmemeli
    assert res.step("settle").onchain_status == "Settled"
    assert "Refunded" not in statuses
    # tüm-adımlar-başarılı ( EVM-status=1)
    assert all(s.status == 1 for s in res.steps), [s.status for s in res.steps]
    # on-chain-solvency: tüm-fonlar-dağıtıldı ( kalıcı-bakiye YOK)
    assert "vaultUSDC=0" in res.step("settle").detail


# ------------------------------------------------------------------ 2) events

def test_events_decoded_not_empty(runner: OnchainEscrowRunner):
    """Event-decode-çalışıyor: ``events=[]``-DEĞİL, doğru-event-isimleri-gelmeli.

    Teşhisin-2.numaralı-semptomu: web3-8.x'te ``contract.events.process_log``
    yok-olduğu-için-hiç-event-decode-edilemiyordu.
    """
    accts = runner.w3.eth.accounts
    res = runner.run_happy_path(accts[1], accts[2])

    assert res.step("deposit_and_lock").events == ["EscrowLocked"]
    assert res.step("submit_output").events == ["OutputSubmitted"]
    assert res.step("settle").events == ["EscrowSettled"]
    # tx-hash'ler-gerçekten-receipt-fetch-edilebilir-hex-olmalı ( str(bytes)-değil)
    for step in res.steps:
        assert step.tx_hash.startswith("0x"), step.tx_hash
        assert not step.tx_hash.startswith("0xb'"), step.tx_hash
        # zincirden-bağımsız-teyit: hash-gerçekten-fetch-edilebiliyor
        rcp = runner.w3.eth.get_transaction_receipt(step.tx_hash)
        assert int(rcp.get("status", 0)) == 1


# --------------------------------------------------- 3) unique-job_id-kanıtı

def test_job_ids_are_unique_across_runs(runner: OnchainEscrowRunner):
    """Unique-job_id-kanıtı: AYNI-runner'la-üst-üste-iki-happy-path-çakışmaz.

    Eski-kodda-ikinci-run ``InvalidStatus``-(0xf525e320)-revert'i-veriyordu.
    Ayrıca ``_new_job_id``-uuid4'ünün-gerçekten-unique-olduğunu-da-kanıtlar.
    """
    runner.run_happy_path(runner.w3.eth.accounts[1], runner.w3.eth.accounts[2])
    # ikinci-run AYNI-runner — eskiden-patlardı
    res2 = runner.run_happy_path(runner.w3.eth.accounts[3], runner.w3.eth.accounts[4])

    assert res2.step("settle").onchain_status == "Settled"
    assert res2.step("settle").events == ["EscrowSettled"]

    # uuid4-unique-lik-kanıtı ( 200-çağrı-hepsi-farklı)
    ids = {OnchainEscrowRunner._new_job_id("pacta-happy-31337") for _ in range(200)}
    assert len(ids) == 200, "job_id'ler-unique-değil — uuid4-çalışmıyor"
    assert all(i.startswith("pacta-happy-31337-") for i in ids)


# ----------------------------------------------------- 4) dispute-path-status

def test_dispute_path_resolves_onchain(runner: OnchainEscrowRunner):
    """lock → submit → dispute → resolve: hakemlik-sonucu-on-chain-icra-edilir.

    buyer_favored=true → SLASH&refund → ``Refunded`` ( burada-DOĞRU'dur;
    happy-path'in-aksine-bu-slot-gerçekten-iade-edilmiştir).
    """
    accts = runner.w3.eth.accounts
    res = runner.run_dispute_path(accts[1], accts[2], buyer_favored=True)

    statuses = [s.onchain_status for s in res.steps]
    assert statuses == ["Locked", "OutputSubmitted", "Disputed", "Refunded"], statuses
    assert res.step("raise_dispute").events == ["DisputeRaised"]
    assert res.step("resolve_dispute").events == ["EscrowRefunded", "DisputeResolved"]


# ------------------------------------------------------ 5) timeout-refund-path

def test_timeout_refund_path(runner: OnchainEscrowRunner):
    """lock → SLA-aşımı → claimTimeoutRefund: alıcıya-tam-iade, ``Refunded``."""
    accts = runner.w3.eth.accounts
    res = runner.run_timeout_refund_path(accts[1], accts[2])

    statuses = [s.onchain_status for s in res.steps]
    assert statuses == ["Locked", "Refunded"], statuses
    assert res.step("claim_timeout_refund").events == ["EscrowRefunded"]
    assert res.step("claim_timeout_refund").onchain_status == "Refunded"
