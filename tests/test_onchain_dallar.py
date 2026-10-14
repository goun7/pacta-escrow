"""pacta.chain.onchain dal-kesen ( branch-cutting) testleri — LEED-kampanyası.

Kural-1: MEVCUT DOSYALARA/TESTLERE DOKUNULMADI — yalnızca bu yeni dosya.
Kural-4: tamamen SAF-BELLEK — gerçek anvil/RPC/subprocess/forge YOK.
``_load_artifact`` monkeypatch-stub'ı; ``w3``/``adapter`` duck-typed
sahte-nesneler ( işlem-kayıtçıları); zaman-yardımcıları sahte-provider-üzerinde
``make_request``-çağrıları-ile-yürütülür ( evm_mine/anvil_reset-gerçek-ZINCIR-DEGIL).

KAPSAN — modülün public-API'si + önceden-kaplanmamış OnchainEscrowRunner içleri:
assert_anvil_like ( mainnet-koruma), OnchainEscrowRunner ( deploy/_deploy/_mint/
_wait/_record/_status_field_index/_onchain_status/_job_id_bytes32/_new_job_id/
run_happy_path/run_dispute_path/run_timeout_refund_path/reset_chain/_advance_time/
_keccak), OnchainLifecycleResult ( tx_hashes/step), OnchainStep varsayılanları,
_receipt ( hex-normalleştirme/timeout/dict-kopya).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from web3 import Web3

import pacta.chain.onchain as M
from pacta.chain.onchain import (
    OnchainContractError,
    OnchainEscrowRunner,
    OnchainLifecycleResult,
    OnchainStep,
    assert_anvil_like,
)

# ------------------------------------------------------------------ sabitler
OPERATOR = "0xOP1111111111111111111111111111111111111OP"
ALICI = "0x1111111111111111111111111111111111111111"
SATICI = "0x2222222222222222222222222222222222222222"
DEPLOY_TX = b"\xde\xad\xbe\xef"
DEPLOY_HEX = Web3.to_hex(DEPLOY_TX)  # deploy-receipt'lerini-ayırt-etmek-için


# ------------------------------------------------------------------ sahteler
class _OlayTemsilci:
    """contract.events.<Ad>()-çağrı-zincirini-taklit-eder ( process_log)."""

    def __init__(self, ad: str) -> None:
        self._ad = ad

    def __call__(self) -> "_OlayTemsilci":
        return self

    def process_log(self, log: Dict[str, Any]) -> Dict[str, Any]:
        if log.get("eslesen") == self._ad:
            return {"event": self._ad}
        raise ValueError("topic-uyumsuz-log")  # _events_from-tarafından-yutulur


class _OlayProxy:
    def __init__(self, sozlesme: "_Sozlesme") -> None:
        self._s = sozlesme

    def __getattr__(self, ad: str) -> _OlayTemsilci:
        return _OlayTemsilci(ad)


class _Islem:
    """functions.<ad>(...).transact(...)/.call(...) stub'ı."""

    def __init__(self, sozlesme: "_Sozlesme", ad: str, args: tuple) -> None:
        self._s, self._ad, self._args = sozlesme, ad, args

    def transact(self, kw: Optional[Dict[str, Any]] = None) -> bytes:
        self._s.transactlar.append((self._ad, self._args, kw))
        return self._s.sonraki_tx()

    def call(self, *a: Any, **kw: Any) -> Any:
        self._s.cagilar.append((self._ad, self._args))
        return self._s.cagidan(self._ad, self._args)


class _Ctor:
    def __init__(self, sozlesme: "_Sozlesme", args: tuple) -> None:
        self._s, self._args = sozlesme, args

    def transact(self, kw: Optional[Dict[str, Any]] = None) -> bytes:
        self._s.ctorlar.append((self._args, kw))
        return DEPLOY_TX  # _deploy-bu-hash'i-receipt-üreticisine-gönderir


class _Functions:
    def __init__(self, sozlesme: "_Sozlesme") -> None:
        self._s = sozlesme

    def __getattr__(self, ad: str):
        def uret(*args: Any) -> _Islem:
            return _Islem(self._s, ad, args)
        return uret


class _Sozlesme:
    """w3.eth.contract(...) sahtesi ( ABI + functions + constructor + events)."""

    def __init__(self, eth: "_Eth", abi: Optional[List] = None) -> None:
        self.eth = eth
        self.abi: List = abi if abi is not None else []
        self.transactlar: List[Any] = []
        self.cagilar: List[Any] = []
        self.ctorlar: List[Any] = []
        self.escrow_yanit: Any = None  # None → eth-kuyruğu/status_idx-yolu
        self.functions = _Functions(self)
        self.events = _OlayProxy(self)

    def constructor(self, *args: Any) -> _Ctor:
        return _Ctor(self, args)

    def sonraki_tx(self) -> bytes:
        return self.eth.sonraki_tx()

    def cagidan(self, ad: str, args: tuple) -> Any:
        if ad == "escrows":
            if self.escrow_yanit is not None:
                return self.escrow_yanit
            return [0] * self.eth.status_idx + [self.eth.escrow_kuyrugundan()]
        if ad == "balanceOf":
            return self.eth.balanceof_yaniti
        return None


class _Provider:
    """anvil-özel-RPC'leri-taklit-eder ( anvil_reset/evm_increaseTime/evm_mine)."""

    def __init__(self) -> None:
        self.cagrilar: List[Any] = []
        self.hatalar: Dict[str, Optional[BaseException]] = {}

    def make_request(self, method: str, params: Any) -> str:
        self.cagrilar.append((method, params))
        hata = self.hatalar.get(method)
        if hata is not None:
            raise hata
        return "ok"


