# v2 API Tasarımı — Gerekçe ve Plan

> **Tür:** explanation — v2 sözleşmesinin NEDEN böyle tasarlandığı.
> **Durum:** ✅ **Uygulandı** (2026-07-28). Kod yazıldı ve canlı sistemde
> uçtan uca doğrulandı.
>
> ✅ **Uygulandı** (2026-07-28): `entegrasyon/is_deposu.py` (PostgreSQL
> `api_jobs` tablosu), `entegrasyon/v2_semalar.py` (şema dönüşümü),
> `entegrasyon/v2_api.py` (4 endpoint + arka plan işçisi), `app.py`'ye router
> olarak bağlandı. Test: `model_eval/tests/test_v2_semalar.py` (18 test).
> Toplam paket: **223 test geçiyor**. Canlı doğrulama: gerçek fatura ile
> 202 → awaiting_approval → approve → completed akışı çalıştı; HTTP
> 400/404/409/422 kodları teyit edildi. v1 endpoint'leri bozulmadı.
> Teslim belgesi: `teslim/API-ENTEGRASYON-KILAVUZU-v2.md`.
>
> ⚠️ **GEÇİCİ DAVRANIŞ (2026-07-28, kullanıcı kararı) — `awaiting_approval`
> şu an devre dışı, tüm KDV uyarıları otomatik onaylanıyor.** Karşı sistemle
> onay haberleşmesinin formatı (senkron mu, webhook mu, hangi JSON şekli)
> henüz kararlaştırılmadığı için gerçek onay akışı beklemeye alındı. Bunun
> yerine `v2_api.py::_isi_calistir` içindeki `OTOMATIK_ONAY = True` bayrağı,
> KDV kontrolü uyarı verse bile akışı **kesmeden** devam ettiriyor. Kayıp
> olmasın diye:
> - Sonuçta `auto_approved: true` alanı eklenir (bu bayrak yoksa/`false` ise
>   normal — ya uyarı çıkmadı ya da gerçek onaydan geçti).
> - `vat_check` uyarısı **aynen korunur**, hiçbir bilgi kaybolmaz.
> - `warnings[]`'e açık bir not eklenir ("... OTOMATIK ONAYLANDI").
>
> **Geri alma:** `OTOMATIK_ONAY = False` yapmak yeterli — `awaiting_approval`
> durumu ve `POST .../approve` endpoint'i hiç kaldırılmadı, çalışır halde
> bekliyor (kod: `is_deposu.py::DURUMLAR`, `v2_api.py::isi_onayla`). Karşı
> sistemle onay formatı netleşince bu bayrağı kapatıp gerçek akışa dönülecek
> — bkz. konuşma geçmişi (2026-07-28): karşılıklı onay isteği/cevap formatı
> henüz tasarlanmadı, kullanıcı bilinçli olarak sonraya bıraktı.

## Neden v2?

Mevcut `POST /fatura/isle`, iç geliştirme aracı olarak doğdu ve bir dış
entegrasyon sözleşmesi olarak tasarlanmadı. Dış ekibe teslim belgesi yazarken
şu sorunlar ortaya çıktı — hiçbiri "belgeyi daha iyi yazmakla" çözülmez:

| # | Sorun | Somut etkisi |
|---|---|---|
| 1 | `satici_vkn` aslında `own_vkn` | Belgede "bu isim yanıltıcıdır" diye uyarı yazmak zorunda kaldık. İlk entegrasyonda kesin yanlış anlaşılır |
| 2 | Türkçe/İngilizce karışık | `asama`, `yon`, `onay` yanında `records`, `account_code`, `debit_credit` |
| 3 | Aynı veri üç yerde | `entries[]`, `records[]`, `dis_sema.records[]` — hangisi doğru kaynak belirsiz |
| 4 | Onay için tüm faturayı tekrar gönder | 500 KB XML ikinci kez ağdan geçiyor; oturum yok |
| 5 | Senkron 5–90 saniye | Proxy/LB timeout'ları devreye girebilir; toplu gönderimde kırılgan |
| 6 | `file_path` her zaman boş | Sözleşmede ölü alan |
| 7 | Uyarı da başarı da HTTP 200 | Ayrım gövdedeki `asama` alanında gizli — HTTP semantiği kullanılmıyor |

## Alınan kararlar (2026-07-27, kullanıcı)

1. **Temiz bir v2 endpoint yazılacak.** Mevcut `/fatura/isle` bozulmadan
   kalır (kendi test arayüzümüz onu kullanıyor). Dış ekibe **yalnızca v2**
   verilir.
2. **Asenkron desen:** `202 Accepted` + iş kimliği, ayrı durum sorgusu.

## v2 sözleşme taslağı

### Endpoint'ler

```
POST   /api/v1/invoices           → 202 + { job_id }        işi kuyruğa al
GET    /api/v1/invoices/{job_id}  → 200 durum + sonuç       durumu sorgula
POST   /api/v1/invoices/{job_id}/approve → 202              onay ver (XML tekrar gönderilmez)
GET    /api/v1/health             → 200                     sağlık
```

`/api/v1` öneki ve İngilizce yollar: sözleşme dilini tek tipe indirir.

### İstek (POST /api/v1/invoices)

```json
{
  "invoice_xml": "<?xml version=\"1.0\"?>...",
  "own_vkn": "0460351893",
  "seller_nace_codes": ["254004", "282210"],
  "currency_mode": "as_is"
}
```

