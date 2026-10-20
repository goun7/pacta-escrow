"""pacta MCP sunucu testleri - Model Context Protocol 2025-06-18 over stdio.

JSON-RPC el sikismasi + 2 araci ( vault_status/verify_gates) uctan-uca
SUBPROCESS uzerinden calistirir. Tamga/sester/swarmax MCP testlerinin
ayni deseni ( stdio'yu besle, stdout JSON satirlarini coz).

Sozlesmeler:
  - initialize -> protocolVersion + capabilities + serverInfo
  - tools/list -> 2 aracin-da listesi
  - arac cagrisi -> {"content":[{"type":"text","text":JSON}]}, asla exception
  - bilinmeyen-arac -> JSON-RPC -32601 hatasi
  - verify_gates kaniti > 0 kapisi-gecmis-olmali ( PASS)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp" / "server.py"
PROTOCOL_VERSION = "2025-06-18"


def _rpc(lines, timeout=120):
    env = dict(os.environ)
    reqs = list(lines or [])
    proc = subprocess.run(
        [sys.executable, str(SERVER)],
        input="\n".join(json.dumps(r) for r in reqs) + "\n",
        capture_output=True, text=True, env=env, timeout=timeout,
        cwd=str(ROOT), check=False)
    out = []
    for raw in (proc.stdout or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return proc.returncode, out, proc.stderr


def _payload(resp):
    """tools/call yanitindan JSON-payload'u cikar."""
    text = resp["result"]["content"][0]["text"]
    return json.loads(text)


def test_initialize_el_sikismasi():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    ])
    assert rc == 0, err[:300]
    assert out, "stdout-bos"
    r = out[0]
    assert r["jsonrpc"] == "2.0"
    assert r["id"] == 1
    info = r["result"]
    assert info["protocolVersion"] == PROTOCOL_VERSION
    assert info["capabilities"]["tools"]["listChanged"] is False
    assert info["serverInfo"]["name"] == "pacta"


def test_tools_list():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert rc == 0, err[:300]
    ids = {r.get("id"): r for r in out if "id" in r}
    tools = ids[2]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"vault_status", "verify_gates"}
    for t in tools:
        assert "description" in t and t["description"]
        assert "inputSchema" in t


def test_verify_gates_kanit_donuyor():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "verify_gates", "arguments": {}}},
    ])
    assert rc == 0, err[:300]
    ids = {r.get("id"): r for r in out if "id" in r}
    assert 2 in ids, "arac-cagrisi-yanit-vermedi"
    payload = _payload(ids[2])
    assert isinstance(payload, dict)
    assert payload.get("ok") is True, payload
    assert payload.get("verdict") == "PASS"
    assert payload.get("total", 0) > 0


def test_vault_status_kanit_donuyor():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "vault_status", "arguments": {}}},
    ])
    assert rc == 0, err[:300]
    ids = {r.get("id"): r for r in out if "id" in r}
    payload = _payload(ids[2])
    assert payload.get("ok") is True, payload
    assert payload.get("vault") == "SOLVENT"


def test_bilinmeyen_arac_jsonrpc_hatasi():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "boyle-bir-arac-yok", "arguments": {}}},
    ])
    assert rc == 0, err[:300]
    ids = {r.get("id"): r for r in out if "id" in r}
    r = ids[2]
    assert r.get("error", {}).get("code") == -32601, r


def test_ping_ve_bilinmeyen_method():
    rc, out, err = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "tanimli-degil"},
    ])
    assert rc == 0, err[:300]
    ids = {r.get("id"): r for r in out if "id" in r}
    assert ids[1]["result"] == {}
    assert ids[2]["error"]["code"] == -32601