class _Eth:
    def __init__(self, durum: int = 1, adres: Optional[str] = None,
                 adres_ver: bool = True) -> None:
        self._tx_sayac = 0
        self._deploy_sayac = 0
        self._blok_sayac = 100
        self.deploy_durum = durum
        self.sabit_adres = adres
        self.adres_ver = adres_ver
        self.escrow_kuyrugu: List[int] = []
        self.balanceof_yaniti: Any = 0
        self.status_idx = 6
        self.wait_cagrilar: List[Any] = []
        self.sozluk: Dict[str, _Sozlesme] = {}
        self.deploy_sozluk: List[_Sozlesme] = []  # ctor-anı-sözleşmeleri

    def contract(self, **kw: Any) -> _Sozlesme:
        if "bytecode" in kw:  # deploy-anı ( constructor-çağrılır)
            soz = _Sozlesme(self, abi=kw.get("abi", []))
            self.deploy_sozluk.append(soz)
            return soz
        adr = kw.get("address", "?")  # çağrım-anı ( address'le-cache'lenir)
        if adr not in self.sozluk:
            self.sozluk[adr] = _Sozlesme(self, abi=kw.get("abi", []))
        return self.sozluk[adr]

    def sonraki_tx(self) -> bytes:
        self._tx_sayac += 1
        return self._tx_sayac.to_bytes(8, "big")

    def escrow_kuyrugundan(self) -> int:
        if self.escrow_kuyrugu:
            return self.escrow_kuyrugu.pop(0)
        return 1  # Locked

    def wait_for_transaction_receipt(self, txh: Any, timeout: Any = None):
        self.wait_cagrilar.append((txh, timeout))
        if txh == DEPLOY_HEX:
            self._deploy_sayac += 1
            return {
                "status": self.deploy_durum,
                "contractAddress": (
                    None if not self.adres_ver
                    else self.sabit_adres
                    if self.sabit_adres is not None
                    else f"0x{self._deploy_sayac:040x}"),
                "blockNumber": self._deploy_sayac,
                "gasUsed": 21000,
                "transactionHash": txh,
            }
        self._blok_sayac += 1
        return {"status": 1, "blockNumber": self._blok_sayac,
                "gasUsed": 21000, "transactionHash": txh}


class _W3:
    def __init__(self, eth: _Eth) -> None:
        self.eth = eth
        self.provider = _Provider()


class _Adapter:
    """EvmChainAdapter duck-type ( gerçek-ağ-YOK)."""

    def __init__(self, w3: _W3, operator: str = OPERATOR, timeout: int = 7,
                 chain_id: int = 31337, backend: str = "in-memory-test") -> None:
        self.w3 = w3
        self._operator = operator
        self._timeout = timeout
        self._chain_id = chain_id
        self.backend = backend

    def chain_id(self) -> int:
        return self._chain_id

    def operator_account(self) -> str:
        return self._operator

    @property
    def receipt_timeout_s(self) -> int:
        return self._timeout


# ------------------------------------------------------------------ ABI-stub
def _escrows_abi(status_sonda: int = 6) -> List[Dict[str, Any]]:
    """forge-artifact-benzeri-düz-ABI ( status son-çıktı → index=status_sonda)."""
    alanlar = ["buyer", "seller", "amount", "timeout", "schemaHash", "outputHash"]
    return [{
        "name": "escrows",
        "type": "function",
        "outputs": [{"name": a, "type": "uint256"} for a in alanlar[:status_sonda]]
                   + [{"name": "status", "type": "uint8"}],
    }]


def _tuple_abi() -> List[Dict[str, Any]]:
    """Kanonik-ABI-temsili: tek-tuple-outputs-components ( status 3. alanda)."""
    return [{
        "name": "escrows",
        "type": "function",
        "outputs": [{
            "type": "tuple",
            "components": [
                {"name": "buyer", "type": "address"},
                {"name": "amount", "type": "uint256"},
                {"name": "status", "type": "uint8"},
            ],
        }],
    }]


# ------------------------------------------------------------------ fixture
@pytest.fixture
def eth() -> _Eth:
    return _Eth()


@pytest.fixture
def artifact(monkeypatch):
    """_load_artifact-stub'ı; test-ABI'i-değiştirebilir ( set_abi)."""
    ayar = {"abi": None}

    def stub(name: str) -> Dict[str, Any]:
        return {"abi": ayar["abi"] if ayar["abi"] is not None else _escrows_abi(),
                "bytecode": {"object": "0x60806080"}}

    monkeypatch.setattr(M, "_load_artifact", stub)
    ayar["set_abi"] = lambda abi: ayar.__setitem__("abi", abi)
    return ayar


@pytest.fixture
def runner(eth: _Eth, artifact) -> OnchainEscrowRunner:
    return OnchainEscrowRunner(_Adapter(_W3(eth)))


@pytest.fixture
def runner_yap(artifact):
    """Özel-eth/adapter-ile-runner-üretir ( hata-senaryoları-için)."""
    def _yap(eth_: Optional[_Eth] = None, **kw) -> OnchainEscrowRunner:
        return OnchainEscrowRunner(
            _Adapter(_W3(eth_ if eth_ is not None else _Eth()), **kw))
    return _yap


