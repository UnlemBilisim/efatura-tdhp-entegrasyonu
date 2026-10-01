# Yeni Şirket Ekleme — Veri Formatı Kılavuzu

Yeni bir şirketi sisteme eklerken (onboarding) bizden **3 zorunlu, 1
opsiyonel dosya** istenir. Bu belge her birinin kesin formatını tanımlar.

## 1. VKN

Şirketin kendi vergi kimlik numarası (10 hane, sadece rakam). Diğer üç
dosyayla birlikte, ayrıca bildirilir.

## 2. Fatura geçmişi — XML

Son 6 aya ait **UBL-TR formatında** e-fatura XML dosyaları, her fatura ayrı
bir `.xml` dosyası olarak, tek bir klasörde.

- Dosya adı önemli değil — fatura numarası XML içeriğinden (`cbc:ID`) okunur.
- Hem alış (inbox) hem satış (outbox) faturaları kabul edilir, yön otomatik
  tespit edilir.

## 3. Mizan

Şirketin hesap planı — Excel (`.xlsx`), aşağıdaki sütunları içerir:

| Sütun | Açıklama |
|---|---|
| **HESAP KODU** | 3 haneli ana kod ya da tam alt kırılım (örn. `320` veya `320.01.00272`) — hücre **metin (text)** biçiminde olmalı, sayı biçiminde değil |
| **HESAP ADI** | Hesabın adı (örn. "Satıcılar" ya da tedarikçi/müşteri unvanı) |

Veri, başlık satırından sonraki satırdan itibaren okunur.

> ⚠️ **Hesap kodu hücresi metin olmalı.** Excel'de bir hücre "sayı" biçiminde
> biçimlendirilmişse (örn. `320` otomatik olarak sayıya çevrilmişse), o satır
> **sessizce atlanır** — hata vermez ama o hesap kodu sisteme hiç girmez.
> Emin değilseniz HESAP KODU sütununun tamamını Excel'de "Metin" (Text)
> biçimine çevirin.

## 4. Yevmiye kaydı — **standart format**

Son 6 aya ait muhasebe kayıtları. **Muhasebe yazılımınızın standart
dökümünü değil, aşağıdaki 5 sütunlu formatı** göndermenizi rica ediyoruz —
farklı yazılımların dökümleri birbirinden çok farklı olduğu için, tek bir
ortak format üzerinden çalışmak hem bizim için hem sizin için daha az
hataya açık.

**Dosya:** `.xlsx` veya `.csv`, başlık satırı zorunlu.

| Sütun | Örnek | Açıklama |
|---|---|---|
| **fatura_no** | `HE22026000014163` | İlgili faturanın numarası — **XML'deki `cbc:ID` ile birebir aynı olmalı** |
| **hesap_kodu** | `320.01.00272` | 3 haneli ana kod ya da tam alt kırılım |
| **hesap_adi** | `Satıcılar` | Hesap adı |
| **borc_alacak** | `Borç` / `Alacak` | (`Borc`/`Alacak`, `D`/`C`, `Debit`/`Credit` de kabul edilir) |
| **tutar** | `45296.00` | Sayı, ondalık ayracı nokta |

**Bir fatura, yevmiyede birden fazla satır tutar** (her hesap hareketi ayrı
satır). Örnek — tek bir tevkifatlı alış faturası için 4 satır:

| fatura_no | hesap_kodu | hesap_adi | borc_alacak | tutar |
|---|---|---|---|---|
| HE22026000014163 | 770 | Genel Yönetim Giderleri | Borç | 45296.00 |
| HE22026000014163 | 191.05.00005 | %20 5/10 Tevkifatlı KDV | Borç | 9059.20 |
| HE22026000014163 | 360.01.00005 | Ödenecek Vergi ve Fonlar | Alacak | 4529.60 |
| HE22026000014163 | 320.01.00272 | Satıcılar | Alacak | 49825.60 |

Örnek dosya (gerçek, doğrulanmış bir kayıttan): `yevmiye-sablonu-ornek.xlsx`.

### Neden bu format?

Sistem, gönderdiğiniz fatura XML'lerini bu yevmiye kayıtlarıyla **fatura
numarasına göre eşleştirir** ve "bu tür fatura geçmişte hangi hesaba
kaydedilmiş" bilgisini öğrenir — bu, gelecekteki faturalarınız için otomatik
öneriler üretmenin temelidir. Eşleşme, fatura numarası XML'deki `cbc:ID`
ile yevmiyedeki `fatura_no` birebir aynı olduğunda çalışır; farklıysa o
fatura eşleşmez ve öğrenme sürecine dahil edilmez (veri kaybı olmaz, sadece
o fatura atlanır — size ayrı raporlanır).

### Sık karşılaşılan sorunlar

- **`fatura_no` boş veya XML'deki numarayla uyuşmuyor** → o fatura eşleşmez.
- **`hesap_kodu` mizanda yok** → kayıt yine de işlenir ama alt kırılım
  bulunamayabilir.
- **Eksik sütun** → dosya hiç işlenmez, hangi sütun(lar)ın eksik olduğu
  açıkça bildirilir.

## 5. NACE kodları — **opsiyonel**, `nace.txt`

Şirketin NACE (faaliyet) kodları — **göndermeseniz de olur**, eklerseniz
KDV ön filtrelemesi (hangi oranların mevzuata uygun olduğunu kontrol eden
adım) daha isabetli çalışır. Göndermezseniz o kalemler gerektiğinde insan
incelemesine düşer, hiçbir veri kaybı olmaz.

**Dosya:** `nace.txt`, düz metin.

- Her satırda **bir** NACE kodu (noktalı/noktasız fark etmez).
- Boş satırlar ve `#` ile başlayan satırlar yorum sayılır, atlanır.
- Birden fazla NACE kodunuz varsa her biri ayrı satıra yazılır (virgülle
  ayırmayın — her satır tek bir kod olarak okunur, virgülle ayrılmış bir
  satır tek, geçersiz bir kod sayılır).

Örnek:

```
# Ana faaliyet
10.71.01
# İkincil faaliyet
10.72.00
```

**Bu dosyayı bir kere gönderirsiniz, sonrasında `POST /fatura/isle`
isteklerinizde `satici_nace_kodlari` alanını doldurmanıza gerek kalmaz**
(bkz. `API-ENTEGRASYON-KILAVUZU.md`) — sistem burada kayıtlı NACE kodlarını
otomatik kullanır. O alanı yalnızca kayıtlı NACE'yi geçici olarak override
etmek isterseniz doldurursunuz.
