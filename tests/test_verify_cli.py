"""
Bağımsız-doğrulama CLI'si için testler ( kanıt-entegrasyonu).

run_verify sıfırdan, demo-paylaşımlı-durum-kullanmadan tüm güvenlik-geçitlerini
yeniden oynar. Bu testler CLI'nın gerçekten-korunan-şeyi-koruduğunu kanıtlar:
 - geçerli-akışlar PASS dönmeli
 - kasıtlı-bozulan-geçitler FAIL dönmeli ( regression-koruma)
"""

import json
import os
import subprocess
import sys

from pacta.cli import run_verify

# Repo-kökü: tests/ → bir-üst-dizin. subprocess'in pacta'yı-bulması-için
# cwd+PYTHONPATH açıkça-ayarlanır ( başka-testlerin-os.chdir'undan etkilenmemesi
# için dayanıklı olmalıdır).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.run([sys.executable, "-m", "pacta.cli", *args],
                       capture_output=True, text=True, timeout=120,
                       cwd=REPO_ROOT, env=env)
    return p


def test_verify_all_green_happy():
    """Tüm-geçitler-sağlamken verify → PASS + exit-0."""
    rc = run_verify(json_output=True)
    assert rc == 0


def test_verify_json_shape():
    """--json makine-okunabilir-yapı."""
    p = _run_cli("verify", "--json")
    assert p.returncode == 0, p.stderr
    d = json.loads(p.stdout)
    assert d["verdict"] == "PASS"
    assert d["passed"] == d["total"]
    assert len(d["checks"]) >= 7
    for c in d["checks"]:
        assert set(c.keys()) == {"check", "result", "detail"}
        assert c["result"] == "PASS"


def test_verify_human_output_has_verdict():
    """İnsan-okunabilir-mod SONUÇ-satırı-içerir."""
    p = _run_cli("verify")
    assert p.returncode == 0
    assert "SONUÇ" in p.stdout
    assert "PASS" in p.stdout


def test_verify_detects_broken_gate(monkeypatch):
    """Regression-koruması: rol-kapısı-kapatılırsa verify FAIL-dönmeli.

    verify'in-değeri, bozulan-geçitleri yakalayabilmesindedir. Rol-kapısını
    atlayan ( stranger'ı-buyer'a-rewrite-ederek) bir vault enjekte ederiz;
    verify bağımsız-olduğu için role_gate_stranger_rejected FAIL-vermeli ve
    genel-verdict FAIL'e-dönmelidir.
    """
    import pacta.cli as cli_mod
    from pacta.core.vault import PactaEscrowVault

    class GateDisabledVault(PactaEscrowVault):
        def settle_escrow(self, job_id, caller_address=None):
            job = self.jobs[job_id]
            if caller_address is not None and caller_address not in (
                    job.buyer_address, job.seller_address):
                caller_address = job.buyer_address  # gate-bypassed
            return super().settle_escrow(job_id, caller_address)

    monkeypatch.setattr(cli_mod, "PactaEscrowVault", GateDisabledVault)
    rc = run_verify(json_output=True)
    assert rc == 1, "rol-kapısı-kapatıldı-AMA-verify-PASS-döndü ( yakalamadı!)"

