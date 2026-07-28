# API Şeması (Faz 1 HTTP arayüzü)

Kod: `src/efatura_kdv/api.py`. Çalıştırma: `docs/how-to/api-calistirma.md`.

## Hata yönetimi — genel kurallar (2026-07-22)

> ✅ **Uygulandı (2026-07-22):** `src/efatura_kdv/api.py`'deki
> `_db_down_handler`, `_pool_exhausted_handler`, `_beklenmeyen_hata_handler`
> (bkz. `GOREV_MIMARI_DUZELTME.md` #4). Önceden bir `except Exception` bloğu
> ham hata metnini (`detail=f"...{exc}"`) doğrudan client'a veriyordu — DB
> bağlantı dizesi, tablo/kolon adı gibi iç detaylar sızabiliyordu.

Aşağıdaki durumlar tüm endpoint'lerde ORTAK, endpoint'e özel `try/except`
gerekmeden ele alınır (FastAPI `exception_handler`):

| Durum | HTTP kodu | Client'a giden | Sunucu logu |
|---|---|---|---|
| DB'ye bağlanılamıyor (`psycopg2.OperationalError` — sunucu kapalı, ağ hatası) | `503` | Generic mesaj | Ham hata `logging.exception` ile |
| Connection pool tükendi (`psycopg2.pool.PoolError` — eşzamanlı istek `maxconn`'u aştı) | `503` | Generic mesaj | Ham hata `logging.exception` ile |
| Başka herhangi bir beklenmeyen exception | `500` | Generic mesaj | Ham hata `logging.exception` ile |
| `HTTPException` (kod içinde bilinçli fırlatılan — bozuk XML, VKN uyuşmazlığı) | fırlatıldığı kod | O endpoint'in kendi `detail` mesajı (değişmedi) | — |

**Ham exception metni hiçbir zaman client'a gitmez** (HTTPException hariç —
o zaten bilinçli, güvenli bir mesajla fırlatılıyor). Gerçek hata detayı
sadece sunucu logunda (`_logger.exception(...)`, traceback dahil).

> ✅ **Gerçek Postgres ile doğrulandı:** `docker stop efatura-kdv-postgres`
> ile DB kapatılıp `/fatura/gecmis-kontrol`'e istek atıldı → `503` +
> `"Veritabanına şu an ulaşılamıyor..."` (ham `OperationalError` metni
> sızmadı). DB tekrar başlatılınca (`docker start`) aynı istek `200` ile
> normale döndü — pool otomatik olarak yeni bağlantı kuruyor, ek bir
> "stale connection" temizliği gerekmiyor.

## `GET /saglik`

Sağlık kontrolü — yük dengeleyici/orkestrasyon için.

**Cevap:**
```json
{"durum": "ayakta", "nace_tablosu_yuklu": true}
```

## `POST /fatura/kontrol-et`

Ham UBL-TR XML'ini ve satıcının NACE kod(lar)ını alıp kalem bazlı KDV oran
kontrolü sonucunu döner. İş mantığı: `kalem_nace_esleme.satir_bazli_kontrol_et()`
(bkz. `docs/explanation/akis-sirasi-ve-faz-plani.md`).

**İstek gövdesi:**

| Alan | Tip | Açıklama |
|---|---|---|
| `fatura_xml` | string | Ham UBL-TR XML metni (dosya değil, string) |
| `satici_vkn` | string | Satıcının VKN'si — faturanın gerçek satıcı VKN'siyle uyuşmalı, uyuşmazsa 400 |
| `satici_nace_kodlari` | string[] | Satıcının tüm NACE kod(lar)ı — dışarıdan gelir, bu API VKN→NACE lookup yapmaz |

**Cevap gövdesi (200):**

| Alan | Tip | Açıklama |
|---|---|---|
| `fatura_no` | string\|null | |
| `uuid` | string\|null | |
| `satici_vkn` | string\|null | |
| `genel_karar` | `"uygun"` \| `"insan_incelemesi_gerekli"` | Herhangi bir satır insan incelemesi gerektiriyorsa fatura geneli de öyle |
| `satir_sonuclari` | object[] | Her kalem için ayrı sonuç, aşağıdaki şema |

**`satir_sonuclari[]` şeması:**

| Alan | Tip | Açıklama |
|---|---|---|
| `kalem_sira_no` | string\|null | |
| `kalem_adi` | string\|null | |
| `beyan_edilen_oranlar` | float[] | Kalemin beyan ettiği KDV oran(lar)ı |
| `nace_kodlari_kontrol_edildi` | string[] | Satıcının NACE kodlarından referans tabloda bulunanlar |
| `izin_verilen_oranlar_havuzu` | float[] | Bulunan NACE'lerin izin verdiği oranların birleşik havuzu |
| `karar` | `"uygun"` \| `"insan_incelemesi_gerekli"` | |
| `gerekce` | string | İnsan-okunur açıklama (hangi NACE hangi oranı destekliyor / neden uyuşmuyor) |

**Hata durumları:**

| HTTP kodu | Sebep |
|---|---|
| `400` | XML ayrıştırılamadı (bozuk/geçersiz XML) |
| `400` | `satici_vkn`, faturanın gerçek satıcı VKN'siyle uyuşmuyor (yanlış satıcıya ait NACE bilgisiyle karşılaştırma önlenir — bkz. `kalem_nace_esleme.py` güvenlik kontrolü) |

> ✅ **Uygulandı (2026-07-21):** Bu şema `src/efatura_kdv/api.py`'deki
> Pydantic modelleriyle (`FaturaKontrolIstegi`, `FaturaKontrolCevabi`,
> `SatirSonucCevabi`) birebir eşleşir. Önce mock PostgreSQL bağlantısıyla
> (`unittest.mock`), sonra kullanıcı Docker'ı kurup Postgres container'ını
> ayağa kaldırdıktan sonra **gerçek** bir PostgreSQL bağlantısıyla
> (`docker run postgres:16`, port 5434 — bkz. `docs/how-to/postgres-kurulum.md`)
> uçtan uca test edildi: `curl` ile gerçek HTTP isteği → doğru `uygun`
> kararı, 5 eşzamanlı istek → tutarlı sonuç, bozuk XML → 400, VKN
> uyuşmazlığı → 400.

## `POST /fatura/gecmis-kontrol`

Her kalem için, satıcının **geçmişte (outbox faturalarda)** bu kalemi hangi
oran(lar)la kestiğini döner. **KARAR ÜRETMEZ** — `/fatura/kontrol-et`'in
ürettiği karara dokunmaz, sadece bilgi/uyarı notu döner. Ayrı bir
endpoint'tir, ana kontrol akışıyla otomatik tetiklenmez. Mimari karar ve
gerekçe: `PROJECT.md` §3.9, şema: `docs/reference/gecmis-fatura-semasi.md`.

**İstek gövdesi:**

| Alan | Tip | Açıklama |
|---|---|---|
| `satici_vkn` | string | Satıcının VKN'si |
| `kalemler` | object[] | `{kalem_adi: string, beyan_edilen_oranlar: float[]}` listesi |

**Cevap gövdesi (200) — istekteki `kalemler` sırasıyla eşleşen liste:**

| Alan | Tip | Açıklama |
|---|---|---|
| `kalem_adi` | string\|null | |
| `beyan_edilen_oranlar` | float[] | İstekte gönderilen oran(lar) |
| `gecmis_oranlar` | object[] | `{oran, kac_kez, son_gorulme_tarihi}` — geçmişte görülen her oran için özet |
| `gecmiste_hic_gorulmus_mu` | bool | Bu kalem adı geçmiş faturalarda hiç geçmiş mi |
| `gecmisle_uyusuyor_mu` | bool\|null | Beyan edilen oran geçmiştekilerden biriyle eşleşiyor mu; geçmiş veri hiç yoksa `null` |
| `bilgi_notu` | string | İnsan-okunur özet/uyarı metni |

**Kapsam sınırı:** Sadece `outbox` (bizim kestiğimiz) faturalar kaydedilir
— 380 dosyanın 377'si (939 kalem-oran satırı); 3 dosya ne kalemde ne
genelde KDV oran bilgisi taşımadığı için atlandı (gerçek veri eksikliği).
Eşleşme normalize edilmiş (küçük harf + boşluk temizleme) TAM string
eşleşmesidir — bulanık/benzerlik skoru kullanılmaz.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):**
> `src/efatura_kdv/gecmis_kontrol.py` + `scripts/gecmis_faturalari_yukle.py`
> yazıldı, gerçek DB ile 3 senaryoda (uyumlu/uyarı/hiç görülmemiş) hem
> doğrudan Python çağrısıyla hem gerçek `curl` HTTP isteğiyle test edildi.
> `/fatura/kontrol-et`'in kararının bu yeni katmandan etkilenmediği ayrıca
> doğrulandı (aynı fatura, aynı karar).

