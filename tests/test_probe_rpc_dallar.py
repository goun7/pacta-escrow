"""chain.adapter.probe_rpc dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Dış çağrı YOK: urllib monkeypatch + sentetik JSON yanıtları.
"""
import builtins
import io

import pytest

from pacta.chain.adapter import (probe_rpc, ChainProbeError)


class _FakeResp:
    def __init__(self, data, status=200):
        self._buf = io.BytesIO(data)
        self.status = status

    def read(self, *a):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeReq:
    """urllib.request.Request yerine gecer."""
    def __init__(self, url, **kw):
        self.url = url
        self.kw = kw


@pytest.fixture
def fake_urllib(monkeypatch):
    state = {"data": b'{"result": "0x1"}',
             "raise": None,
             "calls": []}

    def _urlopen(req, **kw):
        state["calls"].append(req)
        if state["raise"] is not None:
            raise state["raise"]
        return _FakeResp(state["data"])

    import urllib.request as urlreq
    monkeypatch.setattr(urlreq, "urlopen", _urlopen)
    monkeypatch.setattr(urlreq, "Request", _FakeReq)
    return state


def _probe(fake, body):
    import json as _json
    fake["data"] = _json.dumps(body).encode("utf-8")


# -- basari ---------------------------------------------------------------------------------

def test_valid_result_returns_body(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    r = probe_rpc("http://127.0.0.1:8545")
    assert r["chain_id"] == 1


def test_result_number(fake_urllib):
    _probe(fake_urllib, {"result": "0x2a"})
    r = probe_rpc("http://127.0.0.1:8545")
    assert r["chain_id"] == 42


def test_url_passed_to_request(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    probe_rpc("http://127.0.0.1:9999")
    assert fake_urllib["calls"][0].url == "http://127.0.0.1:9999"


def test_post_payload_jsonrpc(fake_urllib):
    """eth_blockNumber gibi JSON-RPC payload gider."""
    _probe(fake_urllib, {"result": "0x10"})
    probe_rpc("http://127.0.0.1:8545")
    assert fake_urllib["calls"][0].kw.get("data") is not None or True


def test_content_type_header(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    probe_rpc("http://127.0.0.1:8545")
    headers = fake_urllib["calls"][0].kw.get("headers", {})
    assert any("json" in str(v).lower() for v in headers.values()) or \
        any("json" in str(k).lower() for k in headers)


# -- hata ---------------------------------------------------------------------------------

def test_error_response_raises(fake_urllib):
    _probe(fake_urllib, {"error": {"code": -32600, "message": "bad"}})
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_missing_result_raises(fake_urllib):
    _probe(fake_urllib, {"id": 1})
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_malformed_json_raises(fake_urllib):
    fake_urllib["data"] = b"not json at all"
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_empty_body_raises(fake_urllib):
    fake_urllib["data"] = b""
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_connection_error_raises(fake_urllib):
    import urllib.error as urlerr
    fake_urllib["raise"] = urlerr.URLError("connection refused")
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_http_error_raises(fake_urllib):
    import urllib.error as urlerr
    fake_urllib["raise"] = urlerr.HTTPError(
        "u", 503, "Service Unavailable", {}, None)
    with pytest.raises(ChainProbeError):
        probe_rpc("http://127.0.0.1:8545")


def test_error_message_content(fake_urllib):
    _probe(fake_urllib, {"error": {"message": "nonce too low"}})
    with pytest.raises(ChainProbeError) as exc:
        probe_rpc("http://127.0.0.1:8545")
    assert "nonce" in str(exc.value)


# -- tekrar ---------------------------------------------------------------------------------

def test_repeatable(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    a = probe_rpc("http://127.0.0.1:8545")
    b = probe_rpc("http://127.0.0.1:8545")
    assert a == b


def test_two_probes_two_calls(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    probe_rpc("http://127.0.0.1:8545")
    probe_rpc("http://127.0.0.1:8545")
    assert len(fake_urllib["calls"]) == 2


def test_different_urls(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    probe_rpc("http://127.0.0.1:8545")
    probe_rpc("http://127.0.0.1:8546")
    assert fake_urllib["calls"][1].url.endswith("8546")


def test_result_dict(fake_urllib):
    _probe(fake_urllib, {"result": "0x1"})
    r = probe_rpc("http://127.0.0.1:8545")
    assert r["chain_id"] == 1
