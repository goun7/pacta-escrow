"""G39/G42-pini: README'nin test-sayisi-iddiasi gercek-kosumla-ayni.

Pacta-ilk-PyPI-yayini-oncesi ( 2026-10-19) eklendi; G44-MCP-serveri
( 2026-10-20) ile birlikte gercek-passed-sayisina-strict-hale-getirildi.

Kural ( G27/G28/G34/G35/G37/G38/G42-deseni): README-nin-soyledigi-ile
olctugumuz-ayni-olmali ("tamamlanma"-olcutumuz-bu).

Olculen-deger: `pytest tests/ -q` ozet-satirindan "N passed". README-de
ayni-N-yazmali ( pin-kendisi-pass-edince-N-artar; eklenen-her-test-icin
README-guncellenmeli-yoksa-pin-KIRMIZI-olur).

G42B-uyumu ( 2026-10-20): toplam-sayi ORTAMA-GORE-DEGISIR. anvil
(Yerel-foundry) ayakta-ise 5-onchain-testi-ekstra-kosar ( CI-de-olumlu-
bulunamayacagi-icin-skip). README-de-CI-temel-sayisi-yazilidir; pin
anvil-ekstrasini-olcavarak-cikartir-VE-ekstra-testlerin-de-gercekte-
gecitigini-kanitlar ( yerelde-anvil-ile).
"""
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

_ANVIL_HOST = "127.0.0.1"
_ANVIL_PORT = int(os.environ.get("PACTA_ANVIL_PORT", "8545"))
_ONCHAIN_MOD = "tests/test_onchain_anvil.py"


def _anvil_ayakta() -> bool:
    try:
        with socket.create_connection(
                (_ANVIL_HOST, _ANVIL_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def test_readme_test_count_is_not_stale():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    m = re.search(r"([\d.,]+)\s*passed", readme)
    assert m, "README-passed-satiri-bulunamadi"
    claimed = int(m.group(1).replace(".", "").replace(",", ""))
    # pin-kendisini-disarida-birak ( sonsuz-oyyinelemeyi-onle)
    # G48-2026-10-22: kardes-checkout'lar-gelistirme-makinesinde-var-ama-CI'da
    # YOK -> mesh-cross-testler-lokalde-PASS-CI'da-SKIP -> sayi-makineye-bagli
    # oldugu-icin-pin-yanlis-KIRMIZI-veriyordu. Cozum: alt-surecteki-sayimdan
    # kardes-checkout-bagimli-iki-dosyayi-cikart ( README-de-CI-temeli-yazilir).
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q",
         "--ignore=%s" % str(Path(__file__).relative_to(root)),
         "--ignore=tests/test_tamga_d5_bridge.py",
         "--ignore=tests/test_unpump_bridge.py",
         "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=str(root), timeout=1800)
    pm = re.search(r"(\d+)\s+passed", res.stdout)
    assert pm, "ozet-satiri-ayristirilamadi: %r" % res.stdout[-300:]
    total = int(pm.group(1))
    assert total > 0, "passed-total-sifir: %r" % res.stdout[-300:]

    # G42B: anvil-ayakta-ise-5-ekstra-onchain-testi-kosar. Bu-testler-yalnizca
    # CI-de-bulunamayan-YEREL-bir-hizmete-baglidir; README-de-CI-temeli
    # yazilidir ( 0-ekstra). Yerelde-anvil-varsa-ekstrayi-cikart-VE-ayni-
    # zamanda-o-testlerin-GEEKTEN-gectigini-kanitla ( yalnizca-saymak-da-ilgic).
    extra_onchain = 0
    if _anvil_ayakta():
        r_oc = subprocess.run(
            [sys.executable, "-m", "pytest", _ONCHAIN_MOD, "-q",
             "-p", "no:cacheprovider"],
            capture_output=True, text=True, cwd=str(root), timeout=1800)
        m_oc = re.search(r"(\d+)\s+passed", r_oc.stdout)
        assert m_oc, "onchain-ozeti-ayristirilamadi: %r" % r_oc.stdout[-300:]
        extra_onchain = int(m_oc.group(1))
        assert r_oc.returncode == 0, (
            "anvil-ayakta-AMA-onchain-testler-KIRMIZI: %s"
            % r_oc.stdout[-400:])
    ci_eslenk = total - extra_onchain
    assert ci_eslenk == claimed, (
        "README-stale-test-sayisi: iddia=%d olculen(CI-esleni)=%d "
        "(toplam=%d, anvil-ekstra=%d)"
        % (claimed, ci_eslenk, total, extra_onchain))
