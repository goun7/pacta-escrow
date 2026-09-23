# 01. M2M ADİL TAKAS VE TESLİMAT KARŞILIĞI ÖDEME (DvP) KRİPTO EKONOMİSİ

> **Belge No:** PACTA-DOC-01  
> **Sürüm:** 2026.1 Enterprise-Sovereign  
> **Konu:** Otonom Ajan Ağlarında Adil Takas (Fair Exchange), İki General Çıkmazı ve Teslimat Karşılığı Ödeme (Delivery-versus-Payment) Kripto-Ekonomik Formülasyonu

---

## 1. Dağıtık Sistemlerde "İki General Açmazı" ve M2M Ticaret Krizi

Otonom yapay zeka ajanlarının (Autonomous AI Agents) ve makine müşterilerin (Machine Customers / Custobots) birbirleriyle insan müdahalesi olmaksızın ekonomik etkileşime girmesi, dağıtık sistemler teorisinin en kadim problemlerinden biri olan **"Adil Takas Çıkmazı (Fair Exchange Problem)"** ile karşı karşıyadır.

Geleneksel insan ticaretinde güven; gecikmeli mahkemeler, itibar sistemleri, kredi kartı ters ibrazları (chargeback) ve banka teminat mektupları gibi yüksek sürtünmeli kurumlarla sağlanır. Ancak mikro ve makro saniyeler mertebesinde çalışan M2M (Machine-to-Machine) otonom ağlarında bu mekanizmaların hiçbiri çalışmaz:

```
[Alıcı Ajan A] ──(USDC Ödemesi Gönderildi)──► [Satıcı Ajan B]
       │                                             │
       │                               (Sunucu Çöktü / Bozuk Veri Döndü)
       ▼                                             ▼
[Alıcının Parası Yandı!]                    [Geri Alınamaz On-Chain Mutabakat]
```

### 1.1. Temel Aksiyomlar ve Tehdit Modeli
* **Asenkron İletişim Kanalı:** Ajanlar arasındaki ağ gecikmesi ($\Delta$) sınırlı ancak belirsizdir. Mesajlar gecikebilir, sırası değişebilir veya düşebilir.
* **Bizans Davranışlı Taraflar:** Alıcı ve satıcı ajanlar rasyonel fayda maksimizasyonu yapan aktörlerdir. Hile yapmanın (örneğin veriyi alıp ödememek veya parayı alıp kalitesiz veri göndermek) marjinal getirisi dürüstlükten yüksek olduğu anda Bizans davranışı sergilerler.
* **Çözüm İhtiyacı:** Üçüncü taraf bir saklama kuruluşuna (trusted centralized custodian) muhtaç olmadan, teslimat ile ödemeyi atomik olarak birbirine bağlayan **kriptografik teslimat karşılığı ödeme (DvP)** altyapısı.

---

## 2. Asokan-Shoup-Waidner İyimser Adil Takas (Optimistic Fair Exchange)

Pacta protokolü, N. Asokan, Victor Shoup ve Michael Waidner tarafından temelleri atılan **İyimser Adil Takas (Optimistic Protocols for Fair Exchange)** prensibine dayanır.

### 2.1. İyimserlik İlkesi (The Optimistic Principle)
Eğer her iki taraf da sözleşme şartlarına uyarsa (dürüst alıcı + dürüst satıcı), üçüncü taraf hakeme (arbitrator) veya ağır konsensüs mekanizmalarına zincir üstünde ihtiyaç duyulmaz. İşlem maliyeti $O(1)$'dir ve doğrudan off-chain imzalı taahhütlerle çözülür.

Hakem (Arbitrator / Oracle Quorum) **yalnızca ve yalnızca** şu iki durumda devreye girer:
1. **İhlal (Breach):** Taraflardan birinin taahhüt ettiği şemayı, zaman aşımını veya yürütme makbuzunu ihlal etmesi.
2. **Uyuşmazlık (Dispute):** Çıktının kalitesine veya doğruluğuna ilişkin bir itirazın resmi olarak teminatla kilitlenmesi.

### 2.2. Protokol Matematiksel Durum Uzayı
Emanet durum uzayı $S \in \{\text{Init}, \text{Locked}, \text{Submitted}, \text{Verified}, \text{Settled}, \text{Disputed}, \text{Refunded}\}$ olarak tanımlanır.

Durum geçiş fonksiyonu $\delta(S_t, \text{Event}, \text{Proof})$:

