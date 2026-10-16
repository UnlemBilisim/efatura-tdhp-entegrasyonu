# Dış Ekip API Kullanımı — `POST /fatura/isle`

Bu belge, muhasebe kaydı üretmek isteyen dış ekibin bilmesi gereken **tek
kaynaktır** — API sözleşmesi ve çıktı şemasının tam detayı bir aradadır.
Servis, e-fatura XML'ini alıp muhasebe kayıtlarını (`records[]`) döner.

---

## 0. Sorumluluk paylaşımı

| Taraf | Sorumluluk |
|---|---|
| **Biz (backend)** | `POST /fatura/isle` — fatura XML → muhasebe kaydı (`dis_sema`) |
| **Dış ekip (frontend)** | Kullanıcı arayüzü, dosya yükleme, sonucun gösterimi |

**Çağrı şekli: sunucu-sunucu.** Dış ekibin backend'i bizim API'yi çağırır;
istek tarayıcıdan **gelmez**. Bu yüzden CORS yapılandırması **bilinçli olarak
yapılmamıştır** — tarayıcıdan doğrudan `fetch` denenirse preflight `405` döner
ve istek başarısız olur. Mimari değişip tarayıcıdan çağrı gerekirse haber
verin; `CORSMiddleware` eklenmesi gerekir.

> ⚠️ **Arayüzü yazarken:** Fatura alanları (kalem adı, tedarikçi unvanı, not
> alanı) **güvenilmeyen veridir** — faturayı gönderen dış taraf yazmıştır ve
> HTML/script içerebilir. Bunları DOM'a basarken escape edin (`textContent`,
> React/Vue'nun varsayılan escape'i) — `innerHTML` ile ham basmak XSS'e yol
> açar.

## 1. Endpoint'ler

```
GET  http://<host>:8100/durum              — sağlık kontrolü
GET  http://<host>:8100/kayitli-sirketler  — bilinen VKN listesi (bkz. §2.1)
POST http://<host>:8100/fatura/isle        — asıl tahmin (bu belgenin konusu)
POST http://<host>:8100/fatura/onayla      — tahmini kalıcı kayıt/RAG'a al (§7)
POST http://<host>:8100/musteri/onboard    — çok şirketli zip ile yeni şirket kur (§9, ayrı yetki ister)
GET  http://<host>:8100/musteri/isler/{id} — onboarding ilerlemesi (§9)
```

> ⚠️ **Gerçek adres henüz iletilmedi.** `<host>` bir yer tutucudur — dağıtım
> adresi (IP/domain/tünel) netleşince ayrı bir kanaldan bildirilecektir.

`/durum` dışındaki iş endpoint'leri bir **API anahtarı** ister (`efk_` ile
başlar). Anahtar size bizim tarafımızdan, ayrı ve güvenli bir kanaldan
iletilir; her istekte `Authorization` başlığında gönderilir:

```
POST /fatura/isle
Content-Type: application/json
Authorization: Bearer <API_ANAHTARI>
```

Her anahtar belirli şirket(ler) adına işlem yapmaya yetkilidir:

- İstekteki `satici_vkn` anahtarınızın yetkili olduğu şirketlerden biri
  değilse `403` döner.
- `GET /kayitli-sirketler` yalnızca anahtarınızın yetkili olduğu
  şirketleri listeler.
- Başka bir şirkete ait `prediction_id`'yi onaylamaya çalışmak `404` döner.

Anahtar iptal edilirse istekler `401` döner; yeni anahtar için bizimle
iletişime geçin.

**Anahtar modeli:** Anahtarı **biz üretiriz** (kendi anahtarınızı üretip bize bildirmezsiniz). Kapsam birimi tek bir şirket
değil, **mali müşavirdir**: her müşaviri temsil eden istemciye bir anahtar verilir ve o müşavirin yönettiği tüm VKN'ler o
anahtara yetkili olur. Müşavirin yeni bir müşterisi sisteme eklendiğinde anahtar iptal edilip yeniden üretilmez; mevcut
anahtarın VKN listesi genişletilir ve **anahtarın değeri değişmez** — elinizdeki anahtarı güncellemeniz gerekmez. Anahtar
değerleri size her zaman ayrı ve güvenli bir kanaldan iletilir.

