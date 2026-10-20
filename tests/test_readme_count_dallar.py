"""G39/G42-pini: README'nin test-sayisi-iddiasi gercek-kosumla-ayni.

Pacta-ilk-PyPI-yayini-oncesi ( 2026-10-19) eklendi; G44-MCP-serveri
( 2026-10-20) ile birlikte gercek-passed-sayisina-strict-hale-getirildi.

Kural ( G27/G28/G34/G35/G37/G38/G42-deseni): README-nin-soyledigi-ile
olctugumuz-ayni-olmali ("tamamlanma"-olcutumuz-bu).

Olculen-deger: `pytest tests/ -q` ozet-satirindan "N passed". README-de
ayni-N-yazmali ( pin-kendisi-pass-edince-N-artar; eklenen-her-test-icin
README-guncellenmeli-yoksa-pin-KIRMIZI-olur).
"""
import re
import subprocess
import sys
from pathlib import Path


def test_readme_test_count_is_not_stale():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    m = re.search(r"([\d.,]+)\s*passed", readme)
    assert m, "README-passed-satiri-bulunamadi"
    claimed = int(m.group(1).replace(".", "").replace(",", ""))
    # pin-kendisini-disarida-birak ( sonsuz-oyyinelemeyi-onle)
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q",
         "--ignore=%s" % str(Path(__file__).relative_to(root)),
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(root), timeout=1800)
    pm = re.search(r"(\d+)\s+passed", res.stdout)
    assert pm, "ozet-satiri-ayristirilamadi: %r" % res.stdout[-300:]
    total = int(pm.group(1))
    assert total > 0, "passed-total-sifir: %r" % res.stdout[-300:]
    assert total == claimed, (
        "README-stale-test-sayisi: iddia=%d olculen=%d" % (claimed, total))
