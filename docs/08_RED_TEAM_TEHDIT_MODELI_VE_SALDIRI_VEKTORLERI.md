# 08. RED TEAM TEHDİT MODELİ VE SALDIRI VEKTÖRLERİ

> **Belge No:** PACTA-DOC-08  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Kapsam:** 10 Gelişmiş Saldırı Vektörü, Kriptografik Karşı Önlemler ve 5 Kesin Güvenlik Değişmezi

---

## 1. Kapsamlı Saldırı Vektörleri ve Savunma Matrisi

| No | Saldırı Vektörü | Tehdit Tanımı | Saldırganın Amacı | Pacta Kriptografik & Algoritmik Karşı Önlemi |
|---|---|---|---|---|
| **01** | **Bedavacılık (Free-Riding Buyer)** | Alıcı ajan çıktıyı alır, kütüphanesine kaydeder ancak akıllı sözleşmeye uyuşmazlık bildirir. | Hizmeti bedavaya getirmek. | **Zorunlu İtiraz Teminatı ($B_{\text{dispute}} = 0.20 \times V$).** Eğer çıktı şema testinden geçerse teminat satıcıya aktarılır, alıcının itirazı reddedilir. |
| **02** | **Bozuk Teslimat (Corrupt Seller)** | Satıcı ajan anlamsız JSON veya bozuk hash ile ödemeyi çözmeye çalışır. | İş yapmadan emanetteki parayı çekmek. | **Tier-1 JSON-Schema ve Tier-2 WASI hash-chain kontrolü.** Şema eşleşmezse sözleşme otomatik alıcıya iade edilir. |
| **03** | **Zaman Aşımı Kilidi (Griefing Timeout)** | Satıcı ödeme kilitlendikten sonra işi yapmaz, alıcının likiditesini kilitler. | Alıcı ajanın sermayesini dondurmak. | **Katı SLA Zaman Aşımı Saati ($T_{\text{max}} = 5000\text{ ms}$).** Süre dolduğu an alıcı fonu tek taraflı çekebilir. |
| **04** | **Hakem Rüşveti (Collusive Arbitrators)** | Kötü niyetli bir taraf hakem düğümlerini satın alarak hileli karara zorlar. | Haksız yere emaneti veya teminatı boşaltmak. | **Rastgele VRF (Verifiable Random Function)** ile gizli komite seçimi + **Karesel Slashing** + Karşı temyiz hakkı. |
| **05** | **Önden Koşma (Front-Running / MEV)** | Kötü niyetli bir arama botu ödeme veya uyuşmazlık işlemini mempool'da öne alır. | Arbitraj yapmak veya işlem sırasını bozmak. | **EIP-712 imzalı taahhüt-ifşa (commit-reveal)** şeması ve özel mempool (Base Private RPC / Flashbots Protect) kullanımı. |
| **06** | **Yeniden Giriş (Re-entrancy Vault Drain)** | Kötü niyetli alıcı/satıcı sözleşmesi geri çağırım kancalarıyla kasayı boşaltmaya çalışır. | Kasa bakiyesini tüketmek. | **Check-Effects-Interactions** paterni ve `nonReentrant` bayrağı. Bakiye düşülmeden dış transfer yapılmaz. |
| **07** | **Şema Zehirleme (Schema Poisoning)** | Satıcı şemada olmayan ek zararlı alanlar (prompt injection) enjekte eder. | Alıcı ajanı içeriden hacklemek. | **Katı Şema İzolasyonu:** Yalnızca tanımlı alanlar kabul edilir (`additionalProperties: false`), fazlalıklar filtrelenir. |
| **08** | **MitM TLS Vekili (TLS Proxy Tampering)**| Ajan harici API verisini çekerken aradaki proxy yanıtı tahrif eder. | Sahte piyasa verisi sunmak. | **DECO / TLSNotary zkTLS Üç Taraflı El Sıkışma.** Sunucu oturum anahtarları şifreli bölünür, veri aracı tarafından değiştirilemez. |
| **09** | **Tekrar Oynatma (Nonce Replay Attack)** | Eski bir iş emrinin imzasını veya işlemini tekrar ağa basarak fon çalmak. | Aynı emri iki kez faturalandırmak. | **Tekil UUIDv4 İş Kimliği + EIP-712 Nonce Eşleme.** Kullanılan her iş kimliği depolanır ve ikinci kez çağrılamaz. |
| **10** | **Flaş Kredi Hizmet Reddi (Flash Loan DoS)**| Saldırgan flaş krediyle çok sayıda emanet kilitleyerek kasayı meşgul eder. | Protokol gazını ve limitlerini tıkamak. | **İşlem Başına Minimum Tutar Sınırı ($0.001 USDC)** ve cüzdan bazlı dinamik hız sınırlaması (rate-limiting). |

---

## 2. Kesin Güvenlik Değişmezleri (Formal Invariants)

Pacta akıllı sözleşmeleri ve yerel yürütme motoru şu 5 matematiksel değişmezi (invariants) her blokta ve her işlemde korumak zorundadır:

### Değişmez 1: Kasa Ödeme Gücü Değişmezi (Solvency Invariant)
$$\forall t, \quad \text{VaultBalance}_t \ge \sum_{j \in \text{ActiveJobs}} \text{Amount}_j + \sum_{d \in \text{ActiveDisputes}} \text{Bond}_d$$
*Anlamı:* Kasa bakiyesi hiçbir zaman kilitli emanetler ve teminatların toplamının altına düşemez. Açık rehin veya fraksiyonel rezerv yasaktır.

### Değişmez 2: Teslimat Adaleti Değişmezi (Delivery Fairness Invariant)
$$(\text{ProofValid}(P) \land t \le T_{\text{deadline}}) \iff \text{State} \to \text{SettledToSeller}$$
*Anlamı:* Kanıtı geçerli olan ve süresinde teslim edilen her iş satıcıya eksiksiz aktarılır; alıcı bunu tek taraflı durduramaz.

### Değişmez 3: Zaman Aşımı Güvencesi (Timeout Safety Invariant)
$$(\neg \text{OutputSubmitted} \land t > T_{\text{deadline}}) \implies \text{State} \to \text{RefundedToBuyer}$$
*Anlamı:* Satıcı SLA süresini aştığı an alıcının parası tek kuruş kayıp olmadan iade edilir.

### Değişmez 4: Gözetimsiz Kasa Değişmezi (Non-Custodial Invariant)
$$\forall \text{AdminKey}, \quad \text{WithdrawalAuthority}(\text{AdminKey}) = \emptyset$$
*Anlamı:* Yönetici anahtarlarının kasadaki kullanıcı fonlarına doğrudan dokunma yetkisi kesin olarak sıfırdır.

### Değişmez 5: Sybil Dirençli Karesel Ceza Değişmezi (Sybil-Proof Slashing Invariant)
$$\text{Penalty}_{\text{slashed}} > \max(\text{Bribe}_{\text{potential}})$$
*Anlamı:* Hileli oy kullanan hakem düğümünün karesel cezayla kaybettiği hisse, elde edebileceği azami rüşvet gelirinden daima büyüktür.
