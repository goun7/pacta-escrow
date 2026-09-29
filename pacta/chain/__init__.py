"""
Pacta Chain Integration ( AT-194).

Dürüst-sınır-kapanışı: README'nin "zincir-değil-simülasyon" sınırı. Pacta artık
bir-EVM-zinciri-erişilebilir-olduğunda **gerçek-zincir-bağı** ( chain-anchoring)
üretir — gerçek-transaction, gerçek-receipt, gerçek-block. Zincir-yoksa-dürüst-
hata-verir ( sessiz-simülasyon-yerine).

İki-arka-uç:
  * ``connect_anvil()``     — üretim-yolu: anvil veya herhangi-bir-EVM-JSON-RPC
                              ( ``PACTA_RPC_URL``-ile-verilir; anvil-varsayılanı
                              http://127.0.0.1:8545).
  * ``connect_in_memory_evm()`` — gerçek-py-evm ( EthereumTesterProvider);
                              sıfır-kurulumlu-gerçek-zincir-test-yolu.

Para-harcama-YOK: bağ 0-wei-value-transferidir ( yalnız-gas, önceden-finanse-
edilmiş-hesaptan). Fon-akışı-hâlâ-ledger'dadır; zincir-bağı **kararın-
taahhüdünü** sabitler.
"""

from pacta.chain.adapter import (
    ChainUnavailableError,
    ChainProbeError,
    EvmChainAdapter,
    connect_anvil,
    connect_in_memory_evm,
    probe_rpc,
    ANVIL_DEFAULT_RPC_URL,
)

__all__ = [
    "ChainUnavailableError",
    "ChainProbeError",
    "EvmChainAdapter",
    "connect_anvil",
    "connect_in_memory_evm",
    "probe_rpc",
    "ANVIL_DEFAULT_RPC_URL",
]
