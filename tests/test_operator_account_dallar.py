"""chain.adapter.ChainAdapter.operator_account dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-3: web3 stub — gercek ag/RPC YAPILMADI.
"""
import pytest

from pacta.chain.adapter import (  # noqa: E402
    EvmChainAdapter, ChainUnavailableError)


class _Eth:
    def __init__(self, accounts=None, error=None):
        self._accounts = accounts
        self._error = error

    @property
    def accounts(self):
        if self._error:
            raise self._error
        return self._accounts


class _W3:
    def __init__(self, accounts=None, error=None):
        self.eth = _Eth(accounts, error)


def _adapter(accounts=None, error=None, operator=None):
    return EvmChainAdapter(
        w3=_W3(accounts, error),
        backend="anvil",
        rpc_url="http://test:8545",
        operator_account=operator,
    )


# -- temel ---------------------------------------------------------------------------------

def test_returns_str():
    assert isinstance(_adapter(accounts=["0xabc"]).operator_account(), str)


def test_returns_first_account():
    a = _adapter(accounts=["0xabc", "0xdef"])
    assert a.operator_account() == "0xabc"


def test_accounts_index_0():
    """eth_accounts[0] secimi."""
    a = _adapter(accounts=["zzz", "aaa"])
    assert a.operator_account() == "zzz"


def test_single_account():
    assert _adapter(accounts=["0x1"]).operator_account() == "0x1"


def test_many_accounts_first():
    a = _adapter(accounts=[f"0x{i:02x}" for i in range(10)])
    assert a.operator_account() == "0x00"


# -- cache ---------------------------------------------------------------------------------

def test_cached_after_first_call():
    a = _adapter(accounts=["0xabc"])
    first = a.operator_account()
    a.w3.eth._accounts = []
    assert a.operator_account() == first


def test_cached_even_if_accounts_change():
    a = _adapter(accounts=["0xabc"])
    a.operator_account()
    a.w3.eth._accounts = ["0xother"]
    assert a.operator_account() == "0xabc"


def test_cache_stored_on_instance():
    a = _adapter(accounts=["0xabc"])
    assert a._operator is None
    a.operator_account()
    assert a._operator == "0xabc"


def test_operator_arg_wins():
    a = _adapter(accounts=["0xabc"], operator="0xOP")
    assert a.operator_account() == "0xOP"


def test_operator_arg_skips_rpc():
    a = _adapter(accounts=["0xabc"], operator="0xOP")
    a.w3.eth._error = RuntimeError("boom")
    assert a.operator_account() == "0xOP"


def test_operator_arg_no_accounts_access():
    a = _adapter(operator="0xOP")
    a.w3.eth._accounts = None
    assert a.operator_account() == "0xOP"


def test_two_instances_independent():
    a = _adapter(accounts=["0xa"])
    b = _adapter(accounts=["0xb"])
    assert a.operator_account() == "0xa"
    assert b.operator_account() == "0xb"


# -- hata ---------------------------------------------------------------------------------

def test_accounts_error_raises():
    a = _adapter(error=ConnectionError("refused"))
    with pytest.raises(ChainUnavailableError):
        a.operator_account()


def test_accounts_error_message_has_rpc():
    a = _adapter(error=ConnectionError("refused"))
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "http://test:8545" in str(ei.value)


def test_accounts_error_message_has_type():
    a = _adapter(error=ConnectionError("refused"))
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "ConnectionError" in str(ei.value)


def test_accounts_error_chained_from():
    a = _adapter(error=ConnectionError("refused"))
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert ei.value.__cause__ is not None


def test_accounts_error_mentions_unlock():
    a = _adapter(error=ConnectionError("refused"))
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "unlock" in str(ei.value).lower()


def test_empty_accounts_raises():
    a = _adapter(accounts=[])
    with pytest.raises(ChainUnavailableError):
        a.operator_account()


def test_empty_accounts_message_has_rpc():
    a = _adapter(accounts=[])
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "http://test:8545" in str(ei.value)


def test_empty_accounts_mentions_operator():
    a = _adapter(accounts=[])
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "OPERATOR" in str(ei.value).upper()


def test_empty_accounts_no_private_key():
    a = _adapter(accounts=[])
    with pytest.raises(ChainUnavailableError) as ei:
        a.operator_account()
    assert "PRIVATE" not in str(ei.value).upper() or "YASAK" in str(ei.value)


def test_error_not_cached():
    a = _adapter(error=ConnectionError("x"))
    with pytest.raises(ChainUnavailableError):
        a.operator_account()
    a.w3.eth._error = None
    a.w3.eth._accounts = ["0xabc"]
    assert a.operator_account() == "0xabc"


# -- islenmemis hesap ------------------------------------------------------------------------

def test_none_accounts_raises():
    a = _adapter()
    a.w3.eth._accounts = None
    with pytest.raises(ChainUnavailableError):
        a.operator_account()


def test_accounts_none_error():
    a = _adapter()
    a.w3.eth._accounts = None
    a.w3.eth._error = RuntimeError("nope")
    with pytest.raises(ChainUnavailableError):
        a.operator_account()


# -- chain_id-bagimsiz ------------------------------------------------------------------------

def test_no_chain_id_access():
    a = _adapter(accounts=["0xabc"])
    a.operator_account()
    assert not hasattr(a.w3, "_chain_id")


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable():
    a = _adapter(accounts=["0xabc"])
    assert a.operator_account() == a.operator_account()


def test_default_operator_none():
    assert _adapter(accounts=["0xabc"])._operator is None