$$\delta(\text{Locked}, \text{SubmitProof}(P), \text{Valid}(P) \land t \le T_{\text{deadline}}) \to \text{Settled}$$

$$\delta(\text{Locked}, \text{Timeout}, t > T_{\text{deadline}}) \to \text{Refunded}$$

$$\delta(\text{Submitted}, \text{DisputeClaim}(B_{\text{dispute}}), B_{\text{dispute}} \ge \alpha \cdot V) \to \text{Disputed}$$

---

## 3. Oyun Teorisi ve Nash Dengesi İspatı

Pacta'nın güvenliği, cezalandırma parametrelerinin ekonomik olarak hileyi imkansız kıldığı bir **Genişletilmiş Formlu Dinamik Oyun (Extensive-Form Game with Imperfect Information)** olarak modellenmiştir.

### 3.1. Oyuncular ve Strateji Kümeleri
* **Alıcı ($B$):** Stratejiler $\sigma_B \in \{\text{Dürüst Ödeme}, \text{Kötü Niyetli İtiraz (Griefing)}\}$
* **Satıcı ($S$):** Stratejiler $\sigma_S \in \{\text{Dürüst Teslimat}, \text{Hileli / Bozuk Teslimat}\}$
* **İşlem Değeri:** $V \in \mathbb{R}^+$ (USDC)
* **Satıcının Hesaplama / Veri Maliyeti:** $C_s < V$
* **Protokol Komisyonu:** $F = \tau \cdot V$ ($\tau = 0.0075$)
* **Satıcının Yatırmış Olduğu PVA Teminatı:** $S_{\text{bond}} \ge 10 \cdot V$
* **Alıcının İtiraz Açmak İçin Yatırdığı Depozito:** $B_{\text{dispute}} = 0.20 \cdot V$

### 3.2. Getiri Matrisi (Payoff Matrix)

| Alıcı \ Satıcı | Satıcı: Dürüst Teslimat ($H_s$) | Satıcı: Hileli Teslimat ($F_s$) |
|---|---|---|
| **Alıcı: Normal Kabul ($H_b$)** | $U_b = V_{\text{fayda}} - V$<br>$U_s = V - C_s - F$ | $U_b = 0$ (Tier-1 oto-iade)<br>$U_s = -C_{\text{boşa}}$ |
| **Alıcı: Kötü Niyetli İtiraz ($G_b$)** | $U_b = -B_{\text{dispute}}$ (Depozito yandı!)<br>$U_s = V - C_s - F + 0.5 B_{\text{dispute}}$ | $U_b = V_{\text{tazminat}}$<br>$U_s = -S_{\text{bond}}$ (Slashing!) |

### 3.3. Dürüstlük Baskınlığı Teoremi (Theorem of Honest Dominance)
**Teorem:** $S_{\text{bond}} > V$ ve $B_{\text{dispute}} \ge 0.20 V$ olduğu koşulda, (Dürüst Kabul, Dürüst Teslimat) strateji çifti $(H_b, H_s)$ katı bir Alt-Oyun Mükemmel Nash Dengesidir (Subgame Perfect Nash Equilibrium - SPNE).

**İspat:**
1. *Satıcı Açısından:*
   Satıcı $F_s$ seçerse; deterministik Tier-1 sentaks denetimi ve Tier-2 Tamga hash-zinciri denetimi nedeniyle yakalanma olasılığı $p = 1.0$'dır.
   $$U_s(F_s) = -S_{\text{bond}} - C_s < 0$$
   Satıcı $H_s$ seçerse:
   $$U_s(H_s) = (1 - \tau)V - C_s > 0$$
   Dolayısıyla $U_s(H_s) > U_s(F_s)$ her zaman geçerlidir. Satıcı için $H_s$ kesin baskın stratejidir.

2. *Alıcı Açısından:*
   Satıcının $H_s$ oynadığı bilindiğinde, alıcı $G_b$ (temelsiz itiraz) oynarsa; Schelling hakem konsorsiyumu çıktının şemaya ve Tamga makbuzuna uygun olduğunu onaylar.
   Alıcının yatırdığı $B_{\text{dispute}}$ depozitosu yakılır ve yarısı satıcıya tazminat olarak verilir.
   $$U_b(G_b) = V_{\text{fayda}} - V - B_{\text{dispute}} < U_b(H_b) = V_{\text{fayda}} - V$$
   Dolayısıyla alıcı için de $H_b$ kesin baskın stratejidir.

**Sonuç:** Sistemde hiçbir rasyonel ajan hile yapamaz veya kötü niyetli uyuşmazlık açamaz.
