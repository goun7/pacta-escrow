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
Bu ayrım bilinçlidir — ama ayrım, iki katmanı **birbirine bağlamamayı** değil,
her katmanın tek bir iş yapmasını gerektirir: aşağıdaki D5-köprüsü settlement
kararlarını kanıt katmanına sabitler ( her iki taraf da kendi işini yapar).

## 🔗 Tamga D5 köprüsü — verified delivery ( RFC-010)

> **Mesh deseni:** `Escrow FSM — No Verified Delivery`. Pacta'nın FSM'i fon
> akışını korur, ama kararlar saf-bellekte dururdu ( restart-kaybeder).
> Köprü, settlement kararını bir **D5 hash-chain**'e sabitler:

```python
from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import D5Ledger, SettlementBinder

v = PactaEscrowVault(d5_ledger=D5Ledger("./ledger.jsonl"))
job, tx = v.settle_escrow(job.job_id, caller_address=buyer)   # → charge yazıldı

# alıcı ( non-custodial: anahtar vault'ta DEĞİL) claim'imzalar
claim = SettlementBinder.build_claim(job, job.settlement_binding["delivery_hash"],
                                     payer_signer=buyer_key)
verdict = SettlementBinder.verify_binding(job.settlement_binding["charge"], claim)
# → {"verdict": "GREEN", "reason_code": 0, "checks": {1..5: True}}
```

Beş-kontrol ( RFC-010 §3; fail-closed — biri-RED → tümü-RED):

| # | Kontrol | Kırmızı-gerekçesi |
|---|---|---|
| 1 | receipt-verifies: D5-üçlüsü ( seq/prev/h) + `delivery_hash` | `receipt_invalid` |
| 2 | claim-verifies: imza `buyerAddress`'e çözümlenir ( x402/v1) | `claim_signature_invalid` |
| 3 | `settlementRef` == `bind.payment_id` | `settlement_ref_mismatch` |
| 4 | claim-tarafları == escrow-tarafları | `party_mismatch` |
| 5 | `evidenceHash` == `delivery_hash` ( bayt-eşit) | `evidence_hash_mismatch` |

**Çapraz-doğrulama kanıtlandı:** Pacta'nın ürettiği charge + imzalı claim,
Tamga'nın **kendi** `tools/settlement_bind_verify.py` gate'inde GREEN rc=0
verir; Pacta'nın `ledger.jsonl`'i Tamga'nın `tamga_runner.py ledger-verify`'ında
sağlam çıkar ( `tests/test_tamga_d5_bridge.py`).

## 💸 Unpump odeme kanıtı — ödeme → escrow → D5 ( 24-ajan-borsasi)