## 2. İstek gövdesi

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `fatura_xml` | string | **Evet** | UBL-TR fatura XML'inin tamamı (ham metin) |
| `satici_vkn` | string | **Evet** | **Kendi şirketinizin VKN'si** — aşağıya bakın |
| `satici_nace_kodlari` | string[] | Hayır | Satıcının NACE kodları; yalnızca outbox'ta kullanılır. Noktalı (`"25.40.04"`) veya noktasız (`"254004"`) gönderilebilir — sistem ikisini de aynı koda normalize eder |
| `onay` | boolean | Hayır | Uyarıya rağmen devam; **outbox'ta gerekebilir** (§4) |
| `kur_secimi` | string | Hayır | `"orijinal"` \| `"tl"` — TL dışı faturalarda (§5) |
| `dosya_adi` | string | Hayır | Yüklenen XML dosyasının orijinal adı. Sadece izleme/loglama amaçlı — işleme mantığını etkilemez, boş bırakılabilir |
| `gonderen_kullanici` | string | Hayır | Faturayı gönderen kişinin kimliği (kendi arayüzünüzde login olan kullanıcının adı/kullanıcı adı — en fazla 200 karakter). **DOĞRULANMAZ**, sadece audit log'a işlenir ("kim kaç fatura işledi" raporlaması için, 2026-09-11 eklendi). Boş bırakılabilir |

### 2.1 `GET /kayitli-sirketler` — hangi VKN'ler bizde tanımlı

```json
{"vkn_listesi": ["0460351893", "1111111111"]}
```

Sistem çoklu şirket (tenant) destekliyor; her `satici_vkn` kendi izole
şemasına/mizanına/geçmiş fatura havuzuna sahiptir. **Bu endpoint, hangi
VKN'lerin bizim tarafımızda önceden onboard edildiğini gösterir.**

> ⚠️ **Onboard edilmemiş bir VKN `404` döner** (2026-09-28'den itibaren).
> Fatura işlenmez, kayıt üretilmez. Yeni bir şirket için önce bizimle
> iletişime geçip onboard edilmesini isteyin; hangi VKN'lerin hazır
> olduğunu bu endpoint'ten görebilirsiniz.
>
> Onboard edilmiş ama **mizanı henüz yüklenmemiş** bir şirket ise hata
> almaz, sonuç kalitesi düşer: sistem sadece 3 haneli TDHP ana kodunu
> üretir, alt kırılım (muavin hesap) çözülemez ve `account_code_reason` bunu
> açıkça söyler. Kayıt hatalı değildir, sadece daha az detaylıdır.

> ⚠️ **`satici_vkn` yanıltıcı bir isimdir.** Fatura üzerindeki satıcının VKN'si
> değil, **isteği yapan şirketin kendi VKN'si**dir (tarihsel isim; kod içinde
> `own_vkn` anlamında kullanılır). Sistem bu değeri XML'deki taraflarla
> karşılaştırıp faturanın yönünü belirler:
> - Kendi VKN'niz **satıcı** tarafındaysa → `outbox` (siz kestiniz)
> - Kendi VKN'niz **alıcı** tarafındaysa → `inbox` (size geldi)

### En basit istek

```bash
curl -X POST http://<host>:8100/fatura/isle \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_ANAHTARI" \
  -d '{
    "fatura_xml": "<?xml version=\"1.0\"?><Invoice ...>",
    "satici_vkn": "0460351893"
  }'
```

