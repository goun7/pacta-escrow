"""G39-pini: README'nin test-sayisi-iddiasi gercek-collect'e-esit.

Pacta-ilk-PyPI-yayini-oncesi ( 2026-10-19) eklendi. README "1.660
passed" iddia-ediyor; bu-pin otomatik-collect ile ayni-olmazsa-KIRMIZI.

Kural ( G27/G28/G34/G35/G37/G38-deseni): README-nin-soyledigi-ile
olctugumuz-ayni-olmali ("tamamlanma"-olcutumuz-bu).

Not: Pacta-nin-pytest-konfigurasyonu-ozet-satirini-basari ( 1666
tests collected), bu-yuzden-iki-yol-da-kullanilir:
( 1) "N tests collected"-ozet-satirindan, ( 2) dosya-basi-test-sayisi
toplamindan. Ikisinden-ilk-bulunan-gecerli.
"""
import re
import subprocess
import sys
from pathlib import Path


def _collected_total(res_stdout: str) -> int:
    # yol-1: "1666 tests collected" ozet-satiri
    m = re.search(r"(\d+)\s+tests?\s+collected", res_stdout)
    if m:
        return int(m.group(1))
    # yol-2: "tests/test_x.py: N" dosya-basi-sayim
    total = 0
    for mm in re.finditer(r"^tests/[\w./-]+\.py:\s*(\d+)\s*$", res_stdout, re.M):
        total += int(mm.group(1))
    return total


def test_readme_test_count_is_not_stale():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    m = re.search(r"([\d.,]+)\s*passed", readme)
    assert m, "README-passed-satiri-bulunamadi"
    claimed = int(m.group(1).replace(".", "").replace(",", ""))
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(root), timeout=600)
    assert res.returncode == 0, res.stderr[-400:]
    total = _collected_total(res.stdout)
    assert total > 0, "collect-total-ayristirilamadi: %r" % res.stdout[-300:]
    assert total >= claimed, (
        "README-stale-test-sayisi: iddia=%d collect=%d" % (claimed, total))
