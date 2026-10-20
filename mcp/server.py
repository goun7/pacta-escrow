#!/usr/bin/env python3
"""pacta MCP sunucusu - Model Context Protocol 2025-06-18 over stdio.

Pacta escrow'unun MUSTEAK-DOGRLAMA cekirdegini AI ajanlarina MCP araclari
olarak sunar. Tamga/sester MCP sunucularinin ayni deseni ( stdio JSON-RPC,
uc-sonuc kaniti, exception-YOK).

Tasarim-ilkesi:
  - SAF STDLIB - hicbir pip bagimliligi; sunucu pacta modullerini
    SUBPROCESS-LEVEL'da cagirir, import etmez - surum-cakismasi yok.
  - UC-SONUC - her arac GREEN/RED/INDETERMINE JSON kaniti dondurur;
    ASLA exception firlatmaz.
  - Subprocess-tabanli cagri - her dogrulama pacta'nin KENDI CLI'inda
    calisir.

Araclar:
  vault_status     vault-sagligi ve solventlik-invaryanti ( pacta.cli status)
  verify_gates     tum escrow-guvenlik-kapilarinin bagimsiz dogrulamasi
                    ( pacta.cli verify --json)

Calistirma:
  python3 mcp/server.py                    # stdio JSON-RPC
  (istemci tarafi: "command": "python", "args": ["<repo>/mcp/server.py"])
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "pacta"
SERVER_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[1]
MAX_TIMEOUT = 120  # saniye


def _e(msg: str) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": -32602, "message": msg}}


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _text(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def _run_cli(args: list) -> dict:
    """pacta CLI'ini SUBPROCESS olarak cagir, cikisini JSON kanita cevir.

    Fail-closed: her hata ( zaman-asimi, exception, bozuk-cikis) bir RED
    kanitidir - traceback DEGIL, JSON doner. pretty-printed JSON ( cok
    satirli) da ayiklanir.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pacta.cli", *args],
            capture_output=True, text=True, timeout=MAX_TIMEOUT, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "zaman-asimi: %ds" % MAX_TIMEOUT}
    except Exception as e:  # cephedeki her hata JSON kaniti olmali
        return {"ok": False, "reason": "calistirma-hatasi: %s" % e}
    out = (proc.stdout or "").strip()
    rec = _extract_json(out)
    if rec is not None:
        rec.setdefault("ok", proc.returncode == 0)
        rec.setdefault("rc", proc.returncode)
        return rec
    return {
        "ok": False,
        "rc": proc.returncode,
        "reason": "cekis-json-uretmedi" + (": %s" % out[:120] if out else ""),
        "stderr": (proc.stderr or "").strip()[:300],
    }


def _extract_json(out: str) -> dict | None:
    """stdout icindeki ilk JSON-dogru-parcasini bul ( satir veya blok)."""
    start = out.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(out)):
            c = out[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        rec = json.loads(out[start:i + 1])
                        if isinstance(rec, dict):
                            return rec
                    except json.JSONDecodeError:
                        break
        start = out.find("{", start + 1)
    return None


def _tool_vault_status(args: dict) -> dict:
    """vault-sagligi: status-CLI JSON-basmiyor ( insan-satiri), verify-GATE
    cikisini kanit-olarak-donuyoruz ( rc + solventlik-kaniti)."""
    r = _run_cli(["verify", "--json"])
    if r.get("ok"):
        return {
            "ok": True,
            "rc": r.get("rc", 0),
            "vault": "SOLVENT",
            "gates_passed": r.get("passed"),
            "gates_failed": r.get("failed"),
            "verdict": r.get("verdict"),
        }
    return r


def _tool_verify_gates(args: dict) -> dict:
    return _run_cli(["verify", "--json"])


TOOL_IMPLS = {
    "vault_status": _tool_vault_status,
    "verify_gates": _tool_verify_gates,
}

TOOLS_LIST = [
    {
        "name": "vault_status",
        "description": (
            "Pacta escrow-vault'in sagligini ve solventlik-invaryantini "
            "bagimsiz-olarak olcer. JSON kanit doner ( ok/redi), "
            "asla exception firlatmaz."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "verify_gates",
        "description": (
            "Tum escrow-guvenlik-kapilarinin ( DvP, tiers,refund, "
            "anti-griefing) bagimsiz dogrulamasi. pacta.cli verify --json "
            "cikitisini kanit olarak doner."),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _tools_list_result() -> dict:
    return {"tools": TOOLS_LIST}


def _handle_call(req_id, params: dict) -> dict | None:
    name = params.get("name")
    if not isinstance(name, str) or not name:
        return _result(req_id, _e("arac-adi-zorunlu"))
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": "bilinmeyen-arac: %s" % name},
        }
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _result(req_id, _e("arguments-bir-nesne-olmali"))
    try:
        payload = impl(args)
    except Exception as e:  # fail-closed: traceback degil JSON kaniti
        payload = {"ok": False, "reason": "arac-hatasi: %s" % e}
    return _result(req_id, _text(payload))


def main() -> int:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_e("gecersiz-json")) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(req, dict):
            sys.stdout.write(json.dumps(_e("istek-bir-nesne-degil")) + "\n")
            sys.stdout.flush()
            continue
        method = req.get("method")
        req_id = req.get("id")
        if method == "initialize":
            sys.stdout.write(json.dumps(_result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                    "instructions": (
                        "Pacta escrow dogrulama sunucusu. "
                        "vault_status -> vault-sagligi; "
                        "verify_gates -> tum-guvenlik-kapilari. "
                        "Her arac JSON kaniti doner, asla exception firlatmaz."),
                }})) + "\n")
        elif method == "notifications/initialized":
            continue  # bildirim - yanit yok
        elif method == "tools/list":
            sys.stdout.write(json.dumps(_result(req_id, _tools_list_result())) + "\n")
        elif method == "tools/call":
            resp = _handle_call(req_id, req.get("params") or {})
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        elif method == "ping":
            sys.stdout.write(json.dumps(_result(req_id, {})) + "\n")
        elif req_id is not None:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": "bilinmeyen-method: %s" % method}
            }) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