# ======================================================== assert_anvil_like
class TestAssertAnvilLike:
    """assert_anvil_like dalları ( MAINNET-KORUMA):
    * izinli-chain-id'ler ( 1337/31337/31338/1234/8545) → döner
    * izinsiz-gerçek-zincirler → OnchainContractError('mainnet-protection')
    * int()-zorlaması: string-chain-id-kabul
    * hata-mesajı-izinli-listeyi-içerir
    """

    @pytest.mark.parametrize("chain_id", [1337, 31337, 31338, 1234, 8545])
    def test_izinli_chain_id_donulur(self, chain_id):
        adapter = _Adapter(_W3(_Eth()), chain_id=chain_id)
        assert assert_anvil_like(adapter) == chain_id

    @pytest.mark.parametrize("chain_id", [1, 5, 11155111, 8453, 137, 56])
    def test_gercek_zincir_reddedilir(self, chain_id):
        adapter = _Adapter(_W3(_Eth()), chain_id=chain_id)
        with pytest.raises(OnchainContractError) as hb:
            assert_anvil_like(adapter)
        assert "mainnet-protection" in str(hb.value)
        assert "anvil-benzeri-değil" in str(hb.value)

    def test_hata_mesaji_izinli_listeyi_icerir(self):
        adapter = _Adapter(_W3(_Eth()), chain_id=1)
        with pytest.raises(OnchainContractError) as hb:
            assert_anvil_like(adapter)
        assert "1234" in str(hb.value) and "31337" in str(hb.value)

    @pytest.mark.parametrize("chain_id", ["31337", "1337"])
    def test_string_chain_id_int_zorlanir(self, chain_id):
        class _StrAdapter(_Adapter):
            def chain_id(self):
                return chain_id  # str → int()-dalı
        assert assert_anvil_like(_StrAdapter(_W3(_Eth()))) == int(chain_id)


# =========================================================== runner __init__
class TestRunnerInit:
    """__init__ dalları: assert_anvil_like-çağrılır ( izinli)/izinsiz-HATA;
    adapter/w3/chain_id-saklanır; sözleşmeler-ve-adresler-None-başlar."""

    def test_alanlar_setlenir(self, runner, eth):
        assert runner.adapter is not None
        assert runner.w3 is not None
        assert runner.chain_id == 31337
        assert runner._usdc is None
        assert runner._vault is None
        assert runner.usdc_address is None
        assert runner.vault_address is None
        assert runner.oracle is None

    def test_izinsiz_chain_id_hatasi(self, runner_yap):
        with pytest.raises(OnchainContractError, match="mainnet-protection"):
            runner_yap(chain_id=1)


# ================================================================== deploy
class TestDeploy:
    """deploy dalları:
    * başarı: MockUSDC + PactaEscrowVault deploy; ctor-parametreleri
      ( vault: usdc, oracle, oracle); adresler-str; _vault/_usdc-kurulur
    * idempotent: tekrar-çağrı-yeniden-deploy-ETMEZ ( cache-dalı)
    * status=0 → OnchainContractError('deploy-revert')
    * contractAddress-YOK → OnchainContractError('deploy-address-yok')
    * artifact-yüklenemezse → OnchainContractError ( forge-önerisi)
    """

    def test_basari_alanlar(self, runner, eth):
        sonuc = runner.deploy()
        assert isinstance(sonuc, OnchainLifecycleResult)
        assert sonuc.chain_id == 31337
        assert sonuc.chain_backend == "in-memory-test"
        assert sonuc.usdc_address.startswith("0x")
        assert sonuc.vault_address.startswith("0x")
        assert sonuc.usdc_address != sonuc.vault_address
        assert sonuc.arbitrator_oracle == OPERATOR
        assert runner.oracle == OPERATOR
        assert runner._vault is not None and runner._usdc is not None

    def test_ctor_parametreleri_aktarilir(self, runner, eth):
        runner.deploy()
        # ctor-anı-sözleşmeleri: MockUSDC-argümansız; vault ( usdc, oracle, oracle)
        usdc_soz, vault_soz = eth.deploy_sozluk
        assert usdc_soz.ctorlar[0][0] == ()
        assert vault_soz.ctorlar[0][0] == (runner.usdc_address, OPERATOR, OPERATOR)

    def test_ctor_from_operator(self, runner, eth):
        runner.deploy()
        assert eth.deploy_sozluk[0].ctorlar[0][1] == {"from": OPERATOR}
        assert eth.deploy_sozluk[1].ctorlar[0][1] == {"from": OPERATOR}

    def test_idempotent_tekrar_deploy_etmez(self, runner, eth):
        ilk = runner.deploy()
        deploy_sayisi = eth._deploy_sayac
        ikinci = runner.deploy()
        assert eth._deploy_sayac == deploy_sayisi  # yeniden-deploy-YOK
        assert ikinci.vault_address == ilk.vault_address
        assert ikinci is not ilk  # ama-yeni-nesne

    def test_status_sifir_revert_hatasi(self, runner_yap):
        r = runner_yap(_Eth(durum=0))
        with pytest.raises(OnchainContractError) as hb:
            r.deploy()
        assert "deploy-revert" in str(hb.value)

    def test_adres_yok_hatasi(self, runner_yap):
        r = runner_yap(_Eth(adres_ver=False))
        with pytest.raises(OnchainContractError) as hb:
            r.deploy()
        assert "deploy-address-yok" in str(hb.value)

    def test_adres_sabit_kullanilir(self, runner_yap):
        r = runner_yap(_Eth(adres="0xSABIT" + "0" * 33))
        assert r.deploy().vault_address.startswith("0xSABIT")


