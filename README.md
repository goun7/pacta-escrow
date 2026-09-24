# Pacta — Escrow FSM + Schelling Arbitration

Pacta, TAMGA-MESH'in **anlaşmazlık çözüm** protokolüdür: emanet (escrow)
fon yönetimi + oyun-teorik hakemlik. Saf-Python, bağımsız-doğrulanabilir.

## Rolü (mesh-içinde)

```
alıcı (buyer) → create_and_lock_escrow → [para-kilitlenir]
                                    ↓
                        submit_output → verify → settle_escrow (satıcı-öder)
                ↘ raise_dispute (kalite/SLA) → Schelling-arbitration
                                    ↓
                    resolve_arbitration → slashing / refund
```

Pacta **kanıt katmanı değildir** — kanıt tamga D5-ledger'dadır (RFC-010 §6).
Pacta, **fon akışını** korur: kimin ne zaman ödediği, kimin iade ettiği.

## Kurulum

```bash
cd pacta
pip install -e .                    # pydantic-v2 + eth-account
PYTHONPATH=. python3 -m pacta.cli demo   # 3-senaryo-demo'su
```

## Temel-API

```python
from pacta.core.vault import PactaEscrowVault, EscrowPolicy

v = PactaEscrowVault()
job = v.create_and_lock_escrow(
    buyer_address="0x…40hex…",
    seller_address="0x…40hex…",
    amount_usdc=100.0,
    idempotency_key="payment-req-1",     # AT-184: çift-deposit-korunması
)
v.submit_output(job.job_id, {"report": "…"})
v.settle_escrow(job.job_id, caller_address=buyer)  # rol-kapısı (AT-180/184)
```

## Güvenlik-modeli ( AT-165..184)

| Özellik | Uygulama |
|---|---|
| Adres-doğrulama | KATI-hex: `0x`-önek + ≥2-hex (AT-169; `0xZZ`-RED) |
| job_id-çarpışma | `job_id_collision`-RED; mevcut-job-korunur (AT-182) |
| Idempotency | aynı-anahtar → mevcut-job (çift-fon-hareketi-YOK) (AT-184) |
| Rol-kapısı | `caller_address`-buyer/seller-dışı → RED (AT-166/180) |
| Zorunlu-rol | `PACTA_REQUIRE_CALLER_ROLE=1` → None-caller-RED (AT-184) |
| FSM-terminal | SETTLED/SLASHED-sonrası → InvalidStateTransitionError (AT-171) |
| SLA-aşımı | settle-kapısında-reddeder, refund_timeout'a-yönlendirir (AT-165) |
| Schelling | 7-üye-quorum + %20-bond + quadratic-slashing (§5.3) |

## Test

```bash
PYTHONPATH=. python3 -m pytest tests/ -q    # 53-passed
```

## Sınırlar ( dürüst)

- **Saf-bellek**: jobs/ledger/revenue `dict`-içinde; restart-kaybeder
  ( mimari-sınır — kalıcı-kanıt-katmanı tamga D5'tir; AT-177-kaydı)
- Adresler **EVM-benzeri-ama-gerçek-zincir-değil** ( simülasyon)
