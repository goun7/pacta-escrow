# 04. HUKUKİ ZIRH: UCC ARTICLE 12 (CER), FINCEN VE GVK 89/13 MUAFİYETİ

> **Belge No:** PACTA-DOC-04  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Hukuki Yargı Alanları:** ABD (UCC, FinCEN), Avrupa Birliği (MiCA, AI Act), Türkiye Cumhuriyeti (GVK 89/13)

---

## 1. ABD Ticaret Kanunu (UCC) Article 12 ve Madde 12-105

2022 yılında Uniform Law Commission (ULC) ve American Law Institute (ALI) tarafından kabul edilen ve 2024–2026 yılları arasında Delaware, Teksas, Kaliforniya, Washington ve New York dahil 25'i aşkın ABD eyaletinde yürürlüğe giren **UCC 2022 Değişiklikleri**, otonom yapay zeka ticaretinin küresel yasal temelini atmıştır.

### 1.1. Kontrol Edilebilir Elektronik Kayıtlar (Controllable Electronic Records - CER)
UCC Article 12 kapsamında blokzincir üzerindeki akıllı sözleşmeler, tokenlar ve kriptografik emanet hakları birer **"CER"** olarak kabul edilir:
* **Hüküm ve Tasarruf:** Bir CER üzerinde kriptografik özel anahtar (private key) ile işlem yapabilen taraf, o kaydın yasal "kontrolüne" (control) sahip sayılır.
* **İyiniyetli İktisap Koruması (Take-Free Rule):** Pacta emanet sözleşmesi üzerinden ödeme alan bir satıcı ajan, üçüncü kişilerin önceki mülkiyet veya rehin iddialarından ari (free of competing property claims) olarak fonu iktisap eder.

### 1.2. Madde 12-105 ve Madde 2-204: Elektronik Ajanların Bağlayıcılığı
UCC Madde 12-105 ve güncellenen Madde 2, insanların gerçek zamanlı onayı olmaksızın çalışan **Elektronik Ajanların (Electronic Agents)** akdettiği sözleşmeleri hukuken geçerli kılmıştır:
* Bir yapay zeka ajanının x402 veya AP2 üzerinden bir emanet sözleşmesini onaylaması, ajanın temsil ettiği tüzel veya gerçek kişi adına bağlayıcı bir irade beyanıdır.
* Pacta akıllı sözleşmelerinin ürettiği kriptografik kayıtlar, ABD federal ve eyalet mahkemelerinde **"Kesin Delil (Conclusive Proof)"** niteliğindedir.

---

## 2. FinCEN FIN-2019-G001 Non-Custodial Akıllı Sözleşme Muafiyeti

Kripto para ve emanet operasyonlarındaki en büyük düzenleyici risk, ABD Mali Suçları Araştırma Ağı (FinCEN) tarafından **Para Hizmeti İşi (Money Services Business - MSB)** veya **Para Transfer Edicisi (Money Transmitter)** olarak sınıflandırılmaktır.

### 2.1. FinCEN'in 9 Mayıs 2019 Tarihli Kılavuz İlkesi (FIN-2019-G001)
Kılavuzun 5.1.1 ve 5.2 bölümleri uyarınca:
* Yalnızca kullanıcıların kendi fonlarını kilitlediği ve serbest bırakılma şartlarının taraflarca belirlenen matematiksel kodlarla (smart contract) yönetildiği sistemlerde;
* Eğer yazılım geliştirici firma **kullanıcı fonları üzerinde bağımsız tasarruf yetkisine, fonları tek taraflı dondurma veya başka adrese yönlendirme gücüne sahip değilse**;
* Bu yazılımı üreten ve dağıtan tüzel kişilik **Money Transmitter DEĞİLDİR**.

### 2.2. Pacta'nın Non-Custodial Tasarım Güvencesi
Pacta Vault akıllı sözleşmesinde hiçbir "Admin Withdraw" veya yönetici arka kapısı bulunmaz. Fonlar yalnızca teslimat kanıtı sağlandığında veya zaman aşımı dolduğunda matematiksel olarak hareket edebilir. Bu mimari, Pacta'yı 50 eyalette para aktarım lisansı (Money Transmitter License - MTL) alma zorunluluğundan muaf tutar.

---

## 3. Avrupa Birliği MiCA ve Yapay Zeka Yasası (EU AI Act) Uyumluluğu

### 3.1. MiCA (Markets in Crypto-Assets)
* Pacta protokolünde kullanılan takas varlıkları, MiCA Title III ve IV kapsamında lisanslanmış ihraççılar tarafından basılan düzenlemeye tabi e-para tokenlarıdır (USDC / EURC).
* Protokol herhangi bir kontrolsüz algoritmik stabilcoin barındırmaz.

### 3.2. EU AI Act Madde 14 (İnsan Gözetimi ve Denetim İzi)
* Yüksek riskli kurumsal B2B finansal süreçlerde otonom uyuşmazlıkların denetlenebilirliği için Pacta, her emanet işleminde RFC 3161 zaman damgalı Merkle denetim izi (audit log) üretir.
* Kurumsal müşteriler için gerektiğinde uyuşmazlığın insan gözetimine (Human-in-the-loop escalation) devredilebileceği uyumluluk arabirimi hazırdır.

---

## 4. Türkiye 193 Sayılı GVK Madde 89/13 Vergi Kalkanı

* **Tam İstisna:** Türkiye Cumhuriyeti Gelir Vergisi Kanunu Madde 89/13 uyarınca; Türkiye'de mukim girişimcilerin yurtdışındaki müşterilere sunduğu yazılım, blokzincir altyapısı ve veri analizi hizmetlerinden elde edilen kazancın **%100'ü gelir vergisinden müstesnadır** (%0 Gelir Vergisi).
* **KDV İstisnası:** 3065 Sayılı KDV Kanunu Madde 11/1-a uyarınca hizmetten yurtdışında faydalanıldığı için işlem **%0 KDV** ile faturalandırılır.
* **Tahsilat Güzergahı:** Protokol komisyonları akıllı sözleşme havuzunda toplanır; Polar.sh / Lemon Squeezy (MoR) veya kurumsal kripto takas rayları üzerinden Türkiye ticari banka hesabına döviz ihracatı olarak aktarılır.