Python ile (XML'i dosyadan okuyarak):

```python
import json, os, requests

with open("fatura.xml", encoding="utf-8") as f:
    xml = f.read()

r = requests.post(
    "http://<host>:8100/fatura/isle",
    headers={"Authorization": f"Bearer {os.environ['API_ANAHTARI']}"},
    json={"fatura_xml": xml, "satici_vkn": "0460351893", "onay": True},
    timeout=600,          # LLM çağrısı 10-30 sn sürer, cömert timeout verin
)
r.raise_for_status()
cevap = r.json()

kayitlar = cevap["tdhp_tahmini"]["dis_sema"]   # ← istediğiniz JSON
```

## 3. Cevap — `dis_sema`

**İhtiyacınız olan alan: `tdhp_tahmini.dis_sema`.** Doğrudan kullanabilirsiniz.

```json
{
  "currency": "TRY",
  "customer": { "id": "8441199152", "name": "TİMSAN VİNÇ VE MÜH. LTD. ŞTİ." },
  "file_path": "",
  "invoice_id": "AKA2025000000001",
  "issue_date": "2025-01-07",
  "payable_amount": 58319.2,
  "records": [
    {
      "account_code": "120.01.00295",
      "account_code_type": "C",
      "account_description": "TİMSAN VINÇ VE MÜHENDISLIK SANAYİ TİCARET LTD",
      "account_code_reason": "Karşı taraf unvanı mizandaki '...' kaydıyla eşleşti (isim benzerliği %100); aynı cari hesap kullanıldı.",
      "amount": 58319.2,
      "debit_credit": "BORÇ",
      "onerilen_yeni_kod": null
    }
  ],
  "success": true,
  "supplier": { "id": "0460351893", "name": "" }
}
```

### Tam zarf (9 alan)

| Alan | Kaynak |
|---|---|
| `invoice_id` | Fatura `cbc:ID` |
| `issue_date` | Fatura `cbc:IssueDate` |
| `currency` | Fatura para birimi |
| `payable_amount` | Fatura ödenecek tutar (float'a çevrilir) |
| `customer` / `supplier` | `{id, name}` — **yöne göre** belirlenir (aşağıya bakın) |
| `records` | Muhasebe kayıtları (6 alanlı, §3.1) |
| `success` | `tdhp_tahmini.error is None` |
| `file_path` | Çağıran katmandan gelir; verilmezse `""` |

### Zarf alanları — detay

- `customer` / `supplier` — **yöne göre** yerleşir. outbox'ta karşı taraf
  `customer`, inbox'ta `supplier` olur. Kendi tarafınızda yalnızca `id` dolu,
  `name` boş string (fatura XML'i kendi unvanınızı taşımıyor — sistem yalnızca
  karşı tarafı tutuyor).
- `success` — tahmin hatasız tamamlandıysa `true`.
- `file_path` — şu an **her zaman boş string**; servis ham XML alıyor, dosya
  yolu bilmiyor. Bu alan size gerekiyorsa istek gövdesine eklenmesi gerekir,
  haber verin.

### 3.1 `records[]` — tam şema ve üretim kuralları

Bu bölüm, cevabınızdaki `records[]` öğelerinin tam şemasını ve alanların nasıl üretildiğini tanımlar.

> **Not:** `onerilen_yeni_kod` (7. alan) sonradan eklendi. Mevcut 6 alan değişmedi — bu **geriye dönük uyumlu bir
> ekleme**dir; bilinmeyen alanları yok sayan bir entegrasyon çalışmaya devam eder.

Her `records[]` öğesi **tam olarak** şu 7 alanı taşır — eksik veya fazla alan yok:

| Alan | Tip | Açıklama |
|---|---|---|
| `account_code` | string | TDHP hesap kodu, alt kırılımlı (`"191.01.00020"`). Alt kırılım çözülemezse 3 haneli kalır (`"320"`). |
| `account_code_type` | string | `"C"` = cari hesap, `"G"` = diğer. Ana kod 120/320/340/440/159/420'den biriyse `C`. |
| `account_description` | string | Mizandaki HESAP ADI (`"%20 İndirilecek KDV"`). Bilinmiyorsa **boş string** — `null` değil. |
| `account_code_reason` | string | Kodun neden seçildiği. **Asla boş kalmaz.** |
| `amount` | number | Tutar — dönüşümde değiştirilmez. |
| `debit_credit` | string | `"BORÇ"` / `"ALACAK"` (iç şemadaki `"Borc"`/`"Alacak"`ın karşılığı). |
| `onerilen_yeni_kod` | string veya `null` | Alt kırılım hiç çözülemediğinde (`account_code` 3 haneli kaldığında) mizanla **çakışmayan** yeni bir alt kod önerisi (ör. `"320.01.00967"`). Çözülemediyse veya çözüldüyse `null`. **Bu bir öneridir, mizana hiçbir şey yazılmaz** — kullanılıp kullanılmayacağına her zaman muhasebeci karar vermeli (`success`/`account_code_reason` zaten bu kayıtların kontrol gerektirdiğini işaret eder). |

Örnek:

```json
{
  "account_code": "320.01.00376",
  "account_code_type": "C",
  "account_description": "Mehmet Kozcağız",
  "account_code_reason": "Karşı taraf unvanı mizandaki 'Mehmet Kozcağız' kaydıyla eşleşti (isim benzerliği %94); aynı cari hesap kullanıldı.",
  "amount": 1700.0,
  "debit_credit": "ALACAK"
}
```

#### `account_code_reason` nasıl üretilir?

**Deterministik üretilir — yapay zekâ modeline sorulmaz.** Modele "bu kodu neden seçtin" diye sormak
*sonradan gerekçe uydurma* riski taşır — model bir kodu bir sebeple seçip tamamen başka bir sebep yazabilir.
Gerekçe, kodun gerçekte nasıl seçildiğinden türetilir:

| Durum | Üretilen gerekçe |
|---|---|
| Karşı taraf adı mizandaki bir kayıtla eşleşti | "Karşı taraf unvanı mizandaki '…' kaydıyla eşleşti (isim benzerliği %N); aynı cari hesap kullanıldı." |
| Alt kırılım, faturadaki gerçek KDV oranına göre düzeltildi | "Hesap türü geçmiş emsal faturalara göre seçildi; alt kırılım, faturadaki gerçek KDV oranına göre … olarak düzeltildi." |
| Aynı tedarikçi/müşteriyle geçmiş benzer faturalar esas alındı | "Aynı tedarikçi/müşteri ile yapılan N geçmiş benzer faturada kullanılan hesap kırılımı esas alındı." |
| Kalem açıklaması mizandaki alt kırılım adlarıyla eşleştirildi | "Faturadaki kalem açıklaması ve mizandaki alt kırılım adları eşleştirilerek seçildi." |
| Kod 3 hanede kaldı, karşı taraf mizanda bulunamadı | "… için mizanda eşleşen alt kırılım (cari kart) bulunamadı; ana hesap kodunda bırakıldı — yeni müşteri/tedarikçi olabilir." |
| Kod 3 hanede kaldı, başka uyarı yok | "… ana hesap kodu kullanıldı; mizanda bu kod için seçilebilecek bir alt kırılım bulunamadı." |
| Başka bilgi yok | "Faturadaki kalem bilgisi ile mizandaki hesap planı eşleştirilerek seçildi." |

#### `uyari` alanının dış şemadaki karşılığı

Cevapta ayrı bir uyarı alanı **yok**. Uyarılar (örn. karşı taraf mizanda bulunamadı) kaybolmasın diye
gerekçenin sonuna `UYARI: …` olarak eklenir. Gerekçe zaten bu durumu anlatıyorsa (3 hanede kalma
senaryosu) **tekrar eklenmez.**

#### Garantiler

1. Her kayıtta yukarıdaki 7 alan **her zaman** bulunur.
2. `amount` ve `account_code` değerleri, hesaplanan muhasebe kaydıyla birebir aynıdır; yalnızca alan adları sizin
   sözleşmenize çevrilir.
3. `account_description` bilinmiyorsa boş string döner, `null` değil — tip tutarlılığına güvenebilirsiniz.

#### Bilinen sınır

"Aynı tedarikçi/müşteriyle N geçmiş benzer faturada kullanılan…" gerekçesi şu an üretilmiyor
(kaç emsal kullanıldığı bilgisi tahmin çıktısında bulunmuyor); onun yerine "kalem açıklaması mizandaki alt kırılım
adlarıyla eşleştirildi" gerekçesi yazılır.

## 4. Önemli: outbox faturalarda iki adımlı akış

Ön filtre kararı (`on_filtre_sonucu.genel_karar`) şimdilik yalnızca iki değer alır: `uygun` ve
`insan_incelemesi_gerekli`; kesin "uyumsuz" kararı üretilmez. İnbox faturalarda `asama` doğrudan
`tdhp_tahmini_tamamlandi` döner (ayrı bir "atlandı" aşaması **yoktur**, yalnızca `mesaj` alanı farklıdır).

Bu, entegrasyonda en çok kafa karıştıran davranıştır.

**Kendi kestiğiniz (outbox) faturalar KDV mevzuatı ön filtresinden geçer.**
Beyan edilen KDV oranı satıcının NACE kodlarının izin verdiği havuzla
uyuşmazsa akış **durur** ve `dis_sema` **gelmez**:

```json
{
  "asama": "on_filtre_insan_incelemesi_bekliyor",
  "on_filtre_sonucu": { "genel_karar": "insan_incelemesi_gerekli", "satir_sonuclari": [...] },
  "tdhp_tahmini": null,
  "mesaj": "Ön filtreleme sonucu: İNSAN İNCELEMESİ GEREKLİ..."
}
```

Devam etmek için **aynı isteği `"onay": true` ile tekrar gönderin.** Bu,
kararın bilinçli olarak insana devredildiği yerdir — sistem sessizce geçmez.

**İnbox faturalarda ön filtre hiç çalışmaz** (başkasının kestiği faturanın
mevzuat sorumluluğu sizde değildir), `onay` gerekmez, ilk çağrıda sonuç gelir.

### Karar ağacı

```
İstek gönder (onay yok)
   │
   ├─ asama == "tdhp_tahmini_tamamlandi"          → dis_sema HAZIR ✅
   ├─ asama == "on_filtre_insan_incelemesi_bekliyor"
   │     → on_filtre_sonucu'nu incele, sonra onay:true ile TEKRAR gönder
   ├─ asama == "kur_onayi_bekliyor"               → §5
   └─ asama == "model_eval_hazir_degil"           → sistem eksik, tekrar deneme
```

Her zaman sonuç almak istiyorsanız (ön filtre uyarısını kendiniz
değerlendirmeyecekseniz) ilk çağrıda `"onay": true` gönderin — ama o zaman
`on_filtre_sonucu`'ndaki uyarıları da loglayın, sessizce yutmayın.

## 5. TL dışı faturalar

Fatura TL değilse ve XML'de kur bilgisi varsa akış `kur_onayi_bekliyor`
aşamasında durur. Seçiminizi `kur_secimi` ile gönderin:

- `"orijinal"` — fatura kendi para biriminde işlenir
- `"tl"` — XML'deki kur oranıyla TL'ye çevrilir, tahmin TL üzerinden üretilir

Kur çevirisi bilinçli olarak **sessizce yapılmaz**.

## 6. Bilmeniz gerekenler

**Süre.** Bir fatura **10-30 saniye** sürer (LLM + RAG). Timeout'u en az 600
saniye verin. Eşzamanlı çok istek göndermeyin — servis tek worker.

**Hata durumları (`POST /fatura/isle`'a özgü — `/fatura/onayla`'nın kendi hata
davranışı §7'de).**

| Kod | Anlamı |
|---|---|
| 400 | Bozuk XML, VKN uyuşmazlığı, yön belirlenemedi |
| 401 | API anahtarı yok, geçersiz veya iptal edilmiş |
| 403 | Anahtarın `satici_vkn` adına işlem yetkisi yok |
| 404 | `satici_vkn` için onboard edilmiş şirket yok (bkz. §2.1) |
| 413 | İstek/XML boyut sınırı aşıldı — **30 MB** |
| 422 | İstek şeması geçersiz veya tahmin onaylanabilir değil |
| 502 | Ön filtreleme servisi erişilemiyor |

Hesaplama modülü hazır değilse `/fatura/isle` **200 döner**, `asama` alanı
`"model_eval_hazir_degil"` olur (bkz. §4 karar ağacı) — bu, `/fatura/onayla`
davranışından farklıdır, o gerçek bir `501` döner (§7).

`success: false` + dolu `error` alanı: tahmin üretilemedi (ör. LLM
erişilemedi). Bu durumda `records[]` boş olur — **boş listeyi "kayıt yok"
diye yorumlamayın**, `success`'i kontrol edin.

**Güvenlik.** API anahtarı zorunludur (§1). Servis yerel başlatmada
varsayılan olarak `127.0.0.1`'e bağlanır. Docker portları da loopback'e
yayınlanır. Dış erişim HTTPS reverse proxy ve ağ izin listesi üzerinden
verilmelidir. Anahtarı yalnızca sunucu tarafında (backend) saklayın,
tarayıcıya/istemci koduna koymayın.

**Uyarılar kaybolmaz.** Bir cari hesap mizanda bulunamazsa (yeni
müşteri/tedarikçi) kod 3 haneli kalır ve uyarı `account_code_reason` metninin
içine yazılır. `account_code`'da nokta yoksa alt kırılım çözülememiştir —
muhasebecinin kontrol etmesi gerekir.

## 7. `POST /fatura/onayla` — tahmini kalıcı hâle getirme (opsiyonel)

`POST /fatura/isle`, tahmini sunucuda 30 dakika geçerli bir bekleyen kayıt
olarak saklar ve cevapta `prediction_id` döndürür. İstemci tahmin içeriğini
geri göndermez. Yalnızca deterministik doğrulamadan geçen
(`tdhp_tahmini.approvable=true`) tahminler onaylanabilir.

1. Kayıt PostgreSQL'e (denetim/geçmiş amaçlı) yazılır.
2. Kayıt RAG (emsal) veritabanına eklenir — **gelecekteki benzer faturaların
   tahmin kalitesini artırır.** Onay adımını atlarsanız sisteminiz zamanla
   emsal biriktirmez, tahmin kalitesi sabit kalır.

```
POST /fatura/onayla
Content-Type: application/json
Authorization: Bearer <API_ANAHTARI>
```

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `prediction_id` | UUID string | **Evet** | `/fatura/isle` cevabındaki sunucu taraflı tahmin kimliği |

```json
{"prediction_id": "f8d7d2c7-..."}
```

Cevap:

```json
{"kaydedildi": true, "mesaj": "Fatura onaylandı — PostgreSQL'e kaydedildi ve RAG vektör veritabanına eklendi."}
```

Bulunmayan tahmin `404`; süresi dolan, daha önce onaylanan veya eş zamanlı
onaylanan tahmin `409`; doğrulamadan geçmeyen tahmin `422` döner.

## 9. `POST /musteri/onboard` — çok şirketli zip ile yeni şirket kurma

**Yetki:** Yalnızca **onboard yetkisi** verilmiş anahtarlar kullanabilir; yetkisiz anahtar `403` alır.
Yetkiyi sizin vermeniz mümkün değildir, bizden talep edilir: mevcut anahtarınıza yetki eklenir (anahtarınız
**değişmez**) ya da size yetkili yeni bir anahtar ayrı ve güvenli bir kanaldan iletilir. Anahtarınızda yetki
olup olmadığını zip göndermeden test edebilirsiniz — yanlış gövdeyle çağırın: `400` ("Gövde bir zip dosyası
değil") yetkiniz var, `403` yetkiniz yok demektir. Başarılı kurulumda yeni şirketin VKN'si anahtarınızın
kapsamına **otomatik eklenir**.

**İstek:** gövde, ham zip (`Content-Type: application/zip`). Boyut sınırı **200 MB**
(`ONBOARD_MAX_ZIP_BYTES`; bu uç nokta için genel 30 MB sınırından bağımsız).

```bash
curl -X POST http://<host>:8100/musteri/onboard \
  -H "Authorization: Bearer $API_ANAHTARI" -H "Content-Type: application/zip" \
  --data-binary @yukleme.zip
```

**Zip yapısı** — kökte her şirket için bir klasör (klasör adı = 10 haneli VKN). Tek bir
sarmalayıcı klasör (macOS "Sıkıştır" gibi) tolere edilir:

```
yukleme.zip
├── 6677889900/
│   ├── mizan.xlsx            (zorunlu)
│   ├── faturalar/*.xml       (zorunlu — dosya adı önemsiz, fatura no XML'den okunur)
│   ├── yevmiye.xlsx          (zorunlu — ya da yevmiye.csv)
│   └── nace.txt              (opsiyonel)
└── 1122334455/ ...
```

Dosya adları **tam olarak** böyle olmalı (büyük/küçük harf fark etmez). Formatlar:
[`ONBOARDING-VERI-FORMATI.md`](ONBOARDING-VERI-FORMATI.md). Başka dosyalar
yok sayılır (cevapta `atlanan_dosya` olarak sayılır); `<10 haneli VKN>` olmayan klasörler
`gecersiz_klasorler`'de listelenir.

**Cevap `202`** (işlem arka planda, şirketler sırayla kurulur):

```json
{"is_id": "bb45...", "durum": "kuyrukta", "sirketler": ["1122334455", "6677889900"],
 "atlanan_dosya": 0, "gecersiz_klasorler": []}
```

**İlerleme:** `GET /musteri/isler/{is_id}` (aynı anahtar; başka anahtarın işi `404` döner):

```json
{"is_id": "bb45...", "durum": "calisiyor", "yuzde": 63,
 "sirketler": {
   "6677889900": {"durum": "kuruldu", "yuzde": 100, "adim": "rag", "ayrinti": null,
                  "ozet": {"mizan_satir_sayisi": 21, "fatura_eslesme": "2/2", "yon_belirsiz": 0}},
   "1122334455": {"durum": "calisiyor", "yuzde": 25, "adim": "sema", "ayrinti": null, "ozet": null}}}
```

`durum` (iş): `kuyrukta` → `calisiyor` → `bitti`. Şirket durumları: `bekliyor`, `calisiyor`,
`kuruldu`, `atlandi` (zaten kurulu), `hata` (nedeni `ayrinti`'de; diğer şirketler yine işlenir).

**İlerleme yüzdesi:** `yuzde` (0–100) işin genel ilerlemesidir; şirketlerin yüzdelerinin ortalamasıdır. Her şirketin
kendi `yuzde` ve `adim` değeri vardır: `sema` (25) → `mizan` (50) → `eslestirme` (75) → `rag` (100). Yüzde **basamaklıdır**
(adımlar bitince artar); özellikle `eslestirme`'den `rag`'a geçerken fatura sayısı çoksa uzun süre aynı değerde kalabilir,
bu takılma değildir. `kuruldu` ve `atlandi` şirketler 100'dür; `hata` veren şirketin `yuzde`/`adim` değeri **hatanın hangi
adımda olduğunu** gösterir (iş genel yüzdesinde o şirket işlenmiş sayılır). İş `bitti` olunca `yuzde` 100'dür.

**Kurallar:**
- **Mevcut şirket atlanır, üzerine yazılmaz.** Güncelleme bu uç noktadan yapılamaz.
  Tek istisna: aynı anahtarın daha önce başlatıp **yarım bıraktığı** kurulum yeniden yüklenince tamamlanır.
- Şirket başına hata diğerlerini durdurmaz. `kuruldu` ama `ayrinti` doluysa şirket kuruldu
  fakat anahtar kapsamına eklenemedi — bize bildirin.
- Gönderdiğiniz ham veri iş bitince **sunucudan silinir**; yalnızca kurulum sonucu kalır.
- Aynı anda en fazla 5 bekleyen iş; fazlası `429`.

| Kod | Anlamı |
|---|---|
| 400 | Zip değil/bozuk, güvensiz yol (`../`), zip bomb şüphesi, parola korumalı, işlenecek şirket klasörü yok |
| 401 | Anahtar yok/geçersiz |
| 403 | Anahtarın onboard yetkisi yok |
| 404 | (`/musteri/isler/…`) iş yok ya da başka anahtara ait |
| 413 | Zip 200 MB sınırını aşıyor |
| 429 | Çok fazla bekleyen iş |

## 10. İlgili belgeler

- Canlı OpenAPI şeması: `http://<host>:8100/openapi.json`
