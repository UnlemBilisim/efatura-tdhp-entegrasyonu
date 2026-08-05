# Dış Ekip API Kullanımı — `POST /fatura/isle`

> **Tür:** reference — kesin teknik başvuru, kodla birebir senkron olmalı.
> **Uygulayan:** [`entegrasyon/app.py`](../../app.py) (`FaturaIsleIstegi`,
> `FaturaIsleCevabi`), çıktı şeması
> [`model_eval/core/disa_aktarim.py`](../../../model_eval/core/disa_aktarim.py)
>
> ✅ **Doğrulandı** (2026-08-05): Bu belge, önceden ayrı duran
> `model_eval/docs/reference/dis-ekip-kayit-semasi.md`'nin içeriğiyle
> BİRLEŞTİRİLDİ (dış ekibe tek dosya olarak teslim edilmesi için, kullanıcı
> kararı) — `records[]` şemasının tam detayı ve `account_code_reason` üretim
> kuralları artık §3.1'de. İki belge de `entegrasyon/app.py`'nin bu tarihteki
> hâliyle satır satır karşılaştırılıp güncellendi.
>
> ✅ **Doğrulandı** (2026-08-04): `GET /durum`, `GET /kayitli-sirketler`,
> `POST /fatura/onayla` eklendi, `dosya_adi` alanı ve VKN-onboarding notu
> eklendi. Önceki "2026-07-27 Doğrulandı" damgası bu tarihe kadar bayat
> kalmıştı (kod 4 gün içinde değişti, belge değişmedi) — bkz. kök CLAUDE.MD
> §1 "kritik değişiklik sonrası docs güncelleme aynı görevin parçasıdır" kuralı.

Bu belge, muhasebe kaydı üretmek isteyen dış ekibin bilmesi gereken **tek
kaynaktır** — API sözleşmesi ve çıktı şemasının tam detayı bir aradadır.
Servis, e-fatura XML'ini alıp muhasebe kayıtlarını (`records[]`) döner.

---

## 0. Sorumluluk paylaşımı

| Taraf | Sorumluluk |
|---|---|
| **Biz (backend)** | `POST /fatura/isle` — fatura XML → muhasebe kaydı (`dis_sema`) |
| **Dış ekip (frontend)** | Kullanıcı arayüzü, dosya yükleme, sonucun gösterimi |

> ✅ **Netleştirildi** (2026-07-27, kullanıcı kararı): Arayüzü dış ekip
> yazacak; biz yalnızca backend'i teslim ediyoruz.

**Çağrı şekli: sunucu-sunucu.** Dış ekibin backend'i bizim API'yi çağırır;
istek tarayıcıdan **gelmez**. Bu yüzden CORS yapılandırması **bilinçli olarak
yapılmamıştır** — tarayıcıdan doğrudan `fetch` denenirse preflight `405` döner
ve istek başarısız olur. Mimari değişip tarayıcıdan çağrı gerekirse haber
verin; `CORSMiddleware` eklenmesi gerekir.

`entegrasyon/static/index.html` bizim **kendi manuel test arayüzümüzdür** —
teslim kapsamında değildir, referans olarak kullanılmamalıdır.

> ⚠️ **Arayüzü yazarken:** Fatura alanları (kalem adı, tedarikçi unvanı, not
> alanı) **güvenilmeyen veridir** — faturayı gönderen dış taraf yazmıştır ve
> HTML/script içerebilir. Bunları DOM'a basarken escape edin (`textContent`,
> React/Vue'nun varsayılan escape'i) — `innerHTML` ile ham basmak XSS'e yol
> açar. Bizim test arayüzümüzde bu açık **mevcuttur** (yalnızca yerel
> kullanım olduğu için kabul edilmiştir); onu kopyalamayın.

## 1. Endpoint'ler

```
GET  http://<host>:8100/durum              — sağlık kontrolü
GET  http://<host>:8100/kayitli-sirketler  — bilinen VKN listesi (bkz. §2.1)
POST http://<host>:8100/fatura/isle        — asıl tahmin (bu belgenin konusu)
POST http://<host>:8100/fatura/onayla      — tahmini kalıcı kayıt/RAG'a al (§7)
```

> ⚠️ **Gerçek adres henüz iletilmedi.** `<host>` bir yer tutucudur — dağıtım
> adresi (IP/domain/tünel) netleşince ayrı bir kanaldan bildirilecektir.

Kimlik doğrulama şu an **yok** (bkz. §6 Güvenlik). `POST /fatura/isle`
detayları aşağıda; diğer üçü ayrı bölümlerde (§2.1, §7) anlatılıyor.

```
POST /fatura/isle
Content-Type: application/json
```