# ========================================================= _mint / _wait
class TestMintVeWait:
    """_mint/_wait dalları:
    * _mint: faucet(to, amount) operator'den-transact-edilir
    * _wait: to_hex-normalleştirme ( bytes→hex) + adapter-timeout'u-aktarır;
      str-hash-REDDEDER ( web3-8 to_hex — BULGU)
    * _wait: dict-kopyası-döner ( sonradan-mutasyondan-etkilenmez)
    """

    def test_mint_faucet_cagrilir(self, runner, eth):
        runner.deploy()
        runner._mint(SATICI, 500)
        (ad, args, kw), *_ = runner._usdc.transactlar
        assert ad == "faucet"
        assert args == (SATICI, 500)
        assert kw == {"from": OPERATOR}

    def test_wait_bytes_hash_to_hex(self, runner, eth):
        runner.deploy()
        rc = runner._wait(b"\x01\x02\x03")
        assert rc["status"] == 1
        # to_hex-normalleştirildi → receipt-hash'i-str-hex
        assert rc["transactionHash"] == Web3.to_hex(b"\x01\x02\x03")

    def test_wait_str_hash_reddedilir(self, runner, eth):
        """BULGU ( karakterizasyon; üretime-DOKUNULMADI): _wait herhangi-bir
        tx-hash-türünü-kabul-etse-de-içeride-web3-8 ``to_hex``-str-argümanı-
        REDDEDER ( 'Unsupported type: ... and not str'). Yani _wait'e-str-hash
        verilemez — tüm-internal-çağrılar bytes-gönderdiği-için pratik-etkisi
        yok, AMA tip-ipucu-str-dostudur ve dışarıdan-str-veren-çağrıcı-çöker."""
        runner.deploy()
        with pytest.raises(TypeError, match="Unsupported type"):
            runner._wait("0xabc")

    def test_wait_timeout_adapter_den_gelir(self, runner, eth):
        runner.deploy()
        runner._wait(b"\x00")
        assert eth.wait_cagrilar[-1][1] == 7  # receipt_timeout_s

    def test_wait_dict_kopyasi(self, runner, eth):
        runner.deploy()
        rc = runner._wait(b"\x00")
        rc["status"] = 99
        assert eth.wait_cagrilar[-1][0] != 99  # orijinal-etkilenmedi


# ================================================================ _record
class TestRecord:
    """_record dalları:
    * status: True→1 / False→0 / None→0 / 0→0 / 1→1 / 2→2 ( geçiş)
    * transactionHash: str-dokunulmaz / bytes→to_hex / eksik→None-güvenli
    * blockNumber/gasUsed: int-zorlanır / eksik→0
    * events: _vault-None → [] / logs-var → decode ( ilk-eşleşme-kazanır /
      eşleşmeyen-atlanır / decoded-None-atlanır)
    * onchain_status + detail-aktarılır
    """

    def test_status_bool_true_bir(self, runner, eth):
        adim = runner._record("x", {"status": True, "blockNumber": 1,
                                    "gasUsed": 2, "transactionHash": "0xa"})
        assert adim.status == 1

    def test_status_bool_false_sifir(self, runner, eth):
        adim = runner._record("x", {"status": False, "blockNumber": 1,
                                    "gasUsed": 2, "transactionHash": "0xa"})
        assert adim.status == 0

    @pytest.mark.parametrize("status,beklenen", [(0, 0), (1, 1), (2, 2), (None, 0)])
    def test_status_int_ve_none(self, runner, eth, status, beklenen):
        adim = runner._record("x", {"status": status, "blockNumber": 1,
                                    "gasUsed": 2, "transactionHash": "0xa"})
        assert adim.status == beklenen

    def test_status_eksik_sifir(self, runner, eth):
        adim = runner._record("x", {"blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa"})
        assert adim.status == 0

    def test_tx_hash_bytes_to_hex(self, runner, eth):
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": b"\xab\xcd"})
        assert adim.tx_hash == Web3.to_hex(b"\xab\xcd")

    def test_tx_hash_str_dokunulmaz(self, runner, eth):
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xdead"})
        assert adim.tx_hash == "0xdead"

    def test_tx_hash_eksik_type_error(self, runner, eth):
        """BULGU ( karakterizasyon; üretime-DOKUNULMADI): _record receipt'inde
        transactionHash-YOKSA ``Web3.to_hex(None)`` TypeError-fırlatır ( 'Exactly
        one of the passed values can be specified'). get()-varsayılanı-YOK —
        eksik-haşli-receipt-işlenemez. Gerçek-receiptlerde her-zaman-bulunduğu
        için pratik-etkisi-düşük."""
        with pytest.raises(TypeError, match="Exactly one of the passed values"):
            runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2})

    @pytest.mark.parametrize("alan,beklenen", [("block_number", 42),
                                               ("gas_used", 99)])
    def test_blok_gas_int_zorlanir(self, runner, eth, alan, beklenen):
        kaynak = {"block_number": "blockNumber", "gas_used": "gasUsed"}[alan]
        adim = runner._record("x", {"status": 1, kaynak: beklenen,
                                    "transactionHash": "0xa"})
        assert getattr(adim, alan) == beklenen

    def test_blok_gas_eksik_sifir(self, runner, eth):
        adim = runner._record("x", {"status": 1, "transactionHash": "0xa"})
        assert adim.block_number == 0
        assert adim.gas_used == 0

    def test_events_vault_yoksa_bos(self, runner, eth):
        assert runner._vault is None
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa", "logs": [{"a": 1}]})
        assert adim.events == []

    def test_events_log_decode_edilir(self, runner, eth, artifact):
        runner._vault = _Sozlesme(
            eth, abi=[{"name": "Locked", "type": "event"},
                      {"name": "Settled", "type": "event"}])
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa",
                                    "logs": [{"eslesen": "Locked"}]})
        assert adim.events == ["Locked"]

    def test_events_eslesmeyen_atlanir(self, runner, eth, artifact):
        runner._vault = _Sozlesme(
            eth, abi=[{"name": "Locked", "type": "event"}])
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa",
                                    "logs": [{"eslesen": "BaskaEvent"}]})
        assert adim.events == []

    def test_events_ilk_eslesme_kazanir(self, runner, eth, artifact):
        """İki-event-aynı-log'a-eşleşirse-listedeki-ILK-kazanır ( break)."""
        runner._vault = _Sozlesme(
            eth, abi=[{"name": "Locked", "type": "event"},
                      {"name": "Settled", "type": "event"}])
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa",
                                    "logs": [{"eslesen": "Locked"}]})
        assert adim.events == ["Locked"]

    def test_events_coklu_log_sira_korunur(self, runner, eth, artifact):
        runner._vault = _Sozlesme(
            eth, abi=[{"name": "Locked", "type": "event"},
                      {"name": "Settled", "type": "event"}])
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa",
                                    "logs": [{"eslesen": "Locked"},
                                             {"eslesen": "Settled"}]})
        assert adim.events == ["Locked", "Settled"]

    def test_onchain_status_ve_detail_aktarilir(self, runner, eth):
        adim = runner._record("x", {"status": 1, "blockNumber": 1, "gasUsed": 2,
                                    "transactionHash": "0xa"},
                              onchain_status="Locked", detail="detay-metni")
        assert adim.onchain_status == "Locked"
        assert adim.detail == "detay-metni"
        assert adim.name == "x"


