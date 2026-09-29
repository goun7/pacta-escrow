# PACTA — Akademik Araştırma Dizini (2025–2026, DOĞRULANMIŞ)

> **Tarih:** 2026-09-29
> **Yöntem:** arXiv API (export.arxiv.org) ile tarama + her başvuru `web_fetch`
> ile **bireyden-doğrulandı (HTTP 200 + başlık + özet)**.
> **UYDURMA YOK.** Aşağıdaki her makale gerçek ve erişilebilir.

## Alan

PACTA = **emanet (escrow) FSM + Schelling hakemlik**, x402/AP2 tabanlı
makine-müşteri (machine-customer) ticareti için. İlgili akademik alanlar:
ajan ekonomisi, zincirler-arası güven, kripto-ekonomik tahkim,
makineden-makineye ödeme.

---

## DOĞRULANAN MAKALELER (fetch ile teyit edildi)

### 1. The Agent Economy: A Blockchain-Based Foundation for Autonomous AI Agents
- **Kaynak:** https://arxiv.org/abs/2602.14219 (HTTP 200 ✓)
- **Tarih:** 2026-02-15 | **Yazar:** Minghui Xu | **Alan:** cs.CR
- **Özet:** Ajanların bağımsız yasal kimliği ve varlık sahipliği olmadığını;
  insan-merkezli altyapının gerçek ajan özerkliğini destekleyemediğini;
  blokzincirin üç kritik özellik sağladığını gösterir: **izinsiz-katılım**,
  **güven olmadan yerleşim (trustless settlement)** ve **makineden-makineye
  mikro-ödemeler**. Beş-katmanlı mimari (DePIN fiziksel, DID kimlik,
  RAG/MCP bilişsel, hesap-soyutlama ekonomik, Agentic-DAO yönetişim).
- **PACTA'ya ilgisi:** **DOĞRUDAN.** PACTA'nın "makine-müşteri" tezini
  akademik olarak destekler — trustless-settlement + M2M-micropayment tam
  PACTA'nın emanet katmanıdır. PACTA README'sindeki rol tanımı bu makalenin
  (4) nolu ekonomik-yerleşim katmanına denk düşer.

### 2. The Web4 Agent Economy: A Large-Scale Empirical Study
- **Kaynak:** https://arxiv.org/abs/2606.25876 (HTTP 200 ✓, v2 2026-09-02)
- **Tarih:** 2026-06-24 | **Yazarlar:** Yuhan Jin, Shuohan Wu, Chong Chen,
  Lingfeng Bao, Xiaohu Yang, Jiachi Chen | **Alan:** cs.SE
- **Özet:** Web4'te otonom ajanların kripto-cüzdan tuttuğu, zincir-içi işlem
  yaptığını ve **API çağrıları için ödediğini** belirtir; altyapı olarak
  **MCP, x402 ve EIP-8004** protokollerini isimlendirir. **99.448 çoklu-zincir
  kimlik-kaydı, 317.596.323 işlem-günlüğü, 341 MCP projesi, 349 GitHub
  sorunu** analiz edilmiştir. Bulgular: günde-milyonlarca M2M ödeme
  gerçekleşiyor AMA altyapı ham (kimlik/doğrulama, çapraz-ortam çalışma,
  **ödeme birlikte-çalışabilirliği en kalıcı çözülmemiş darboğaz**).
- **PACTA'ya ilgisi:** **EN YÜKSEK.** **x402'yi açıkça anar** (PACTA'nın
  `pacta/protocols/x402.py` modülü). "Ödeme birlikte-çalışabilirliği"
  darboğazı PACTA'nın çözmeyi iddia ettiği boşluktur. Ampirik veri
  (99,448/317M) PACTA dokümantasyonundaki pazar-iddialarının yerini
  gerçeğe bırakmasını sağlar.

### 3. Can Trustless Agents Be Trusted? ERC-8004 Decentralized AI Agent Ecosystem
- **Kaynak:** https://arxiv.org/abs/2606.26028 (HTTP 200 ✓, v2 2026-07-08)
- **Tarih:** 2026-06-24 | **Yazarlar:** Xihan Xiong, Zelin Li, Wei Wei,
  Qin Wang, William Knottenbelt, Zhipeng Wang | **Alan:** cs.CR
- **Özet:** ERC-8004'ün ilk izinsiz ajan-güven katmanı olduğunu; üç zincir-içi
  kayıt (Kimlik, İtibar, Doğrulama) sunduğunu; **Ethereum, BSC ve Base'de
  dağıtımdan 2026-05-13'e kadar** ampirik analiz yaptığını ve **x402 ödeme
  işlemlerini taradığını** söyler. Bulgu: çoğu kayıt yer-tutucu;
  aktif-ajan oranı **%3 / %4 / %15** (zincir sırasıyla).
- **PACTA'ya ilgisi:** **DOĞRUDAN.** "Bilinmeyen karşı-tarafa güven" sorunu
  PACTA'nın Tier-2/Tier-3 doğrulama + itibar ihtiyacının ta kendisidir.
  **Dürüst uyarı:** aktif-ajan oranının düşük olması, PACTA'nın hakemlik
  talebi varsayımının (şu-an) küçük bir gerçek-pazara hizmet ettiğini gösterir.

### 4. Inter-Agent Trust Models: A2A, AP2, ERC-8004 and Beyond
- **Kaynak:** https://arxiv.org/abs/2511.03434 (HTTP 200 ✓)
- **Tarih:** 2025-11-05 | **Yazarlar:** Botao 'Amber' Hu, Helena Rong
  | **Alan:** cs.HC