| Eski ad | Yeni ad | Neden |
|---|---|---|
| `fatura_xml` | `invoice_xml` | Tutarlı İngilizce |
| `satici_vkn` | `own_vkn` | **Gerçek anlamını yansıtıyor** (sorun #1) |
| `satici_nace_kodlari` | `seller_nace_codes` | Tutarlı İngilizce |
| `kur_secimi` | `currency_mode` (`as_is` \| `try`) | Tutarlı İngilizce |
| `onay` | *(kaldırıldı)* | Onay artık ayrı endpoint (sorun #4) |

### Yanıt (GET /api/v1/invoices/{job_id})

```json
{
  "job_id": "01JQ8...",
  "status": "completed",
  "invoice": {
    "id": "AKA2025000000001",
    "issue_date": "2025-01-07",
    "currency": "TRY",
    "payable_amount": 58319.20,
    "direction": "outbound",
    "customer": { "vkn": "8441199152", "name": "TİMSAN..." },
    "supplier": { "vkn": "0460351893", "name": null }
  },
  "entries": [
    {
      "account_code": "120.01.00295",
      "account_type": "receivable",
      "account_name": "TİMSAN VINÇ...",
      "amount": 58319.20,
      "side": "debit",
      "reason": "...",
      "needs_review": false
    }
  ],
  "totals": { "debit": 58319.20, "credit": 58319.20, "balanced": true },
  "vat_check": { "verdict": "review_required", "lines": [ ... ] },
  "warnings": []
}
```

**Tek veri kaynağı** (sorun #3): yalnızca `entries[]`. `records`/`dis_sema`
tekrarı yok.

`status` değerleri: `queued` · `processing` · `awaiting_approval` ·
`awaiting_currency_choice` · `completed` · `failed`

Ek düzeltmeler:
- `side`: `"debit"`/`"credit"` — Türkçe BORÇ/ALACAK yerine (sorun #2)
- `account_type`: `"receivable"`/`"general"` — `C`/`G` kısaltması yerine
- `needs_review`: 3 haneli kalan kodlar için açık bayrak (belgede metinden
  çıkarma gereği kalkar)
- `direction`: `"outbound"`/`"inbound"` — `outbox`/`inbox` yerine
- `file_path` **kaldırıldı** (sorun #6)
- `supplier.name` `null` — boş string yerine "bilinmiyor" anlamı net

### HTTP semantiği (sorun #7)

| Durum | Kod |
|---|---|
| İş kabul edildi | `202 Accepted` + `Location` başlığı |
| Sonuç hazır | `200 OK` |
| İş henüz bitmedi | `200 OK` + `status: processing` |
| Onay bekliyor | `200 OK` + `status: awaiting_approval` |
| Geçersiz XML / şema | `400` / `422` |
| İş kimliği yok | `404` |
| Zaten onaylanmış işe tekrar onay | `409 Conflict` |
| Bağımlılık erişilemez | `503` |

## Asenkron desenin gerekçesi

Senkron çağrıda 5–90 saniye HTTP bağlantısı açık kalıyor. Ölçülen süreler:
4,7 / 29,6 / 30 / 85 saniye — **öngörülemez** (model uzak sunucuda, yükü
değişken).

Asenkron desende:
- Karşı taraf kuyruk kurmak zorunda kalmaz; `job_id` ile yoklar
- Proxy/LB timeout'ları devre dışı kalır
- Toplu gönderim doğal olarak desteklenir (N iş at, N kimlik topla)
- Kesinti sonrası devam edilebilir (iş kimliği kalıcı)

### İş deposu

PostgreSQL kullanılacak — zaten mevcut ve `model_eval_sonuclar` tablosunda
`JSONB` deseni var. Yeni tablo:

```sql
CREATE TABLE IF NOT EXISTS api_jobs (
    job_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    request      JSONB NOT NULL,     -- invoice_xml dahil (onayda tekrar gerekmez)
    result       JSONB,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`request` içinde XML saklanması sorun #4'ü çözer: onay verilirken istemci
XML'i tekrar göndermez.

> **Not:** Bu tablo `entegrasyon/` bileşenine ait olacak — mevcut kurala göre
> (`System/CLAUDE.md` §4) her bileşen kendi tablolarını kullanır, başkasının
> tablosuna dokunmaz. `api_` öneki bu ayrımı korur.

## Kapsam dışı bırakılanlar

- **Kimlik doğrulama:** ayrı bir iş; v2 tasarımı buna hazır (başlık tabanlı
  token kolayca eklenebilir) ama bu turda yapılmıyor.
- **Mevcut `/fatura/isle`:** dokunulmuyor. Test arayüzümüz onu kullanmaya
  devam eder; 205 test de ona bağlı.
- **İç şema (`entries[]` + `dc`):** değişmiyor. v2, mevcut
  `core/disa_aktarim.py` deseniyle iç şemadan TÜRETİLİR.

## Uygulama sırası

1. `api_jobs` tablosu + iş deposu modülü (`entegrasyon/is_deposu.py`)
2. v2 şema modelleri (`entegrasyon/v2_semalar.py`) — iç şemadan dönüşüm
3. v2 endpoint'leri (`entegrasyon/v2_api.py`), `app.py`'ye router olarak bağla
4. Arka plan işçisi (FastAPI `BackgroundTasks` ya da ayrı süreç)
5. Testler: şema dönüşümü + durum geçişleri + onay akışı
6. Yeni teslim belgesi (mevcut kılavuz v1 olarak arşivlenir)
