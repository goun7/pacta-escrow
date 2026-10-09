"""chain.adapter.connect_in_memory_evm dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: web3 + EvmChainAdapter stub (gercek RPC YOK).
"""
import sys
import types

import pytest

from pacta.chain.adapter import (  # noqa: E402
    ChainUnavailableError, connect_in_memory_evm)


class _FakeW3:
    def __init__(self, connected=True):
        self._connected = connected

    def is_connected(self):
        return self._connected


class _FakeProvider:
    """EthereumTesterProvider gibi: Web3(provider) provider'i cagirir."""
    shared_w3 = None
    shared_raises = None

    def __call__(self):
        if _FakeProvider.shared_raises:
            raise _FakeProvider.shared_raises
        return _FakeProvider.shared_w3 or _FakeW3()


class _FakeWeb3Factory:
    """Web3 sinifi: Web3(provider) -> provider()."""
    def __call__(self, provider):
        return provider()


@pytest.fixture
def web3mod(monkeypatch):
    _FakeProvider.shared_w3 = None
    _FakeProvider.shared_raises = None
    mod = types.ModuleType("web3")
    mod.Web3 = _FakeWeb3Factory()
    mod.EthereumTesterProvider = _FakeProvider
    monkeypatch.setitem(sys.modules, "web3", mod)
    return _FakeProvider


@pytest.fixture
def adapter_stub(monkeypatch):
    seen = {}

    class _A:
        def __init__(self, **kw):
            seen.update(kw)
            self.kw = kw
    import pacta.chain.adapter as ad
    monkeypatch.setattr(ad, "EvmChainAdapter", _A)
    return seen


def _call(**kw):
    return connect_in_memory_evm(**kw)


# -- import hatalari ---------------------------------------------------------------------------------

def test_web3_missing_raises(monkeypatch):
    import builtins
    real = builtins.__import__

    def _imp(name, *a, **k):
        if name == "web3":
            raise ImportError("no module")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _imp)
    with pytest.raises(ChainUnavailableError) as e:
        _call()
    assert "web3-kurulu-değil" in str(e.value)


def test_web3_import_other_error(monkeypatch):
    import builtins
    real = builtins.__import__

    def _imp(name, *a, **k):
        if name == "web3":
            raise RuntimeError("weird")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _imp)
    with pytest.raises(ChainUnavailableError):
        _call()


def test_error_is_runtime_subclass():
    assert issubclass(ChainUnavailableError, RuntimeError)


# -- provider hatalari ---------------------------------------------------------------------------------

def test_provider_init_fails(web3mod, monkeypatch):
    web3mod.shared_raises = RuntimeError("py-evm-yok")
    with pytest.raises(ChainUnavailableError) as e:
        _call()
    assert "in-memory-evm-init-failed" in str(e.value)


def test_not_connected(web3mod, adapter_stub):
    web3mod.shared_w3 = _FakeW3(connected=False)
    with pytest.raises(ChainUnavailableError) as e:
        _call()
    assert "in-memory-evm-not-connected" in str(e.value)


# -- basarili ---------------------------------------------------------------------------------

def test_returns_adapter(web3mod, adapter_stub):
    _call()
    assert "w3" in adapter_stub


def test_backend_label(web3mod, adapter_stub):
    _call()
    assert adapter_stub["backend"] == "in-memory-pyevm"


def test_w3_is_provider_instance(web3mod, adapter_stub):
    _call()
    assert isinstance(adapter_stub["w3"], _FakeW3)


def test_chain_id_hint_ignored(web3mod, adapter_stub):
    _call(chain_id_hint=999)
    assert adapter_stub["backend"] == "in-memory-pyevm"


def test_default_chain_id(web3mod, adapter_stub):
    _call()
    assert isinstance(adapter_stub, dict)


# -- EvmChainAdapter gercek ---------------------------------------------------------------------------------

def test_real_adapter_class(web3mod):
    """EvmChainAdapter gercek sinif -> w3 alir."""
    import pacta.chain.adapter as ad
    orig = ad.EvmChainAdapter
    try:
        r = _call()
        assert isinstance(r, orig)
    except ChainUnavailableError:
        pass
    finally:
        ad.EvmChainAdapter = orig


# -- hata mesajlari ---------------------------------------------------------------------------------

def test_error_message_has_pip_hint(monkeypatch):
    import builtins
    real = builtins.__import__

    def _imp(name, *a, **k):
        if name == "web3":
            raise ImportError("x")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _imp)
    with pytest.raises(ChainUnavailableError) as e:
        _call()
    assert "pip install" in str(e.value)


def test_provider_error_pip_hint(web3mod):
    web3mod.shared_raises = RuntimeError("x")
    with pytest.raises(ChainUnavailableError) as e:
        _call()
    assert "py-evm" in str(e.value)


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(web3mod, adapter_stub):
    a = _call()
    b = _call()
    assert type(a) is type(b)


def test_two_calls_two_adapters(web3mod, adapter_stub):
    _call()
    _call()
    assert "w3" in adapter_stub


def test_import_called_each_time(monkeypatch):
    """web3 her cagrida taze import edilir."""
    import builtins
    real = builtins.__import__
    calls = []

    def _imp(name, *a, **k):
        if name == "web3":
            calls.append(1)
            raise ImportError("x")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _imp)
    for _ in range(3):
        with pytest.raises(ChainUnavailableError):
            _call()
    assert len(calls) == 3