## 2. İstek gövdesi

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `fatura_xml` | string | **Evet** | UBL-TR fatura XML'inin tamamı (ham metin) |
| `satici_vkn` | string | **Evet** | **Kendi şirketinizin VKN'si** — aşağıya bakın |
| `satici_nace_kodlari` | string[] | Hayır | Satıcının NACE kodları; yalnızca outbox'ta kullanılır. Noktalı (`"25.40.04"`) veya noktasız (`"254004"`) gönderilebilir — Mcp_mimarisi 2026-07-28'den beri ikisini de aynı koda normalize ediyor (bkz. `Mcp_mimarisi/docs/reference/nace-kdv-excel-yapisi.md`) |
| `onay` | boolean | Hayır | Uyarıya rağmen devam; **outbox'ta gerekebilir** (§4) |
| `kur_secimi` | string | Hayır | `"orijinal"` \| `"tl"` — TL dışı faturalarda (§5) |
| `dosya_adi` | string | Hayır | Yüklenen XML dosyasının orijinal adı. Sadece izleme/loglama amaçlı — işleme mantığını etkilemez, boş bırakılabilir |

### 2.1 `GET /kayitli-sirketler` — hangi VKN'ler bizde tanımlı

```json
{"vkn_listesi": ["0460351893", "1111111111"]}
```

Sistem çoklu şirket (tenant) destekliyor; her `satici_vkn` kendi izole
şemasına/mizanına/geçmiş fatura havuzuna sahiptir. **Bu endpoint, hangi
VKN'lerin bizim tarafımızda önceden onboard edildiğini gösterir.**

> ⚠️ **Onboard edilmemiş bir VKN göndermek hata VERMEZ, ama sonuç kalitesi
> düşer.** O VKN'nin mizanı/geçmiş faturası yoksa sistem "emsal yok" yoluna
> düşer — sadece 3 haneli TDHP ana kodunu üretir, alt kırılım (muavin hesap)
> çözülemez ve `account_code_reason` bunu açıkça söyler. Kayıt hatalı değildir,
> sadece daha az detaylıdır. Yeni bir şirket için önce bizimle iletişime
> geçip onboard edilmesini isteyin, aksi halde ilk faturalar eksik kalır.

> ⚠️ **`satici_vkn` yanıltıcı bir isimdir.** Fatura üzerindeki satıcının VKN'si
> değil, **isteği yapan şirketin kendi VKN'si**dir (tarihsel isim; kod içinde
> `own_vkn` anlamında kullanılır). Sistem bu değeri XML'deki taraflarla
> karşılaştırıp faturanın yönünü belirler:
> - Kendi VKN'niz **satıcı** tarafındaysa → `outbox` (siz kestiniz)
> - Kendi VKN'niz **alıcı** tarafındaysa → `inbox` (size geldi)

### En basit istek

```bash
curl -X POST http://localhost:8100/fatura/isle \
  -H "Content-Type: application/json" \
  -d '{
    "fatura_xml": "<?xml version=\"1.0\"?><Invoice ...>",
    "satici_vkn": "0460351893"
  }'
```

