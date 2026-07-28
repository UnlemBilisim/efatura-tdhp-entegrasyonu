# Dış Ekip API Kullanımı — `POST /fatura/isle`

> **Tür:** reference — kesin teknik başvuru, kodla birebir senkron olmalı.
> **Uygulayan:** [`entegrasyon/app.py`](../../app.py) (`FaturaIsleIstegi`,
> `FaturaIsleCevabi`), çıktı şeması
> [`model_eval/core/disa_aktarim.py`](../../../model_eval/core/disa_aktarim.py)
>
> ✅ **Doğrulandı** (2026-07-27): Aşağıdaki tüm istek/cevap örnekleri canlı
> servise gerçek faturalarla atılıp gözlemlendi (outbox + inbox + onaysız
> çağrı senaryoları).

Bu belge, muhasebe kaydı üretmek isteyen dış ekibin bilmesi gereken tek
şeydir. Servis, e-fatura XML'ini alıp muhasebe kayıtlarını (`records[]`)
döner.

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

## 1. Endpoint

```
POST http://<host>:8100/fatura/isle
Content-Type: application/json
```

Kimlik doğrulama şu an **yok** (bkz. §6 Güvenlik).

## 2. İstek gövdesi

| Alan | Tip | Zorunlu | Açıklama |
|---|---|---|---|
| `fatura_xml` | string | **Evet** | UBL-TR fatura XML'inin tamamı (ham metin) |
| `satici_vkn` | string | **Evet** | **Kendi şirketinizin VKN'si** — aşağıya bakın |
| `satici_nace_kodlari` | string[] | Hayır | Satıcının NACE kodları; yalnızca outbox'ta kullanılır. Noktalı (`"25.40.04"`) veya noktasız (`"254004"`) gönderilebilir — Mcp_mimarisi 2026-07-28'den beri ikisini de aynı koda normalize ediyor (bkz. `Mcp_mimarisi/docs/reference/nace-kdv-excel-yapisi.md`) |
| `onay` | boolean | Hayır | Uyarıya rağmen devam; **outbox'ta gerekebilir** (§4) |
| `kur_secimi` | string | Hayır | `"orijinal"` \| `"tl"` — TL dışı faturalarda (§5) |

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

### `records[]` alanları

| Alan | Açıklama |
|---|---|
| `account_code` | TDHP kodu, alt kırılımlı (`191.01.00020`). Çözülemezse 3 haneli kalır (`320`) |
| `account_code_type` | `C` = cari hesap (120/320/340/440/159/420), `G` = diğer |
| `account_description` | Mizandaki hesap adı. Bilinmiyorsa **boş string** (`null` değil) |
| `account_code_reason` | Kodun neden seçildiği. **Asla boş kalmaz** |
| `amount` | Tutar |
| `debit_credit` | `"BORÇ"` \| `"ALACAK"` |

### Zarf alanları

- `customer` / `supplier` — **yöne göre** yerleşir. outbox'ta karşı taraf
  `customer`, inbox'ta `supplier` olur. Kendi tarafınızda yalnızca `id` dolu,
  `name` boş string (fatura XML'i kendi unvanınızı taşımıyor).
- `success` — tahmin hatasız tamamlandıysa `true`.
- `file_path` — şu an **her zaman boş string**; servis ham XML alıyor, dosya
  yolu bilmiyor. Bu alan size gerekiyorsa haber verin.

## 4. Önemli: outbox faturalarda iki adımlı akış

> ✅ **Uygulandı** (2026-07-28): Aşağıdaki akış `entegrasyon/app.py::fatura_isle`
> satır 333-397 ile birebir doğrulandı. `devam_etsin` koşulu (satır 333-335)
> tam olarak burada anlatılan iki dalı üretir; `genel_karar` değeri
> `Mcp_mimarisi/src/efatura_kdv/kalem_nace_esleme.py::SatirKararTuru`'dan gelir
> ve Faz 1'de **bilerek sadece iki değer** vardır (`uygun` /
> `insan_incelemesi_gerekli`) — kesin `uyumsuz` bu fazda hiç üretilmez.
> İnbox faturalarda `asama` doğrudan `tdhp_tahmini_tamamlandi` döner (ayrı bir
> "atlandı" aşama değeri **yoktur**, sadece `mesaj` alanı farklılaşır) —
> `entegrasyon/app.py:187-190`'daki eski docstring bunu yanlış listeliyordu,
> bu oturumda düzeltildi.

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

**Hata durumları.**

| Kod | Anlamı |
|---|---|
| 400 | Bozuk XML, VKN uyuşmazlığı, yön belirlenemedi |
| 501 | `model_eval` hazır değil (sistem eksik kurulmuş) |
| 502 | Ön filtreleme servisi (Mcp_mimarisi) erişilemiyor |

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

## 7. İlgili belgeler

- Çıktı şemasının tam sözleşmesi ve `account_code_reason` üretim kuralları:
  [`model_eval/docs/reference/dis-ekip-kayit-semasi.md`](../../../model_eval/docs/reference/dis-ekip-kayit-semasi.md)
- Sistem mimarisi (neden iki aşamalı):
  [`../../../../MIMARI.md`](../../../../MIMARI.md)
- Canlı OpenAPI şeması: `http://localhost:8100/openapi.json`