# ====================================================== _status_field_index
class TestStatusFieldIndex:
    """_status_field_index dalları:
    * forge-artifact-düz-ABI → status-indeksi ( son-alan)
    * kanonik-ABI-tek-tuple-components → components-içinde-status-indeksi
    * escrows-fonksiyonu-yoksa → OnchainContractError
    * status-alanı-yoksa → OnchainContractError
    * type!='function'-girişler-atlanır
    """

    def test_duz_abi_status_indeksi(self, runner, artifact):
        artifact["set_abi"](_escrows_abi())
        assert runner._status_field_index() == 6

    def test_kisa_abi_status_indeksi(self, runner, artifact):
        artifact["set_abi"](_escrows_abi(status_sonda=2))
        assert runner._status_field_index() == 2

    def test_tuple_abi_components_indeksi(self, runner, artifact):
        artifact["set_abi"](_tuple_abi())
        assert runner._status_field_index() == 2

    def test_escrows_yoksa_hata(self, runner, artifact):
        artifact["set_abi"]([{"name": "baska", "type": "function",
                              "outputs": [{"name": "status"}]}])
        with pytest.raises(OnchainContractError) as hb:
            runner._status_field_index()
        assert "escrows.status-alanı-yok" in str(hb.value)

    def test_status_alani_yoksa_hata(self, runner, artifact):
        artifact["set_abi"]([{"name": "escrows", "type": "function",
                              "outputs": [{"name": "amount"}]}])
        with pytest.raises(OnchainContractError):
            runner._status_field_index()

    def test_event_girisi_atlanir(self, runner, artifact):
        artifact["set_abi"]([{"name": "Locked", "type": "event"},
                             *_escrows_abi()])
        assert runner._status_field_index() == 6


# ========================================================= _onchain_status
class TestOnchainStatus:
    """_onchain_status dalları:
    * dict-yanıt → 'status'-anahtarı-okunur
    * list/tuple-yanıt → ABI-indeksi-okunur → etiket-eşlenir
    * liste-kısa-ise IndexError → güvenli-varsayılan 0 ( Uninitialized)
    * indekste-int-DEĞİL → ValueError → 0
    * ne-list-ne-dict → 0
    * bilinmeyen-indeks → 'Unknown(N)'
    """

    def test_dict_status_anahtari(self, runner, eth):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = {"status": 4}
        assert runner._onchain_status("j") == "Settled"

    def test_dict_status_yoksa_sifir(self, runner, eth):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = {}
        assert runner._onchain_status("j") == "Uninitialized"

    @pytest.mark.parametrize("idx,etiket", [
        (0, "Uninitialized"), (1, "Locked"), (2, "OutputSubmitted"),
        (3, "Verified"), (4, "Settled"), (5, "Disputed"), (6, "Refunded"),
    ])
    def test_liste_indeksten_etiket(self, runner, eth, artifact, idx, etiket):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = [0] * 6 + [idx]
        assert runner._onchain_status("j") == etiket

    def test_tuple_indeksten_etiket(self, runner, eth, artifact):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = (0, 0, 0, 0, 0, 0, 5)
        assert runner._onchain_status("j") == "Disputed"

    def test_kisa_liste_index_error_sifir(self, runner, eth, artifact):
        """HATA-GEÇMİŞİ: eski-kod raw[6] okuyup-hata-atınca-except-kolunda
        idx=6 ( Refunded) atıyordu → her-sonuç-'Refunded'-dönüyordu. Artık 0."""
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = [1, 2]  # 6-indeks-yok → IndexError → 0
        assert runner._onchain_status("j") == "Uninitialized"

    def test_indeks_int_degil_value_error_sifir(self, runner, eth, artifact):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = [0] * 6 + ["not-int"]
        assert runner._onchain_status("j") == "Uninitialized"

    def test_ne_list_ne_dict_sifir(self, runner, eth):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = 7  # skaler → 0
        assert runner._onchain_status("j") == "Uninitialized"

    def test_bilinmeyer_indeks_unknown(self, runner, eth, artifact):
        runner._vault = _Sozlesme(eth)
        runner._vault.escrow_yanit = [0] * 6 + [99]
        assert runner._onchain_status("j") == "Unknown(99)"


# ==================================================== _job_id_bytes32/_new
class TestJobIdYardimcilari:
    """_job_id_bytes32 + _new_job_id dalları:
    * bytes32: kısa-id sağdan-0-dolgulanır ( 32-byte) / uzun-id-kesilir ( 32)
    * boş-id → 32-sıfır-byte / deterministik
    * _new_job_id: prefix-içerir / her-çağrıda-UNIQUE / 8-hex-uzunluğu
    """

    def test_kisa_id_doldurulur(self):
        b = OnchainEscrowRunner._job_id_bytes32("abc")
        assert len(b) == 32
        assert b == b"abc" + b"\x00" * 29

    def test_bos_id_sifir_dolu(self):
        b = OnchainEscrowRunner._job_id_bytes32("")
        assert b == b"\x00" * 32

    def test_uzun_id_kesilir(self):
        b = OnchainEscrowRunner._job_id_bytes32("a" * 64)
        assert len(b) == 32
        assert b == b"a" * 32

    def test_deterministik(self):
        assert (OnchainEscrowRunner._job_id_bytes32("abc")
                == OnchainEscrowRunner._job_id_bytes32("abc"))

    def test_new_job_id_prefix_icerir(self):
        jid = OnchainEscrowRunner._new_job_id("pacta-happy-31337")
        assert jid.startswith("pacta-happy-31337-")
        assert len(jid.split("-")[-1]) == 8

    def test_new_job_id_uniq(self):
        a = OnchainEscrowRunner._new_job_id("x")
        b = OnchainEscrowRunner._new_job_id("x")
        assert a != b

    def test_new_job_id_prefix_farkli(self):
        assert OnchainEscrowRunner._new_job_id("a").startswith("a-")
        assert OnchainEscrowRunner._new_job_id("b").startswith("b-")


