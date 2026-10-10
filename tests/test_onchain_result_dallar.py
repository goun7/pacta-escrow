"""OnchainLifecycle._result dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: saf in-memory; __init__'siz kur (__new__) — anvil/web3 YOK.
"""
from types import SimpleNamespace

import pytest

from pacta.chain.onchain import OnchainEscrowRunner as OnchainLifecycle, OnchainLifecycleResult


def _lc(**kw):
    lc = OnchainLifecycle.__new__(OnchainLifecycle)
    lc.adapter = SimpleNamespace(backend=kw.get("backend", "anvil"))
    lc.chain_id = kw.get("chain_id", 31337)
    lc.vault_address = kw.get("vault", "0xVAULT")
    lc.usdc_address = kw.get("usdc", "0xUSDC")
    lc.oracle = kw.get("oracle", "0xORACLE")
    return lc


# -- mutlu-yol ---------------------------------------------------------------------------------

def test_returns_result():
    assert isinstance(_lc()._result(), OnchainLifecycleResult)


def test_chain_backend():
    assert _lc(backend="anvil")._result().chain_backend == "anvil"


def test_chain_id():
    assert _lc(chain_id=31337)._result().chain_id == 31337


def test_vault_address():
    assert _lc(vault="0xV")._result().vault_address == "0xV"


def test_usdc_address():
    assert _lc(usdc="0xU")._result().usdc_address == "0xU"


def test_arbitrator_oracle():
    assert _lc(oracle="0xO")._result().arbitrator_oracle == "0xO"


# -- str-donusum ---------------------------------------------------------------------------------

def test_vault_str_coerced():
    class _Str:
        def __str__(self):
            return "0xSTRVAULT"
    lc = _lc()
    lc.vault_address = _Str()
    assert lc._result().vault_address == "0xSTRVAULT"


def test_usdc_str_coerced():
    class _Str:
        def __str__(self):
            return "0xSTRUSDC"
    lc = _lc()
    lc.usdc_address = _Str()
    assert lc._result().usdc_address == "0xSTRUSDC"


def test_oracle_str_coerced():
    class _Str:
        def __str__(self):
            return "0xSTRORACLE"
    lc = _lc()
    lc.oracle = _Str()
    assert lc._result().arbitrator_oracle == "0xSTRORACLE"


def test_str_of_str_identity():
    assert _lc(vault="0xA")._result().vault_address == "0xA"


# -- None ---------------------------------------------------------------------------------

def test_none_vault():
    assert _lc(vault=None)._result().vault_address == "None"


def test_none_usdc():
    assert _lc(usdc=None)._result().usdc_address == "None"


def test_none_oracle():
    assert _lc(oracle=None)._result().arbitrator_oracle == "None"


def test_str_none_is_str_none():
    assert _lc(vault=None)._result().vault_address == str(None)


# -- backend chain_id turleri ---------------------------------------------------------------------------------

def test_backend_str():
    assert isinstance(_lc()._result().chain_backend, str)


def test_chain_id_int():
    assert isinstance(_lc()._result().chain_id, int)


def test_chain_id_zero():
    assert _lc(chain_id=0)._result().chain_id == 0


def test_chain_id_large():
    assert _lc(chain_id=11155111)._result().chain_id == 11155111


def test_backend_variants():
    for b in ("anvil", "hardhat", "geth", "reth"):
        assert _lc(backend=b)._result().chain_backend == b


# -- result-yapisi ---------------------------------------------------------------------------------

def test_result_fields():
    r = _lc()._result()
    assert set(("chain_backend", "chain_id", "vault_address",
                "usdc_address", "arbitrator_oracle")) <= set(vars(r))


def test_result_has_steps():
    r = _lc()._result()
    assert hasattr(r, "steps")


def test_tx_hashes_property():
    r = _lc()._result()
    assert r.tx_hashes == []


def test_result_no_mutate_source():
    lc = _lc()
    lc._result()
    assert lc.vault_address == "0xVAULT"
    assert lc.chain_id == 31337


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    lc = _lc()
    assert lc._result().vault_address == lc._result().vault_address


def test_new_result_each_call():
    lc = _lc()
    a, b = lc._result(), lc._result()
    assert a is not b
    assert a.vault_address == b.vault_address


def test_independent_lifecycles():
    a, b = _lc(vault="0xA"), _lc(vault="0xB")
    assert a._result().vault_address == "0xA"
    assert b._result().vault_address == "0xB"


# -- field-bagimsiz ---------------------------------------------------------------------------------

def test_vault_only():
    lc = _lc()
    lc.usdc_address = None
    r = lc._result()
    assert r.vault_address == "0xVAULT"


def test_all_fields_set():
    lc = _lc(backend="hardhat", chain_id=1, vault="0xV",
             usdc="0xU", oracle="0xO")
    r = lc._result()
    assert (r.chain_backend, r.chain_id) == ("hardhat", 1)
    assert (r.vault_address, r.usdc_address, r.arbitrator_oracle) == \
        ("0xV", "0xU", "0xO")


def test_adapter_backend_not_read_after_init():
    """_result her cagrida adapter.backend okur (taze)."""
    lc = _lc(backend="anvil")
    lc.adapter.backend = "hardhat"
    assert lc._result().chain_backend == "hardhat"
