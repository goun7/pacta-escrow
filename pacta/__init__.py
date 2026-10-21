"""
Pacta — x402 / AP2 Machine-Customer Escrow & Autonomous Arbitration Rail
Enterprise Sovereign Edition (2026.1)
"""

# Surum-artik TEK-KAYNAKLI: pyproject.toml tek-gercegi. Onceden burada-da
# ayri "2026.1.0" vardi ( cift-kaynak). Asagidaki desen OncE-kaynak-agacindaki
# pyproject.toml'i-okur; YOKSA-importlib.metadata'ye-duser ( kurulu-paket).
# Neden-importlib-degil-oncelikli: kaynak-gelistirme-modunda metadata
# site-packages'taki-ESKI-kurulu-surumu-bulur ( yanlis-deger).
# Dikkat: pacta src-layout-DEGILDIR ( pacta/pacta/), bu yuzden parents[1].
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _kaynak_surumu():
    """Kaynak-agacindaki-pyproject.toml'den-version-okur ( yoksa-None)."""
    if not _PYPROJECT.exists():
        return None
    for ln in _PYPROJECT.read_text(encoding="utf-8").splitlines():
        if ln.startswith("version ="):
            return ln.split('"')[1]
    return None


_kaynak = _kaynak_surumu()
if _kaynak is not None:
    __version__ = _kaynak
else:  # kurlu-paket ( site-packages) - pyproject-agacta-yok
    from importlib.metadata import PackageNotFoundError, version as _dist_version

    try:
        __version__ = _dist_version("pacta-escrow")
    except PackageNotFoundError:
        __version__ = "0.0.0-dev"

__author__ = "Pacta Core Team"

from pacta.models import (
    EscrowStatus,
    VerificationTier,
    EscrowPolicy,
    EscrowJob,
    TamgaExecutionReceipt,
    ZkTLSCertificate,
    DisputeClaim,
    ArbitrationOutcome,
)
from pacta.client import PactaEscrowClient
from pacta.core.vault import PactaEscrowVault

__all__ = [
    "__version__",
    "EscrowStatus",
    "VerificationTier",
    "EscrowPolicy",
    "EscrowJob",
    "TamgaExecutionReceipt",
    "ZkTLSCertificate",
    "DisputeClaim",
    "ArbitrationOutcome",
    "PactaEscrowClient",
    "PactaEscrowVault",
]
