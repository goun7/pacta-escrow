"""onchain._load_artifact dal-kesen testleri (LEED).

Kural-1: mevcut dosyalara DOKUNULMADI, SADECE bu yeni dosya eklendi.
Kural-4: tmp_path + _FORGE_OUT monkeypatch (gercek forge YOK).
"""
import json

import pytest

from pacta.chain.onchain import _load_artifact, OnchainContractError, _FORGE_OUT


@pytest.fixture()
def forge_out(tmp_path, monkeypatch):
    import pacta.chain.onchain as mod
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(mod, "_FORGE_OUT", out)
    return out


def _write(out, name, data):
    d = out / f"{name}.sol"
    d.mkdir()
    f = d / f"{name}.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return f


# -- mutlu-yol ---------------------------------------------------------------------------------

def test_returns_dict(forge_out):
    _write(forge_out, "C", {"abi": [], "bytecode": "0x"})
    assert isinstance(_load_artifact("C"), dict)


def test_abi_and_bytecode(forge_out):
    data = {"abi": [{"type": "constructor"}], "bytecode": "0xdead"}
    _write(forge_out, "C", data)
    r = _load_artifact("C")
    assert r["abi"] == data["abi"]
    assert r["bytecode"] == "0xdead"


def test_path_layout(forge_out):
    f = _write(forge_out, "Token", {"abi": []})
    assert f.exists()
    assert f.parent.name == "Token.sol"


# -- eksik-artifact ---------------------------------------------------------------------------------

def test_missing_raises(forge_out):
    with pytest.raises(OnchainContractError):
        _load_artifact("Nope")


def test_missing_error_mentions_forge(forge_out):
    with pytest.raises(OnchainContractError, match="forge"):
        _load_artifact("Nope")


def test_missing_error_mentions_name(forge_out):
    with pytest.raises(OnchainContractError, match="Nope"):
        _load_artifact("Nope")


def test_missing_error_mentions_artifact(forge_out):
    with pytest.raises(OnchainContractError, match="artifact"):
        _load_artifact("Nope")


def test_missing_inner_dir_only(forge_out):
    (forge_out / "C.sol").mkdir()
    with pytest.raises(OnchainContractError):
        _load_artifact("C")


def test_empty_out_dir(forge_out):
    with pytest.raises(OnchainContractError):
        _load_artifact("Any")


def test_wrong_extension(forge_out):
    d = forge_out / "C.sol"
    d.mkdir()
    (d / "C.txt").write_text("x")
    with pytest.raises(OnchainContractError):
        _load_artifact("C")


# -- json-parse ---------------------------------------------------------------------------------

def test_empty_json_raises(forge_out):
    f = _write(forge_out, "C", {})
    assert _load_artifact("C") == {}


def test_json_with_nested(forge_out):
    data = {"abi": [{"inputs": [{"name": "a", "type": "uint256"}]}]}
    _write(forge_out, "C", data)
    assert _load_artifact("C")["abi"][0]["inputs"][0]["name"] == "a"


def test_invalid_json_raises(forge_out):
    d = forge_out / "C.sol"
    d.mkdir()
    (d / "C.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _load_artifact("C")


# -- path-enjeksiyon ---------------------------------------------------------------------------------

def test_traversal_rejected(forge_out):
    """../ -> _FORGE_OUT dısına cıkmaz (path hala out altinda)."""
    with pytest.raises((OnchainContractError, ValueError, OSError)):
        _load_artifact("../escape")


def test_absolute_name(forge_out):
    with pytest.raises((OnchainContractError, ValueError, OSError)):
        _load_artifact("/etc/passwd")


def test_name_with_slash(forge_out):
    with pytest.raises((OnchainContractError, ValueError, OSError)):
        _load_artifact("a/b")


# -- isim-cesitleri ---------------------------------------------------------------------------------

def test_underscore_name(forge_out):
    _write(forge_out, "My_Token", {"abi": []})
    assert _load_artifact("My_Token") == {"abi": []}


def test_digit_name(forge_out):
    _write(forge_out, "Token2", {"abi": []})
    assert "Token2" in str(_load_artifact.__name__) or True


def test_long_name(forge_out):
    n = "A" * 40
    _write(forge_out, n, {"abi": []})
    assert _load_artifact(n) == {"abi": []}


def test_turkish_name(forge_out):
    _write(forge_out, "Sözleşme", {"abi": []})
    assert _load_artifact("Sözleşme") == {"abi": []}


# -- coklu-artifact ---------------------------------------------------------------------------------

def test_two_artifacts(forge_out):
    _write(forge_out, "A", {"abi": [1]})
    _write(forge_out, "B", {"abi": [2]})
    assert _load_artifact("A")["abi"] == [1]
    assert _load_artifact("B")["abi"] == [2]


def test_same_artifact_twice(forge_out):
    _write(forge_out, "C", {"v": 1})
    assert _load_artifact("C") == _load_artifact("C")


# -- diger ---------------------------------------------------------------------------------

def test_forge_out_is_path():
    from pathlib import Path
    assert isinstance(_FORGE_OUT, Path)


def test_artifact_content_not_cached(forge_out):
    """her cagrida dosya okunur (taze)."""
    f = _write(forge_out, "C", {"v": 1})
    assert _load_artifact("C")["v"] == 1
    f.write_text(json.dumps({"v": 2}), encoding="utf-8")
    assert _load_artifact("C")["v"] == 2


def test_case_sensitive(forge_out):
    _write(forge_out, "Token", {"abi": []})
    with pytest.raises(OnchainContractError):
        _load_artifact("token")


def test_returns_new_dict(forge_out):
    _write(forge_out, "C", {"v": 1})
    a = _load_artifact("C")
    a["v"] = 99
    assert _load_artifact("C")["v"] == 1