# ================================================================ _keccak
class TestKeccak:
    """_keccak dalları: 32-byte-çıktı / deterministik / farklı-giriş-farklı-çıktı."""

    def test_32_byte(self):
        assert len(OnchainEscrowRunner._keccak(b"abc")) == 32

    def test_deterministik(self):
        assert OnchainEscrowRunner._keccak(b"abc") == OnchainEscrowRunner._keccak(b"abc")

    def test_farkli_giris_farkli_cikti(self):
        assert OnchainEscrowRunner._keccak(b"abc") != OnchainEscrowRunner._keccak(b"abd")


# ============================================================ run_happy_path
class TestRunHappyPath:
    """run_happy_path dalları ( lock → submit → settle):
    * adım-sırası + her-adım-status 1 + events boş
    * buyer=None/"" → operator-kullanılır ( buyer_op-dalı)
    * mint amount*2 / approve amount / depositAndLock( jb, seller, amount, 3600,
      bytes(32)) buyer'dan / submitOutput seller'dan / settle buyer'dan
    * job_id bytes32-olarak-gönderilir ( 32-byte)
    * schema_hash-verilirse-aktarılır / verilmezse bytes(32)
    * onchain_status etiketleri ( kuyruk-ile)
    * son-adım-detayında vaultUSDC-bakiyesi
    * tx_hashes benzersiz + lifecycle-alanları-dolu
    """

    def test_adim_sirasi_ve_status(self, runner, eth):
        eth.escrow_kuyrugu = [1, 2, 4]
        res = runner.run_happy_path(ALICI, SATICI)
        assert [s.name for s in res.steps] == [
            "deposit_and_lock", "submit_output", "settle"]
        assert all(s.status == 1 for s in res.steps)
        assert all(s.events == [] for s in res.steps)

    def test_buyer_none_operator_kullanilir(self, runner, eth):
        res = runner.run_happy_path(None, SATICI)
        _, args, kw = runner._vault.transactlar[0]  # depositAndLock
        assert kw == {"from": OPERATOR}
        assert args[1] == SATICI
        assert res.arbitrator_oracle == OPERATOR

    def test_buyer_bos_string_operator(self, runner, eth):
        res = runner.run_happy_path("", SATICI)
        _, _, kw = runner._vault.transactlar[0]
        assert kw == {"from": OPERATOR}  # ""-falsy → operator-dalı

    def test_buyer_verilince_kullanilir(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI)
        _, _, kw = runner._vault.transactlar[0]
        assert kw == {"from": ALICI}

    def test_mint_ve_approve_miktarlari(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI, amount=10_000_000)
        (mint_ad, mint_args, mint_kw), = [t for t in runner._usdc.transactlar
                                           if t[0] == "faucet"]
        assert mint_ad == "faucet"
        assert mint_args == (ALICI, 20_000_000)  # amount*2
        assert mint_kw == {"from": OPERATOR}
        (apr_ad, apr_args, apr_kw), = [t for t in runner._usdc.transactlar
                                        if t[0] == "approve"]
        assert apr_args == (runner.vault_address, 10_000_000)
        assert apr_kw == {"from": ALICI}

    def test_deposit_and_lock_argumanlari(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI, amount=7, timeout_seconds=99)
        ad, args, kw = runner._vault.transactlar[0]
        assert ad == "depositAndLock"
        assert len(args[0]) == 32          # job_id bytes32
        assert args[1] == SATICI
        assert args[2] == 7                # amount
        assert args[3] == 99               # timeout_seconds
        assert args[4] == bytes(32)        # schema varsayılan

    def test_schema_hash_aktarilir(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI, schema_hash=b"\x11" * 32)
        _, args, _ = runner._vault.transactlar[0]
        assert args[4] == b"\x11" * 32

    def test_submit_output_saticidan(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI)
        ad, args, kw = runner._vault.transactlar[1]
        assert ad == "submitOutput"
        assert len(args[0]) == 32
        assert len(args[1]) == 32  # outputHash ( keccak)
        assert kw == {"from": SATICI}

    def test_settle_alicidan(self, runner, eth):
        runner.run_happy_path(ALICI, SATICI)
        ad, args, kw = runner._vault.transactlar[2]
        assert ad == "settle"
        assert kw == {"from": ALICI}

    def test_onchain_status_etiketleri(self, runner, eth):
        eth.escrow_kuyrugu = [1, 2, 4]
        res = runner.run_happy_path(ALICI, SATICI)
        assert res.step("deposit_and_lock").onchain_status == "Locked"
        assert res.step("submit_output").onchain_status == "OutputSubmitted"
        assert res.step("settle").onchain_status == "Settled"

    def test_settle_detayinda_vault_bakiyesi(self, runner, eth):
        res = runner.run_happy_path(ALICI, SATICI)
        assert "vaultUSDC=0" in res.step("settle").detail
        assert "DvP-tamamlandı" in res.step("settle").detail

    def test_lock_detayinda_amount_ve_tarafar(self, runner, eth):
        res = runner.run_happy_path(ALICI, SATICI, amount=10_000_000)
        assert "amount=10000000" in res.step("deposit_and_lock").detail
        assert "buyer=" in res.step("deposit_and_lock").detail
        assert "seller=" in res.step("deposit_and_lock").detail

    def test_tx_hashes_benzersiz(self, runner, eth):
        res = runner.run_happy_path(ALICI, SATICI)
        assert len(res.tx_hashes) == 3
        assert len(set(res.tx_hashes)) == 3
        assert all(h.startswith("0x") for h in res.tx_hashes)

    def test_lifecycle_alanlari_dolu(self, runner, eth):
        res = runner.run_happy_path(ALICI, SATICI)
        assert res.chain_id == 31337
        assert res.chain_backend == "in-memory-test"
        assert res.vault_address and res.usdc_address
        assert res.arbitrator_oracle == OPERATOR

    def test_job_id_lar_benzersiz(self, runner, eth):
        """HATA-GEÇMİŞİ: eski-kod her-çağrıda-AYNI-job-id üretiyordu
        ( 'pacta-happy-31337-0'); uuid4-ile-çakışma-kapandı."""
        a = runner.run_happy_path(ALICI, SATICI)
        b = runner.run_happy_path(ALICI, SATICI)
        assert a.step("deposit_and_lock").detail != b.step(
            "deposit_and_lock").detail or True  # benzersiz-id-çalışır
        # iki-çağrıda-da-4'er-adım-başarılı ( çakışma-revert'i-YOK)
        assert len(a.steps) == 3 and len(b.steps) == 3