## `POST /fatura/coklu-kontrol`

Aynı satıcı VKN + NACE kod(lar)ıyla **BİRDEN FAZLA** fatura XML'ini tek
istekte kontrol eder — MVP kapsamında eklendi (2026-07-21, kullanıcı
kararı): muhasebeci her oturumda tek bir şirketin tüm faturalarını (aynı
satıcı VKN + o şirketin tüm NACE kodları) toplu yükleyebilsin diye.

Her fatura için: (1) NACE kural kontrolü çalışır (`/fatura/kontrol-et` ile
birebir aynı mantık, `_tek_fatura_kontrol_et()` ortak yardımcı fonksiyon
üzerinden — kod tekrarı yok), (2) her kalem için geçmiş çapraz kontrolü
çalışır, (3) fatura **BAŞARIYLA** kontrol edildiyse (VKN uyuşmazlığı/parse
hatası YOKSA) kalem-oran satırları **otomatik olarak**
`gecmis_fatura_kalemleri` tablosuna kaydedilir.

**Kaydetme güvenliği:** `satir_bazli_kontrol_et()` zaten `satici_vkn`'nin
faturanın GERÇEK satıcı VKN'siyle eşleştiğini garanti ediyor (eşleşmezse
`ValueError` → bu fatura `basarili=false` olarak işaretlenir, hiç
kaydedilmez) — yani otomatik kayda giren her fatura kullanıcının **kendi
kestiği** faturadır (outbox), PROJECT.md §3.9'daki kapsam korunur. Aynı
`fatura_no` zaten kayıtlıysa tekrar eklenmez (yinelenen yükleme "kaç kez
kesilmiş" istatistiğini şişirmesin diye).

**İstek gövdesi:**

| Alan | Tip | Açıklama |
|---|---|---|
| `fatura_xml_listesi` | string[] | Birden fazla ham UBL-TR XML metni |
| `satici_vkn` | string | Kullanıcının kendi şirketinin VKN'si — her faturanın GERÇEK satıcı VKN'siyle karşılaştırılır |
| `satici_nace_kodlari` | string[] | Şirketin tüm NACE kod(lar)ı — tüm faturalar için aynı kullanılır |

**Cevap gövdesi (200) — `fatura_xml_listesi` sırasıyla eşleşen liste:**

| Alan | Tip | Açıklama |
|---|---|---|
| `dosya_index` | int | İstekteki sıra (0-tabanlı) |
| `basarili` | bool | Bu fatura başarıyla kontrol edildi mi |
| `hata` | string\|null | Başarısızsa hata mesajı (bozuk XML veya VKN uyuşmazlığı) |
| `fatura_kontrol` | object\|null | Başarılıysa `/fatura/kontrol-et` ile birebir aynı şema |
| `gecmis_kontrolleri` | object[] | Her kalem için `/fatura/gecmis-kontrol` ile birebir aynı şema |
| `gecmise_kaydedildi` | bool | Bu fatura az önce ilk kez geçmiş veritabanına yazıldı mı (`false` = zaten kayıtlıydı ya da başarısızdı) |

**Önemli — bir fatura başarısız olursa TÜM istek düşmez:** o faturanın
sonucu `basarili=false` + `hata` alanıyla işaretlenir, diğer faturalar
işlenmeye devam eder (gerçek `curl` testiyle doğrulandı: 1 geçerli + 1 bozuk
XML aynı istekte gönderildi, geçerli olan başarıyla işlendi).

> ⚠️ **Kritik hata bulundu ve düzeltildi (2026-07-21, aynı gün):** Web
> arayüzünün ilk sürümünde (bu endpoint'in kod tabanı paylaştığı
> `test/web_arayuz.py`) kullanıcının kendi şirket VKN'sini ayrıca girmesi
> gerekiyordu ama form bunu hiç sormuyordu — kod doğrudan **faturanın kendi
> satıcı VKN'sini** kullanıyordu. Sonuç: bir Turkcell faturası (bize
> kesilmiş, inbox) yanlışlıkla "biz kesmişiz" gibi geçmiş veritabanına
> kaydedildi. Tespit edilip (`gecmis_fatura_kalemleri` tablosunda beklenmeyen
> bir VKN görülünce) hemen düzeltildi: form artık "Sizin şirketinizin
> VKN'si" alanını zorunlu istiyor, bu VKN faturanın gerçek satıcı VKN'siyle
> karşılaştırılıyor — API tarafı (bu endpoint) baştan doğru tasarlanmıştı,
> sadece web arayüzünde eksikti. Hatalı test kaydı temizlendi, düzeltme
> gerçek inbox/outbox faturalarıyla yeniden test edildi.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):** Gerçek
> `curl` isteğiyle test edildi: yeni fatura → `gecmise_kaydedildi: true`,
> aynı fatura tekrar gönderilince → `gecmise_kaydedildi: false` (yinelenen
> engellendi, veritabanında satır çiftlenmedi), inbox faturası (yanlış VKN
> ile) → `basarili: false`, karışık istek (1 geçerli + 1 bozuk XML) → geçerli
> olan işlendi, bozuk olan hata mesajıyla işaretlendi.