> **Mesh deseni:** `External Payment — No Escrow Link`. Unpump'un borsası bir
> ödeme kanıtı üretir ( `borsa_core.Match.work_done` + `receipt_hash`,
> `kanit_cekirdegi`'nin Delilix SHA-256 zincirinden) — ama o kanıt Unpump'un
> kendi zincirinde kalır ve Pacta'nın escrow kararına **bağlı değildir**.
> Köprü iki kanıtı çapraz-uzlaştırır ve ortak sonucu D5'e sabitler:

```python
from pacta.core.vault import PactaEscrowVault
from pacta.integrations.tamga_d5 import D5Ledger
from pacta.integrations.unpump_bridge import UnpumpPaymentBridge, UnpumpPaymentProof

# 1) ödeme: Unpump'ta iş bitti — receipt_hash kanıt zincirinden gelir
proof = UnpumpPaymentProof.from_match(match, buyer_id=bid.buyer_id,
                                      kanit_entry=tamga,       # {id, h, prev}
                                      kanit_operation=islem.kanonik())  # 6-alan

# 2) escrow settlement + 3) D5 kanıtı: uzlaşırsa yanına bir charge yazar
v = PactaEscrowVault(d5_ledger=D5Ledger("./ledger.jsonl"))
job, tx = v.settle_escrow(job.job_id, caller_address=buyer)
b = UnpumpPaymentBridge.bind_unpump_payment(proof, job, v.d5_ledger,
                                            payer_signer=buyer_key)
# → charge = RFC-010 üstküsesi ( additive unpump bloğu) + alıcı-imzalı claim

verdict = UnpumpPaymentBridge.verify_binding(b.charge, b.claim)
# → {"verdict": "GREEN", "checks": {1..5 RFC-010 ∪ 6/7/8 unpump: True}}
```

RFC-010'ın beşinin üzerine üç ek kontrol ( fail-closed — biri-RED → tümü-RED):

| # | Kontrol | Kırmızı-gerekçesi |
|---|---|---|
| 1–5 | RFC-010 beş-kontrol ( yukarıda) | `receipt_invalid` … `evidence_hash_mismatch` |
| 6 | unpump-proof: `unpump` bloğu + `work_done` + `unpump_ref` uyumu | `unpump_proof_missing` |
| 7 | receipt bağımsız yeniden-üretilebilir ( Unpump'un **kendi** `content_hash`'i) | `receipt_hash_mismatch` |
| 8 | kanıtın tutar/tarafları == escrow kaydının tutar/tarafları | `escrow_reconcile_mismatch` |

**Üç-yönlü çapraz-test kanıtlandı:** üretilen charge, RFC-010 beşini geçen bir
üstkümedir ( additive — şema değişikliği yok), bu yüzden Tamga'nın **kendi**
gate'inde GREEN rc=0 verir; Unpump'un kanıt zinciri `kanit_cekirdegi`'yle
bağımsız teyit edilir ( `tests/test_unpump_bridge.py`). Unpump checkout'u
erişilebilir olduğunda ( `UNPUMP_ROOT` env veya komşu dizin) köprü onun
`borsa_core` + `kanit_cekirdegi`'yle gerçek çalışır; değilse receipt'in Delilix
hash'i hesaplanamadığı için **İNDETERMİNE** döner — gizlice "geçti" denmez.

## Kurulum

```bash
cd pacta
pip install -e .                    # pydantic-v2 + eth-account
PYTHONPATH=. python3 -m pacta.cli demo   # 3-senaryo-demo'su
```

## ⏱️ In 30 seconds ( hızlı-bakış)

```bash
# 1) Bağımsız-doğrulama — 7-güvenlik-geçidini sıfırdan-oynar ( kanıt-entegrasyonu)
PYTHONPATH=. python3 -m pacta.cli verify            # → SONUÇ: PASS — 7/7

# 2) Makine-okunabilir-çıktı ( CI/entegrasyon-için)
PYTHONPATH=. python3 -m pacta.cli verify --json     # → {"verdict":"PASS",...}

# 3) Demo — 3-gerçek-senaryo ( DvP / bozuk-çıktı-iadesi / Schelling-hakemlik)
PYTHONPATH=. python3 -m pacta.cli demo

# 4) Sağlık
PYTHONPATH=. python3 -m pacta.cli status            # → 100% SOLVENT
```

> `verify` çıkış-kodu: **0** = tüm-geçitler-sağlam, **1** = en-az-bir-bozuk.
> Kontroller: `dvp_happy_path`, `refund_on_failed_verification`,
> `schelling_arbitration_slashing`, `idempotency_no_double_lock`,
> `role_gate_stranger_rejected`, `fsm_terminal_state_guard`,
> `solvency_invariant`.

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
PYTHONPATH=. python3 -m pytest tests/ -q    # 1.113-passed (+5-skipped; onchain-anvil)
```

2026-10-13 LEED-ölçümü: 1.113 passed / 0 failed rc=0. Bu sayı, bu repodaki
`tests/`-suitinin tamamıdır; `test_unpump_bridge.py`'nin Tamga-gate
çapraz-testleri dahil ( `TamgaProtocol/tools/settlement_bind_verify.py`
üzerinden üçüncü-proje-doğrulaması — bkz. §Tamga D5 köprüsü).

## Sınırlar ( dürüst)

- **Saf-bellek**: jobs/ledger/revenue `dict`-içinde; restart-kaybeder
  ( mimari-sınır — kalıcı-kanıt-katmanı tamga D5'tir; AT-177-kaydı).
  **Kapanış-yolu:** `PactaEscrowVault(d5_ledger=D5Ledger(...))` settlement
  kararlarını D5 hash-chain'ine sabitler ( yukarıdaki §Tamga D5 köprüsü);
  kararların-kanıtı restart'tan-sonra-da-bağımsız-doğrulanabilir.
- Adresler **EVM-benzeri-ama-gerçek-zincir-değil** ( simülasyon)

## Akademik & teknik temel

- **Escrow as conditional payment** — klasik koşullu ödeme deseni:
  alıcı fonları kilitler, sağlayıcı çıktı sunar, doğrulama geçerse
  fonlar serbest kalır. Pacta bu deseni ajanlar arası SLA sözleşmeleri
  için uygular (`create_and_lock_escrow` → `submit_output` → `verify`).
- **Arbitration / dispute resolution** — `raise_dispute` →
  `resolve_arbitration` akışı: kalite/SLA anlaşmazlıklarında tarafsız
  karar mekanizması. x402 ekosistemindeki paralel tartışma:
  [x402 #2887](https://github.com/x402-foundation/x402/issues/2887)
  "Correctness/dispute layer downstream of settlement" — ödeme
  başarılı olsa bile teslimat başarısız olabilir.
- **Mesh içindeki rolü**: Pacta fon akışını korur; **kanıt katmanı
  değildir** — kanıt [TamgaProtocol](../../05_acik_kaynak/TamgaProtocol)
  (hash-chain anchor, [x402 #2332](https://github.com/x402-foundation/x402/issues/2332)).
  **Köprü ( 2026-10-05):** `pacta/integrations/tamga_d5.py`, settlement
  kararlarını Tamga D5-ledger'ına RFC-010 cross-artifact binding ile sabitler —
  Tamga'nın kendi gate'i ile doğrulanır ( yukarıdaki bölüm). **Ödeme-makbuz
  katmanı** [63-Sester](../63-Sester).
  Bu ayrım bilinçlidir: her katman tek bir işi yapar.

## Akademik Kaynaklar (2024-2026)

Bu çalışma aşağıdaki araştırmaya dayanır (her referans canlı
doğrulanmıştır: arXiv abs sayfaları HTTP-200 + DOI çözümlemesi 200):

- **[1] Anlaşmazlık-çözüm protokolü (dispute resolution protocol)** —
  *BoLD: Fast and Cheap Dispute Resolution* — Alvarez et al., arXiv 2024.
  Arbitrum için gecikme-saldırılarına-dirençli, stake-maliyeti düşürülmüş
  yeni bir anlaşmazlık-çözüm protokolü. Pacta'nın `raise_dispute` →
  `resolve_arbitration` akışına ve hakemlik için bond/stake ekonomisine
  doğrudan paraleldir (§5.3 quorum + %20-bond).
  [arXiv:2404.10491](https://arxiv.org/abs/2404.10491)

- **[2] Kripto-ekonomik teşvik-tasarımı (challenge-based protocols)** —
  *(Im)possibility of Incentive Design for Challenge-based Blockchain Protocols*
  — Lee, Nguyen & Lee, arXiv 2025.
  Truebit / optimistic-rollup gibi challenge-tabanlı protollerde "dürüst
  itirazcının zarar-etmemesi" ile "dolandırıcılığın caydırılması" hedeflerinin
  birlikte ne zaman sağlanabileceğini (tek-kazananlı: imkansız/limitli;
  çok-kazananlı: açık koşullar) kanıtlar. Pacta'nın quadratic-slashing
  tasarımı için temel teşvik-modeli.
  [arXiv:2512.20864](https://arxiv.org/abs/2512.20864)

- **[3] Anlaşmazlık-oyunu ekonomisi (dispute-game exploitation)** —
  *Hollow Victory: How Malicious Proposers Exploit Validator Incentives in
  Optimistic Rollup Dispute Games* — Lee, arXiv 2025 (WTSC 2025).
  Dispute-game'lerinde kazanan itirazcıya yeterli ödül-aktarılmaması gibi
  yapısal bir güvenlik-açığı; önerilen countermeasure'lar arasında
  **escrowed reward mechanism** ve commit-reveal de var. Pacta'nın
  slashing-dağıtımının itirazcı-teşviki açısından denetlenmesi gerekir.
  [arXiv:2504.05094](https://arxiv.org/abs/2504.05094)

- **[4] Emanet-tabanlı uzlaşma (bonded settlement + arbitration)** —
  *Bonded Recourse for Smart-Contract Settlement of Compensable Agent Side
  Effects* — Bindschaedler, Botha & Siebenbrunner, arXiv 2026 (BCCA 2026).
  Ajan eylemlerini scope/recovery/evidence/payout/**collateral**'a bağlayan
  bir smart-contract settlement protokolü; objektif iddialar
  **optimistic-oracle challenge** ile, sübjektifler ERC-792 hakemliğine
  yönlendirilir. Pacta'nın `create_and_lock_escrow` (emanet) +
  `raise_dispute` (challenge/arbitration) ayrımına çok yakın bir mimari.
  [arXiv:2609.01939](https://arxiv.org/abs/2609.01939)

- **[5] İyimser uzlaşma + itiraz-tabanlı hakemlik (optimistic settlement)** —
  *SettleFL: Trustless and Scalable Reward Settlement Protocol for Federated
  Learning on Permissionless Blockchains* — Liang et al., arXiv 2026.
  Trustless settlement için iki yapı: **Commit-and-Challenge** (optimistic
  çalıştırma + itiraz-tetikli hakemlik) ve Commit-with-Proof (anında finalite).
  Pacta'nın `submit_output` → `verify` → `settle_escrow` iyimser-yoluna ve
  itiraz-dağıtımına karşılıktır.
  [arXiv:2602.23167](https://arxiv.org/abs/2602.23167)

- **[6] İyimser mekanizma oyun-teorisi (announcement/challenge games)** —
  *Games in Public Announcement: How to Reduce System Losses in Optimistic
  Blockchain Mechanisms* — Liu & Zeng, arXiv 2024.
  Duyuru-oyunlarının (announcer vs validator-challenger) tüm Nash-dengelerini
  ve sistem-zararını çıkarır, ödül/çaba parametrelerinin dengeye etkisini
  analiz eder. Pacta'nın hakem-ödülleme ve SLA-eşiği parametreleri için
  denge-tabanlı bir kalibrasyon çerçevesi.
  [arXiv:2407.21413](https://arxiv.org/abs/2407.21413)

- **[7] Çevrimiçi anlaşmazlık-çözümü + zincir-üstü emanet (ODR + escrow)** —
  *Designing Inclusive Crypto-Asset Dispute Resolution: A Hybrid AI and Smart
  Contract Online Dispute Resolution Framework for Vulnerable Users* —
  Arnone & Giacalone, arXiv 2026.
  Hibrit ODR modeli: zincir-dışı AI sınıflandırma/kanıt-düzenleme +
  zincir-üstü **anlaşmazlık-kaydı, timestamping, doğrulama, escrow yönetimi**
  ve sonuç-icrası. Pacta'nın fon-akışı-koruma rolünün (kanıt katmanı değil)
  hukuki/ODR perspektifinden yansıması.
  [arXiv:2608.14356](https://arxiv.org/abs/2608.14356)

- **[8] Merkeziyetsiz hakemlik altyapısı (arbitration infrastructure)** —
  *Bitcoin Smart Accounts: Trust-Minimized Native Bitcoin DeFi Infrastructure*
  — Lalor, Marshall & Russo, arXiv 2026.
  Self-custody'yi koruyan trust-minimized altyapıda **TEE-tabanli hakemlik
  sistemi** ile honest-majority (m-of-n) varsayımını existential-honesty
  (1-of-k)'e indirme. Pacta'nın "bağımsız-doğrulanabilir" hedefi için
  güven-varsayımını-azaltan bir hakemlik-alternatifi.
  [arXiv:2603.26293](https://arxiv.org/abs/2603.26293)

- **[9] Ajan-ekonomisi altyapısında sistematikleşme (escrow → verification →
  settlement)** —
  *SoK: Decentralized Agent Economic Infrastructure* — Sun, Xiong, Wang, Gao,
  Li, Cheng, Sun & Wang, arXiv 2026.
  Ajan görevlerinin tam yaşam-döngüsü için 17 özellik ailesi / 6 aşama
  tanımlar; "doğru bir escrow, teslim edilen işin görevi karşıladığına dair
  kanıt sunmayan bir onayla ödemeyi serbest bırakabilir" türü arızaları
  sınıflandırır ve **guarantee closure** (bir aşamada kurulmuş garantilerin
  sonraki kararları nasıl kısıtladığı) ölçütünü tanıtır. Pacta'nın
  `submit_output` → `verify` → `settle_escrow` akışının ve
  kanıt-öncelikli tasarımının haritalandığı çerçeve.
  [arXiv:2610.01756](https://arxiv.org/abs/2610.01756)

- **[10] AP2 ödeme protokolünde imza-kararı bağlama (intent binding)** —
  *Signing the Transaction but Not the Decision: Whisper Attacks and a
  Binding Defense for AP2* — Louck, Dvir & Stulman, arXiv 2026.
  AP2 gibi ajan-ödeme protokolleri kriptografik olarak geçerli imzalar üretir
  ama kararı kısıtlamaz: "whisper" saldırıları alışveriş ajanını her protokol
  kontrolünü geçen ama kullanıcının isteğine uymayan sepetler kurmaya
  yönlendirebilir. Savunma olarak önerilen A-VIP, imzalı niyeti bir
  yetki-tahsisi (capability grant) olarak bağlar. Pacta'nın AP2/x402
  machine-customer rayında niyet-farkının gözetlenmesi için doğrudan uyarlanan
  saldırı/savunma analizi.
  [arXiv:2609.11757](https://arxiv.org/abs/2609.11757)

- **[11] Ajan ekonomisi için özel execution + settlement katmanı** —
  *AGNT2: Autonomous Agent Economies on Interaction-Optimized Layer 2
  Infrastructure* — Ruan & Zhang, arXiv 2026.
  İnsan-finansal işlemler için optimize edilmiş L2'lerin aksine ajan
  etkileşimlerini (kimlik, **escrow**, bağımlılık sıralaması, oturum-durumu)
  birinci-sınıf protokol nesneleri yapar; computational fraud-proof'larla
  settlement katmanını herhangi bir EVM L1'e bağlar. Pacta'nın
  onchain settlement katmanının (escrow + challenge) ölçeklendirme
  konumlandırması için sistem-mimarisi referansı.
  [arXiv:2604.21129](https://arxiv.org/abs/2604.21129)

- **[12] HTTP 402 settlement protokolü interoperabilitesi** —
  *Agent-OSI: An Interoperability Architecture for Communication and
  Settlement in the Decentralized Internet of Agents* — Xu, Wang, Xia, Zhang
  & Liew, arXiv 2026.
  HTTP 402'yi bir application-layer challenge-response ilkel olarak ele alır;
  settlement arka ucu (**escrow sözleşmesi**, ödeme kanalı veya zincir-dışı
  makbuz) takılabilir bir seçimdir. Pacta'nın x402/AP2 rayının "arka uç
  olarak escrow" tasarımıyla birebir örtüşen, standart-katmanı Referansı.
  [arXiv:2602.13795](https://arxiv.org/abs/2602.13795)

- **[13] Ajan eylemlerinde settlement denetimi (order/progress/replay)** —
  *Auditing Action Settlement in LLM Agent Environments: Order, Progress, and
  Replay* — Chen, Ye, Zhang & Yu, arXiv 2026.
  Eş-zamanlı ajan eylemleri için tipli snapshot-settlement sözleşmesi; sıra
  duyarlılığı, yararlı ilerleme ve yeniden-oynatma (replay) tutarlılığını
  denetler; tam-durum günlüğü 156 kontrol noktasını birebir yeniden oynatır ve
  1.332 bozma denemesini reddeder. Pacta'nın deterministic
  finite-state-machine (FSM) vault'u ve hash-chained evidence ledger'i için
  denetlenebilirlik metodolojisi.
  [arXiv:2610.01138](https://arxiv.org/abs/2610.01138)

- **[14] Ajan ticaretinde clearing (doğrulama → settlement arası boşluk)** —
  *RAILS: Verification-Native Clearing For Agentic Commerce* — de
  Valois-Franklin & Bogdan, arXiv 2026.
  "Ödeme clearing değildir; escrow clearing kararlarını tüketir" teziyle
  ajan ticaretinde eksik primitif olarak clearing'i tanımlar; yedi primitif
  (Obligation Object, Evidence Envelope, Verification Mesh, Clearing Decision,
  Settlement Instruction, Clearing Passport, Finality Rules) ve
  admissibility-graded doğrulama modeliyle "finansal olarak anlamlı hiçbir
  settlement, yükümlülüğün kabul edilebilirlik tabanının altındaki kanıtla
  desteklenmez" özelliğini formülleştirir. Pacta'nın
  escrow-öncesi-verify edilmiş (verify-before-settle) akışının teorik
  karşılığı.
  [arXiv:2606.08790](https://arxiv.org/abs/2606.08790)