- **Özet:** 2025'te kristalleşen aracı-protokolleri (Google A2A, **AP2**,
  ERC-8004) güven-modelleri açısından karşılaştırır: **Brief, Claim, Proof,
  Stake (teminat + slashing + sigorta), Reputation, Constraint**.
- **PACTA'ya ilgisi:** **DOĞRUDAN.** PACTA'nın `pacta/protocols/ap2.py`
  modülü AP2'yi uygular. "**Stake** — teminat bağlama + slashing" kategorisi
  PACTA'nın %20-itiraz-teminatı + karesel-slashing modelinin akademik
  karsılıdır. PACTA'nın güven-modeli tablosu bu taksonomiye haritalanabilir.

### 5. Designing Inclusive Crypto-Asset Dispute Resolution
- **Kaynak:** https://arxiv.org/abs/2608.14356 (HTTP 200 ✓)
- **Tarih:** 2026-08-14 | **Yazarlar:** Gioia Arnone, Marco Giacalone
  | **Alan:** cs.CY
- **Özet:** Kripto-varlık anlaşmazlıklarının mevcut hukuk-içi yollarla
  çözülemediğini; **hibrit ODR (çevrimiçi-anlaşmazlık-çözme)** önerir:
  AI zincir-dışı (doğal-dil, sınıflandırma, kanıt-düzenleme), **akıllı
  sözleşmeler zincir-içi sınırlı işler: anlaşmazlık-kaydı, zaman-damgası,
  doğrulama, EMANET YÖNETİMİ ve sonucun icrası.**
- **PACTA'ya ilgisi:** **DOĞRUDAN.** Makalenin akıllı-sözleşme görevleri
  listesinde **emanet yönetimi** geçer — PACTA'nın `EscrowVault`'unun
  akademik yansıması. İnsan-gözetimi ve açıklayıcılık vurgusu, PACTA'nın
  Schelling hakemliğini "tamamen-otonom" olarak pazarlaması yerine bir
  insan-açıklayıcılık katmanı düşünmeye teşvik eder (gerçekçi kapsam).

### 6. Markets, Not Planners: Decentralized Orchestration of LLM Agents
- **Kaynak:** https://arxiv.org/abs/2608.23867 (HTTP 200 ✓)
- **Tarih:** 2026-08-24 | **Yazarlar:** Xiao Liu, Haoyang Li, Songwei Li,
  Hongbo Fang, Fengli Xu, Feng Shi, James Evans | **Alan:** cs.MA
- **Özet:** Merkezi-planli ajan-orkestrasyonunun darboğaz ve manipülasyona
  açık olduğunu gösterir (**tek-eklenmiş-tercih, merkezi bir tahsiscide
  tercih-edilen ajanın görev-payını neredeyse ikiye katlıyor**);
  **AgentLance** tekrarlı-emek-pazarını tanıtır: ajanlar özel-maliyetleriyle
  teklif verir, VCG-tarzı ödeme kuralı, hiyerarşik alt-yüklenme.
- **PACTA'ya ilgisi:** **ORTA-YÜKSEK.** PACTA'nın mesh-içi rolü
  (alışveriş-in-ağı) ile aynı yöndedir: **pazar-mekanizmaları > planlayıcı**.
  PACTA'nın emaneti, ajan-emek-pazarında teslimat-karşılığı-ödemenin
  (DvP) güvenli-çekirdeğidir.

---

## EKİPMAN-İÇİ BAĞLANTI (önceki dokümantasyon)

`docs/07_AKADEMIK_KAYNAKCA_VE_2026_AMPIRIK_RAPOR.md` zaten 18 klasik
kaynak içerir (Kleros, SchellingCoin, DECO, ZKCP, Asokan vs.). Bu dosya
**onun yerine değil, yanına** 2025–2026 taze-ampirik katman olarak yazıldı.

## DOĞRULANAMAYAN / BOŞ SONUÇLAR (dürüst kayıt)

- arXiv `all:"Schelling" AND all:"arbitration"` → **0 sonuç** (Schelling
  kelimesi akademik aramada daha çok **Schelling ayrılma-modeli**
  (segregation) bağlamında geçiyor; kripto-Schelling için "coordination game"
  terimlerini denemek gerekir — aşağıda öneri).
- arXiv `all:"machine customers" AND all:payments` → **0 sonuç** (terim
  Gartner'ın pazarlama-türmolojisidir, akademik literatürde "machine-to-machine
  payments" / "agent economy" kullanılır).
- `mcp__weblocal__web_search` (DuckDuckGo) bu oturumda **tüm sorgularda boş `[]`**
  döndü — bu yüzden tüm doğrulama arXiv API + `web_fetch` ile yapıldı.
- Yerleşik `web_search` aracı **HTTP 401** (DeepSeek arama-uç-noktası geçersiz
  API-anahtarı) ile başarısız oldu — kullanılamaz durumda.

## SONRAKİ ARAŞTIRMA AÇILARI (henüz denenmedi)

1. `abs:"coordination game" AND abs:slashing` — Schelling/slashing için
   daha isabetli terimler.
2. USENIX / IEEE Security & Privacy 2026 — ödeme-kanalı ve özgür-sürüş
   (free-riding) saldırıları.
3. Kleros yellow-paper v2 (mevcut kaynakçada #15) için bağımsız doğrulama.