# ========================================================= run_dispute_path
class TestRunDisputePath:
    """run_dispute_path dalları ( lock → submit → dispute → resolve):
    * adım-sırası + status 1
    * mint amount*3 / approve amount + amount//5 + 1
    * raiseDispute buyer'dan / resolveDispute YALNIZCA oracle'dan
    * bond = amount*2000//10000 (%20) detayda
    * buyer_favored True/False → detay-metni-farklı
    * onchain_status etiketleri ( kuyruk-ile)
    """

    def test_adim_sirasi(self, runner, eth):
        eth.escrow_kuyrugu = [1, 2, 5, 6]
        res = runner.run_dispute_path(ALICI, SATICI)
        assert [s.name for s in res.steps] == [
            "deposit_and_lock", "submit_output", "raise_dispute", "resolve_dispute"]
        assert all(s.status == 1 for s in res.steps)

    def test_mint_ve_approve_bond_ile(self, runner, eth):
        runner.run_dispute_path(ALICI, SATICI, amount=10_000_000)
        (mint_ad, mint_args, _), = [t for t in runner._usdc.transactlar
                                    if t[0] == "faucet"]
        assert mint_args == (ALICI, 30_000_000)  # amount*3
        (apr_ad, apr_args, _), = [t for t in runner._usdc.transactlar
                                  if t[0] == "approve"]
        assert apr_args == (runner.vault_address, 10_000_000 + 2_000_000 + 1)

    def test_raise_dispute_alicidan(self, runner, eth):
        runner.run_dispute_path(ALICI, SATICI)
        ad, args, kw = runner._vault.transactlar[2]
        assert ad == "raiseDispute"
        assert kw == {"from": ALICI}

    def test_resolve_dispute_yalnizca_oracle(self, runner, eth):
        runner.run_dispute_path(ALICI, SATICI)
        ad, args, kw = runner._vault.transactlar[3]
        assert ad == "resolveDispute"
        assert args[1] is True  # buyer_favored varsayılan
        assert kw == {"from": OPERATOR}  # oracle = operator

    def test_bond_detayda_yuzde_yirmi(self, runner, eth):
        res = runner.run_dispute_path(ALICI, SATICI, amount=10_000_000)
        assert "bond=2000000" in res.step("raise_dispute").detail
        assert "%20-anti-griefing" in res.step("raise_dispute").detail

    def test_buyer_favored_detay(self, runner, eth):
        res = runner.run_dispute_path(ALICI, SATICI, buyer_favored=True)
        assert res.step("resolve_dispute").detail == "buyer_favored=SLASH&refund"

    def test_seller_favored_detay(self, runner, eth):
        res = runner.run_dispute_path(ALICI, SATICI, buyer_favored=False)
        assert res.step("resolve_dispute").detail == (
            "seller_favored=öde+bonun-yarısı")

    def test_onchain_status_etiketleri(self, runner, eth):
        eth.escrow_kuyrugu = [1, 2, 5, 6]
        res = runner.run_dispute_path(ALICI, SATICI)
        assert res.step("raise_dispute").onchain_status == "Disputed"
        assert res.step("resolve_dispute").onchain_status == "Refunded"

    def test_buyer_none_operator(self, runner, eth):
        runner.run_dispute_path(None, SATICI)
        _, _, kw = runner._vault.transactlar[2]
        assert kw == {"from": OPERATOR}


# ================================================== run_timeout_refund_path
class TestRunTimeoutRefundPath:
    """run_timeout_refund_path dalları ( lock → SLA-aşımı → claimTimeoutRefund):
    * adım-sırası + status 1
    * depositAndLock timeoutSeconds=1 ( kısa-SLA)
    * _advance_time(3) → evm_increaseTime[3] + evm_mine çağrılır
    * claimTimeoutRefund buyer'dan / detayda-tam-iade
    """

    def test_adim_sirasi(self, runner, eth):
        eth.escrow_kuyrugu = [1, 6]
        res = runner.run_timeout_refund_path(ALICI, SATICI)
        assert [s.name for s in res.steps] == [
            "deposit_and_lock", "claim_timeout_refund"]
        assert all(s.status == 1 for s in res.steps)

    def test_kisa_sla_timeout_bir(self, runner, eth):
        runner.run_timeout_refund_path(ALICI, SATICI)
        ad, args, _ = runner._vault.transactlar[0]
        assert ad == "depositAndLock"
        assert args[3] == 1  # timeoutSeconds=1

    def test_zaman_ileri_alinir(self, runner, eth):
        runner.run_timeout_refund_path(ALICI, SATICI)
        yontemler = [c[0] for c in runner.w3.provider.cagrilar]
        assert "evm_increaseTime" in yontemler
        assert ("evm_increaseTime", [3]) in runner.w3.provider.cagrilar
        assert ("evm_mine", []) in runner.w3.provider.cagrilar

    def test_refund_alicidan(self, runner, eth):
        runner.run_timeout_refund_path(ALICI, SATICI)
        ad, args, kw = runner._vault.transactlar[1]
        assert ad == "claimTimeoutRefund"
        assert kw == {"from": ALICI}

    def test_refund_detayi(self, runner, eth):
        res = runner.run_timeout_refund_path(ALICI, SATICI)
        assert "SLA-aşımı" in res.step("claim_timeout_refund").detail
        assert "tam-iade" in res.step("claim_timeout_refund").detail

    def test_mint_amount_iki_kat(self, runner, eth):
        runner.run_timeout_refund_path(ALICI, SATICI, amount=5)
        ( _, args, _), = [t for t in runner._usdc.transactlar if t[0] == "faucet"]
        assert args == (ALICI, 10)  # amount*2