Python ile (XML'i dosyadan okuyarak):

```python
import json, requests

with open("fatura.xml", encoding="utf-8") as f:
    xml = f.read()

r = requests.post(
    "http://localhost:8100/fatura/isle",
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
      "debit_credit": "BORÇ"
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
  `name` boş string (fatura XML'i kendi unvanınızı taşımıyor — parser yalnızca
  karşı tarafı tutuyor).
- `success` — tahmin hatasız tamamlandıysa `true`.
- `file_path` — şu an **her zaman boş string**; servis ham XML alıyor, dosya
  yolu bilmiyor. Bu alan size gerekiyorsa istek gövdesine eklenmesi gerekir,
  haber verin.

### 3.1 `records[]` — tam şema ve üretim kuralları

> **Uygulayan:** [`model_eval/core/disa_aktarim.py`](../../../model_eval/core/disa_aktarim.py),
> [`model_eval/core/single.py::_entry_dicts_uygula`](../../../model_eval/core/single.py)
>
> ✅ **Uygulandı** (2026-07-27): Sözleşme kodda uygulandı ve test edildi
> (`model_eval/tests/test_disa_aktarim.py`, 21 test). **Canlı doğrulama:**
> gerçek bir fatura (`AKA2025000000001`) `POST /fatura/isle` ile işlendi;
> `records[]` alan kümesi karşı tarafın örnek JSON'uyla birebir eşleşti.

Dış ekip, muhasebe kayıtlarını kendi alan adlarıyla istiyor. `model_eval`'ın
iç şeması (`entries[]`) farklı — bu bölüm iki şema arasındaki **tek yönlü**
dönüşümü tanımlar.

**İç şema neden değişmedi:** `entries[]` ve `dc="Borc"/"Alacak"` değerlerine
200+ test, ChromaDB RAG kayıtları ve `model_eval_sonuclar` tablosu bağlı. İç
şemayı değiştirmek bunların hepsini kırardı. Bunun yerine dışa aktarımda tek
yönlü dönüşüm yapılır: **iç şema serbest kalır, dış sözleşme sabitlenir.**

Her `records[]` öğesi **tam olarak** şu 6 alanı taşır — eksik veya fazla alan yok:

| Alan | Tip | Açıklama |
|---|---|---|
| `account_code` | string | TDHP hesap kodu, alt kırılımlı (`"191.01.00020"`). Alt kırılım çözülemezse 3 haneli kalır (`"320"`). |
| `account_code_type` | string | `"C"` = cari hesap, `"G"` = diğer. Ana kod `CARI_HESAP_KODLARI` (120/320/340/440/159/420) içindeyse `C`. |
| `account_description` | string | Mizandaki HESAP ADI (`"%20 İndirilecek KDV"`). Bilinmiyorsa **boş string** — `null` değil. |
| `account_code_reason` | string | Kodun neden seçildiği. **Asla boş kalmaz.** |
| `amount` | number | Tutar — dönüşümde değiştirilmez. |
| `debit_credit` | string | `"BORÇ"` / `"ALACAK"` (iç şemadaki `"Borc"`/`"Alacak"`ın karşılığı). |

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

**Deterministik üretilir — LLM'e sorulmaz** (kullanıcı kararı, 2026-07-27).
Modele "bu kodu neden seçtin" diye sormak *post-hoc rasyonalizasyon* riski
taşır — model kodu bir sebeple seçip tamamen başka bir sebep yazabilir.
Gerekçe, kodun gerçekten nereden geldiğinin izinden (`secim_kaynagi`) türetilir:

| Durum (`secim_kaynagi.kaynak`) | Üretilen gerekçe |
|---|---|
| `"fuzzy"` | "Karşı taraf unvanı mizandaki '…' kaydıyla eşleşti (isim benzerliği %N); aynı cari hesap kullanıldı." |
| `"llm"` + `oran_duzeltildi=True` | "Hesap türü geçmiş emsal faturalara göre seçildi; alt kırılım, faturadaki gerçek KDV oranına göre … olarak düzeltildi." |
| `"llm"` + `emsal_sayisi>0` | "Aynı tedarikçi/müşteri ile yapılan N geçmiş benzer faturada kullanılan hesap kırılımı esas alındı." |
| `"llm"` (emsalsiz) | "Faturadaki kalem açıklaması ve mizandaki alt kırılım adları eşleştirilerek seçildi." |
| Kod 3 hanede kaldı + `uyari` var | "… için mizanda eşleşen alt kırılım (cari kart) bulunamadı; ana hesap kodunda bırakıldı — yeni müşteri/tedarikçi olabilir." |
| Kod 3 hanede kaldı, uyarı yok | "… ana hesap kodu kullanıldı; mizanda bu kod için seçilebilecek bir alt kırılım bulunamadı." |
| İz yok | "Faturadaki kalem bilgisi ile mizandaki hesap planı eşleştirilerek seçildi." |

#### `uyari` alanının dış şemadaki karşılığı

Dış şemada ayrı bir uyarı alanı **yok**. İç şemadaki `uyari` (karşı taraf
mizanda bulunamadı) bilgisi kaybolmasın diye gerekçenin sonuna `UYARI: …`
olarak eklenir. Gerekçe zaten bu durumu anlatıyorsa (3 hanede kalma
senaryosu) **tekrar eklenmez.**

#### Değişmez kurallar (backend tarafında — bilgi amaçlı)

1. İç şema (`entries[]`, `dc="Borc"/"Alacak"`) değiştirilmez; dönüşüm yalnızca
   `core/disa_aktarim.py`'de yapılır.
2. Dönüşüm `amount` ve `account_code` değerlerini değiştirmez — sadece alan
   adlarını çevirir ve türetilmiş alanları ekler.
3. `account_description` bilinmiyorsa boş string döner, `null` değil — tip
   tutarlılığına güvenebilirsiniz.

#### Bilinen sınır

`emsal_sayisi` parametresi şu an backend'den **geçirilmiyor** (varsayılan
`0`), çünkü RAG'ın kaç emsal kullandığı bilgisi tahmin çıktısında dönmüyor.
Bu yüzden "N geçmiş benzer faturada kullanılan…" gerekçesi henüz üretilmiyor;
onun yerine emsalsiz LLM gerekçesi yazılıyor.

## 4. Önemli: outbox faturalarda iki adımlı akış

> ✅ **Uygulandı** (2026-07-28): Aşağıdaki akış `entegrasyon/app.py::fatura_isle`
> ile birebir doğrulandı. `devam_etsin` koşulu tam olarak burada anlatılan iki
> dalı üretir; `genel_karar` değeri
> `Mcp_mimarisi/src/efatura_kdv/kalem_nace_esleme.py::SatirKararTuru`'dan gelir
> ve Faz 1'de **bilerek sadece iki değer** vardır (`uygun` /
> `insan_incelemesi_gerekli`) — kesin `uyumsuz` bu fazda hiç üretilmez.
> İnbox faturalarda `asama` doğrudan `tdhp_tahmini_tamamlandi` döner (ayrı bir
> "atlandı" aşama değeri **yoktur**, sadece `mesaj` alanı farklılaşır).

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
| 502 | Ön filtreleme servisi (Mcp_mimarisi) erişilemiyor |

`model_eval` hazır değilse `/fatura/isle` **200 döner**, `asama` alanı
`"model_eval_hazir_degil"` olur (bkz. §4 karar ağacı) — bu, `/fatura/onayla`
davranışından farklıdır, o gerçek bir `501` döner (§7).

`success: false` + dolu `error` alanı: tahmin üretilemedi (ör. LLM
erişilemedi). Bu durumda `records[]` boş olur — **boş listeyi "kayıt yok"
diye yorumlamayın**, `success`'i kontrol edin.

**Güvenlik (2026-07-27 durumu).** Servis şu an kimlik doğrulama içermiyor ve
`0.0.0.0`'a bind ediliyor — yani API'ye erişebilen herkes fatura işletebilir.
Bu belge **iç ağdaki test entegrasyonu** için yazılmıştır. Üretime çıkmadan
önce en az şu ikisi gerekli:

1. Kimlik doğrulama (API key ya da servis-hesabı token'ı) — çağrı
   sunucu-sunucu olduğu için paylaşılan bir sır yeterli.
2. Servisin `127.0.0.1`'e bind edilmesi ya da ağ seviyesinde kısıtlanması.

Bunlar bizim tarafımızda yapılacak işlerdir; entegrasyonu etkileyeceği için
(istek başlığına token eklenmesi) zamanı geldiğinde haber vereceğiz.

**Uyarılar kaybolmaz.** Bir cari hesap mizanda bulunamazsa (yeni
müşteri/tedarikçi) kod 3 haneli kalır ve uyarı `account_code_reason` metninin
içine yazılır. `account_code`'da nokta yoksa alt kırılım çözülememiştir —
muhasebecinin kontrol etmesi gerekir.

## 7. `POST /fatura/onayla` — tahmini kalıcı hâle getirme (opsiyonel)

`POST /fatura/isle`'ın döndürdüğü tahmin **hiçbir yere kaydedilmez** —
sonucu görüp değerlendirmeniz için üretilir, kalıcı değildir. Kullanıcınız
(muhasebeci) tahmini "doğru" olarak onaylarsa, **aynı tahmini** bu endpoint'e
göndererek iki şeyi tetiklersiniz:

1. Kayıt PostgreSQL'e (denetim/geçmiş amaçlı) yazılır.
2. Kayıt RAG (emsal) veritabanına eklenir — **gelecekteki benzer faturaların
   tahmin kalitesini artırır.** Onay adımını atlarsanız sisteminiz zamanla
   emsal biriktirmez, tahmin kalitesi sabit kalır.

```
POST /fatura/onayla
Content-Type: application/json
```

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `fatura_xml` | string | **Evet** | `/fatura/isle`'a gönderdiğiniz AYNI XML |
| `satici_vkn` | string | **Evet** | `/fatura/isle`'a gönderdiğiniz AYNI VKN |
| `tdhp_tahmini` | object | **Evet** | `/fatura/isle` cevabındaki `tdhp_tahmini` alanının **aynen geri gönderilmiş hâli** (sunucu tekrar LLM'e gitmez, sadece bu veriyi kaydeder) |

Cevap:

```json
{"kaydedildi": true, "mesaj": "Fatura onaylandı — PostgreSQL'e kaydedildi ve RAG vektör veritabanına eklendi."}
```

`501` döner (`model_eval` hazır değilse) — bu, `/fatura/isle`'daki
`asama: "model_eval_hazir_degil"` davranışından **farklıdır**: `/fatura/isle`
bu durumda 200 + özel bir `asama` değeriyle "eksik ama hata değil" der,
`/fatura/onayla` ise gerçek bir HTTP hata kodu (501) döner çünkü kaydedecek
bir şey olmadan devam edemez.

## 8. İlgili belgeler

- Sistem mimarisi (neden iki aşamalı):
  [`../../../../mimari.md`](../../../../mimari.md)
- Canlı OpenAPI şeması: `http://localhost:8100/openapi.json`
