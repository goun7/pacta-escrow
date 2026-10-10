"""chain.onchain._deploy dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-3: web3/adapter stub — gercek ag/RPC YAPILMADI.
"""
import pytest

from pacta.chain.adapter import EvmChainAdapter
from pacta.chain.onchain import (
    OnchainContractError, OnchainEscrowRunner)


class _Ctor:
    """contract.constructor stub."""

    def __init__(self, args):
        self.args = args
        self.transact_kwargs = None

    def transact(self, kwargs):
        self.transact_kwargs = kwargs
        return b"\x01"


class _Contract:
    def __init__(self):
        self.ctor_args = None
        self.last = None

    def constructor(self, *args):
        self.ctor_args = args
        self.last = _Ctor(args)
        return self.last


class _Eth:
    def __init__(self, receipt):
        self._receipt = receipt
        self._contract = _Contract()
        self.last_kwargs = None
        self.wait_kwargs = []
        self.tx_hashes = []

    def contract(self, **kw):
        self.last_kwargs = kw
        return self._contract

    def wait_for_transaction_receipt(self, txh, timeout=None):
        self.wait_kwargs.append(timeout)
        self.tx_hashes.append(txh)
        return self._receipt


class _W3:
    def __init__(self, receipt):
        self.eth = _Eth(receipt)


class _Adapter:
    def __init__(self, receipt, operator="0xOP", timeout=7, chain_id=31337):
        self._operator = operator
        self._timeout = timeout
        self._chain_id = chain_id
        self.w3 = _W3(receipt)

    def chain_id(self):
        return self._chain_id

    def operator_account(self):
        return self._operator

    @property
    def receipt_timeout_s(self):
        return self._timeout


@pytest.fixture
def deploy(monkeypatch):
    import pacta.chain.onchain as M
    monkeypatch.setattr(
        M, "_load_artifact",
        lambda name: {"abi": [], "bytecode": {"object": "0x6080"}})

    def _make(receipt, **kw):
        a = _Adapter(receipt, **kw)
        return OnchainEscrowRunner(a), a
    return _make


def _receipt(status=1, addr="0xVAULT"):
    return {"status": status, "contractAddress": addr,
            "blockNumber": 10, "gasUsed": 21000}


# -- temel ---------------------------------------------------------------------------------

def test_returns_address_string(deploy):
    lc, _ = deploy(_receipt())
    assert lc._deploy("MockUSDC") == "0xVAULT"


def test_returns_str_type(deploy):
    lc, _ = deploy(_receipt())
    assert isinstance(lc._deploy("X"), str)


def test_receipt_status_0_raises(deploy):
    lc, _ = deploy(_receipt(status=0))
    with pytest.raises(OnchainContractError):
        lc._deploy("X")


def test_status_0_message_has_name(deploy):
    lc, _ = deploy(_receipt(status=0))
    with pytest.raises(OnchainContractError) as e:
        lc._deploy("PactaVault")
    assert "PactaVault" in str(e.value)


def test_status_0_message_has_status(deploy):
    lc, _ = deploy(_receipt(status=0))
    with pytest.raises(OnchainContractError) as e:
        lc._deploy("X")
    assert "status=0" in str(e.value)


def test_missing_address_raises(deploy):
    lc, _ = deploy({"status": 1, "contractAddress": None})
    with pytest.raises(OnchainContractError):
        lc._deploy("X")


def test_missing_address_message(deploy):
    lc, _ = deploy({"status": 1, "contractAddress": None})
    with pytest.raises(OnchainContractError) as e:
        lc._deploy("Y")
    assert "Y" in str(e.value)


def test_empty_address_raises(deploy):
    lc, _ = deploy({"status": 1, "contractAddress": ""})
    with pytest.raises(OnchainContractError):
        lc._deploy("X")


def test_status_missing_treated_as_0(deploy):
    """receipt.get('status', 0)."""
    lc, _ = deploy({"contractAddress": "0xV"})
    with pytest.raises(OnchainContractError):
        lc._deploy("X")


def test_status_none_treated_as_0(deploy):
    lc, _ = deploy({"status": None, "contractAddress": "0xV"})
    with pytest.raises(OnchainContractError):
        lc._deploy("X")


# -- cagri ---------------------------------------------------------------------------------

def test_constructor_called_with_artifact_abi(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("MockUSDC")
    assert a.w3.eth.last_kwargs is not None


def test_transact_from_operator(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("X")
    assert a.w3.eth._contract.last.transact_kwargs == {"from": "0xOP"}


def test_ctor_args_forwarded(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("X", 1, "foo")
    assert a.w3.eth._contract.ctor_args == (1, "foo")


def test_no_ctor_args_default(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("X")
    assert a.w3.eth._contract.ctor_args == ()


def test_wait_timeout_from_adapter(deploy):
    lc, a = deploy(_receipt(), timeout=42)
    lc._deploy("X")
    assert a.w3.eth.wait_kwargs == [42]


def test_wait_called_once(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("X")
    assert len(a.w3.eth.wait_kwargs) == 1


def test_tx_hash_is_hex_string(deploy):
    lc, a = deploy(_receipt())
    lc._deploy("X")
    h = a.w3.eth.tx_hashes[0]
    assert isinstance(h, str)
    assert h.startswith("0x")


# -- artifact ---------------------------------------------------------------------------------

def test_missing_artifact_raises(monkeypatch):
    from pathlib import Path
    import pacta.chain.onchain as M
    monkeypatch.setattr(M, "_FORGE_OUT", Path("/nonexistent-forge-out"))
    lc = OnchainEscrowRunner(_Adapter(_receipt()))
    with pytest.raises(OnchainContractError):
        lc._deploy("Nope")


def test_artifact_error_message_has_forge_build(monkeypatch):
    from pathlib import Path
    import pacta.chain.onchain as M
    monkeypatch.setattr(M, "_FORGE_OUT", Path("/nonexistent-forge-out"))
    lc = OnchainEscrowRunner(_Adapter(_receipt()))
    with pytest.raises(OnchainContractError) as e:
        lc._deploy("Nope")
    assert "forge build" in str(e.value)


def test_artifact_loaded(tmp_path, monkeypatch):
    import json
    import pacta.chain.onchain as M
    d = tmp_path / "out" / "Token.sol"
    d.mkdir(parents=True)
    (d / "Token.json").write_text(
        json.dumps({"abi": [], "bytecode": {"object": "0x6080"}}),
        encoding="utf-8")
    monkeypatch.setattr(M, "_FORGE_OUT", tmp_path / "out")
    a = _Adapter(_receipt())
    lc = OnchainEscrowRunner(a)
    lc._deploy("Token")
    assert a.w3.eth.last_kwargs is not None


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(deploy):
    lc, _ = deploy(_receipt())
    assert lc._deploy("A") == lc._deploy("A") == "0xVAULT"


def test_two_deploys_distinct_addresses(deploy):
    class _Two:
        def __init__(self):
            self.n = 0

        def wait_for_transaction_receipt(self, txh, timeout=None):
            self.n += 1
            return _receipt(addr=f"0x{self.n:02d}")
    lc, a = deploy(_receipt())
    two = _Two()
    a.w3.eth.wait_for_transaction_receipt = two.wait_for_transaction_receipt
    assert lc._deploy("A") == "0x01"
    assert lc._deploy("A") == "0x02"