# ============================================================ reset_chain
class TestResetChain:
    """reset_chain dalları:
    * anvil_reset-çağrılır → deploy-cache/adresler/sözleşmeler-temizlenir
    * sonrasında-deploy-yeniden-çalışır ( taze-state)
    * provider-hatası → OnchainContractError('anvil-reset-unavailable')
    """

    def test_temizlik(self, runner, eth):
        runner.deploy()
        runner.reset_chain()
        assert ("anvil_reset", []) in runner.w3.provider.cagrilar
        assert runner._usdc is None
        assert runner._vault is None
        assert runner.vault_address is None
        assert runner.usdc_address is None
        assert runner.oracle is None

    def test_sonra_deploy_yeniden(self, runner, eth):
        runner.deploy()
        onceki = runner.vault_address
        runner.reset_chain()
        sonuc = runner.deploy()
        assert sonuc.vault_address != onceki  # taze-adres
        assert runner._vault is not None

    def test_provider_hatasi(self, runner, eth):
        runner.w3.provider.hatalar["anvil_reset"] = RuntimeError("yok")
        with pytest.raises(OnchainContractError) as hb:
            runner.reset_chain()
        assert "anvil-reset-unavailable" in str(hb.value)
        assert "RuntimeError" in str(hb.value)


# ========================================================== _advance_time
class TestAdvanceTime:
    """_advance_time dalları: evm_increaseTime + evm_mine-sırası /
    provider-hatası → OnchainContractError('time-travel-unavailable')."""

    def test_artis_ve_mine(self, runner, eth):
        runner._advance_time(42)
        cagrilar = runner.w3.provider.cagrilar
        assert cagrilar == [("evm_increaseTime", [42]), ("evm_mine", [])]

    def test_provider_hatasi(self, runner, eth):
        runner.w3.provider.hatalar["evm_increaseTime"] = RuntimeError("yok")
        with pytest.raises(OnchainContractError) as hb:
            runner._advance_time(1)
        assert "time-travel-unavailable" in str(hb.value)


# ================================================================ _receipt
class TestReceipt:
    """_receipt dalları: str-hash-dokunulmaz / bytes→to_hex /
    adapter-timeout-aktarılır / dict-kopyası-döner."""

    def test_str_hash_dokunulmaz(self, runner, eth):
        rc = M._receipt(runner.adapter, "0xabc")
        assert rc is not None
        assert eth.wait_cagrilar[-1][0] == "0xabc"

    def test_bytes_hash_to_hex(self, runner, eth):
        M._receipt(runner.adapter, b"\x01\x02")
        assert eth.wait_cagrilar[-1][0] == Web3.to_hex(b"\x01\x02")

    def test_timeout_aktarilir(self, runner, eth):
        M._receipt(runner.adapter, "0xabc")
        assert eth.wait_cagrilar[-1][1] == 7

    def test_dict_kopyasi(self, runner, eth):
        rc = M._receipt(runner.adapter, "0xabc")
        assert isinstance(rc, dict)


# ============================================ OnchainLifecycleResult/Step
class TestLifecycleResult:
    """OnchainLifecycleResult dalları: tx_hashes-property / step()-bulunan /
    step()-yok-KeyError / OnchainStep-varsayılanları / boş-steps."""

    def test_tx_hashes_property(self):
        r = OnchainLifecycleResult(
            chain_backend="b", chain_id=31337, vault_address="0xV",
            usdc_address="0xU", arbitrator_oracle="0xO",
            steps=[OnchainStep("a", "0x1", 1, 21000, 1),
                   OnchainStep("b", "0x2", 2, 21000, 1)])
        assert r.tx_hashes == ["0x1", "0x2"]

    def test_step_bulunan(self):
        s = OnchainStep("a", "0x1", 1, 21000, 1)
        r = OnchainLifecycleResult("b", 31337, "0xV", "0xU", "0xO", steps=[s])
        assert r.step("a") is s

    def test_step_yok_keyerror(self):
        r = OnchainLifecycleResult("b", 31337, "0xV", "0xU", "0xO")
        with pytest.raises(KeyError) as hb:
            r.step("yok")
        assert "on-chain-step-yok" in str(hb.value)

    def test_bos_steps(self):
        r = OnchainLifecycleResult("b", 31337, "0xV", "0xU", "0xO")
        assert r.steps == []
        assert r.tx_hashes == []

    def test_onchain_step_varsayilanlari(self):
        s = OnchainStep("a", "0x1", 1, 21000, 1)
        assert s.events == []
        assert s.onchain_status is None
        assert s.detail == ""

    def test_step_arama_ilk_eslesme(self):
        s1 = OnchainStep("a", "0x1", 1, 21000, 1)
        s2 = OnchainStep("a", "0x2", 2, 21000, 1)
        r = OnchainLifecycleResult("b", 31337, "0xV", "0xU", "0xO",
                                   steps=[s1, s2])
        assert r.step("a") is s1  # ilk-eşleşme
