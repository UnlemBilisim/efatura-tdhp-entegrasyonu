# Toplu fatura işleme (`POST /fatura/toplu-isle`) — nasıl kullanılır

> **Tür:** how-to — somut adımlar. Sözleşmenin kesin tanımı:
> [`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md) §10.
> Dış ekibe verilen kılavuz: [`teslim/FATURA-ISLEME-KILAVUZU.md`](../../teslim/FATURA-ISLEME-KILAVUZU.md).
>
> ✅ **Uygulandı** (2026-10-16): `entegrasyon/toplu_fatura_api.py`. Birim/HTTP testleri geçiyor
> (`entegrasyon/tests/test_toplu_fatura.py`). ⚠️ **Gerçek LLM ile uçtan uca henüz denenmedi** — ilk gerçek denemede
> bu belgedeki "Kendin dene" adımlarını izleyin ve sonucu not edin.

## Bu nedir?

Birden fazla e-fatura XML'ini **tek zip** olarak göndermenin yolu. Zip yüklenince hemen `202` + `is_id` döner; faturalar arka planda,
tek-fatura uç noktasıyla (`POST /fatura/isle`) **aynı hattan** (yön tespiti → ön filtre → TDHP tahmini → doğrulama) sırayla işlenir. Sonuç `is_id`
ile sorgulanır: yüzde, sayaçlar ve fatura bazında `records[]`.

**Paralel tek istekler** için ayrı bir şey gerekmez: `POST /fatura/isle` aynı anda çağrılabilir, sunucu aynı anda en fazla
`MAX_ESZAMANLI_ISLEM` (varsayılan **2**) faturayı işler, fazlası **sırada bekler** (reddedilmez). Toplu iş bu sınırı tek isteklerle paylaşır.

## Başlamadan önce

| Gereksinim | Kontrol |
|---|---|
| Sistem ayakta | `curl http://127.0.0.1:8100/durum` → `{"model_eval_hazir": true, ...}` |
| **LLM erişimi** (tünel/Ollama) | Yoksa her fatura boş `entries` ile `tdhp_dogrulama_basarisiz` döner — hata fırlatılmaz (CLAUDE.md "Tuzak") |
| **Embedding** (`embeddinggemma`, RAG için) | Yerel/sunucu Ollama'da kurulu olmalı |
| **Şirket kurulu** | `GET /kayitli-sirketler` listesinde VKN görünmeli (yoksa `404`; kurmak için [`musteri-onboard-zip.md`](musteri-onboard-zip.md)) |
| **Anahtar** | O VKN'ye yetkili normal API anahtarı yeterli (toplu için ayrı yetki gerekmez) |

## Kendin dene

**1. Zip'i hazırla.** İki düzen var:

```
# A) Tek şirket — satici_vkn parametresi verilir; klasör düzeni önemsiz, TÜM .xml dosyaları o şirketin
faturalar.zip
├── fatura-001.xml
└── fatura-002.xml

# B) Çok şirket — satici_vkn VERİLMEZ; kökte <10 haneli VKN>/ klasörleri
faturalar.zip
├── 6677889900/fatura-001.xml
└── 1122334455/fatura-101.xml
```
```bash
cd faturalar_klasoru && zip -r ../faturalar.zip . -x "*.DS_Store"
```
Mock deneme için `onboarding_test/<vkn>/faturalar/*.xml` kullanılabilir (şirket kurulu olmalı).

**2. Yükle** (yerel Docker için `127.0.0.1:8100`; sunucu için önce `ssh -L 8100:localhost:8100 unlem-gx10-01@10.34.10.112` tüneli
açıp yine `127.0.0.1:8100` kullanabilir ya da komutu sunucunun içinden çalıştırabilirsiniz):

```bash
curl -X POST "http://127.0.0.1:8100/fatura/toplu-isle?satici_vkn=6677889900" \
  -H "Authorization: Bearer $API_ANAHTARI" -H "Content-Type: application/zip" \
  --data-binary @faturalar.zip
# → {"is_id":"...","durum":"kuyrukta","toplam":2,"vknler":["6677889900"],"atlanan_dosya":0}   (HTTP 202)
```

Seçenekler (sorgu parametresi): `onay=true` (satış faturasında KDV oranı uyarısına rağmen devam), `kur_secimi=orijinal|tl` (döviz). İkisi de
zip'teki **tüm** faturalara uygulanır; verilmezse ilgili faturalar `onay_bekliyor`/`kur_bekliyor` sonucuyla biter (hata değildir).

**3. İzle.**

```bash
curl -s -H "Authorization: Bearer $API_ANAHTARI" http://127.0.0.1:8100/fatura/toplu/<is_id> | python3 -m json.tool
```
`durum`: `kuyrukta` → `calisiyor` → `bitti`; `yuzde` işlenen fatura oranıdır. Fatura bazında `sonuc`:

| `sonuc` | Anlamı |
|---|---|
| `hazir` | Kayıt hazır, doğrulamadan geçti (`approvable: true`) |
| `onaysiz` | Kayıt üretildi ama doğrulamadan geçemedi (`red_kodlari`'na bak) — onaylanamaz |
| `onay_bekliyor` | Satış faturasında KDV uyarısı, `onay` verilmediği için durdu |
| `kur_bekliyor` | Döviz faturası, `kur_secimi` verilmediği için durdu |
| `hata` | İşlenemedi (bozuk XML vb.) — nedeni `hata` + `http_durum` alanlarında |

Süzme: `?sonuc=hata`; sayfalama: `?sayfa=2&boyut=100` (en çok 500).

**4. Tam sonucu (records[]) al.**

```bash
curl -s -H "Authorization: Bearer $API_ANAHTARI" "http://127.0.0.1:8100/fatura/toplu/<is_id>/sonuclar?sonuc=hazir&boyut=20"
# her kayıtta cevap.tdhp_tahmini.dis_sema.records[]  (tek-fatura cevabıyla aynı biçim)
```

**5. (İsteğe bağlı) Onayla.** Muhasebeci doğru bulursa `prediction_id` ile `POST /fatura/onayla` — PostgreSQL + RAG'a yazılır, sonraki tahminler
iyileşir. **Otomatik onay yoktur.** Toplu tahminler **24 saat** onaylanabilir (tek istekte 30 dk). Yalnızca `approvable: true` olanlar onaylanabilir.

## Mac'ten izleme: İzleme Paneli

Hata nedenlerini ve ilerlemeyi tek ekranda görmek için ([`izleme/README.md`](../../izleme/README.md)):

```bash
python3 izleme/panel.py            # sunucuyu izler → http://127.0.0.1:8300
python3 izleme/panel.py --yerel    # bu Mac'teki Docker'ı izler
```
**İstekler** sekmesinde yükleme/sorgu istekleri (durum kodu, süre, istemci, **hata mesajı**) görünür. Hata mesajının görünmesi için sunucuda
`entegrasyon/istek_gunlugu.py`'nin bulunduğu sürüm çalışmalı. (Toplu işlerin ilerlemesi şu an panelin "Onboarding işleri" sekmesinde değil;
ilerleme için yukarıdaki `GET /fatura/toplu/{id}` kullanılır.)

## Kurallar ve davranış

| Konu | Davranış |
|---|---|
| **Yetki** | Kuyruğa girmeden doğrulanır: zip'teki **her VKN** anahtara yetkili (yoksa `403`) ve kayıtlı (yoksa `404`) olmalı; biri tutmazsa **hiçbir fatura işlenmez** |
| **Hata izolasyonu** | Bozuk bir XML yalnızca kendi satırını `hata` yapar, diğerleri işlenir |
| **Hız** | Toplu iş bir yuvayı kullanır (`MAX_ESZAMANLI_ISLEM − 1`), bir yuva tek istekler için boş kalır. Fatura başına genelde 10–30 sn → saatte kabaca 120–360 fatura |
| **Yeniden başlatma** | Uygulama iş sürerken yeniden başlarsa iş **kaldığı yerden** devam eder; işlenenler tekrar işlenmez |
| **Veri saklama** | Ham XML'ler iş bitince silinir; sonuçlar 14 gün saklanır (saatte bir temizlenir) |
| **Başka anahtarın işi** | `404` (varlığı sızdırılmaz) |
| **Loglama** | Her yükleme/fatura/bitiş `entegrasyon.audit`'e yazılır (kim, hangi VKN, sonuç, red kodları); **ham XML asla yazılmaz** |

Sınırlar: zip ≤ 200 MB, ≤ 2000 fatura, tek XML ≤ `MAX_REQUEST_BYTES` (30 MB), aynı anda ≤ 5 bekleyen toplu iş (`429`).

## Ayarlar (env)

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `TOPLU_MAX_ZIP_BYTES` | 200 MB | Zip boyut sınırı (gövde belleğe alınmaz, diske akıtılır) |
| `TOPLU_MAX_FATURA` | 2000 | Bir zip'teki en çok fatura |
| `TOPLU_ISCI_SAYISI` | `max(1, MAX_ESZAMANLI_ISLEM−1)` | Toplu işte aynı anda işlenen fatura |
| `TOPLU_TAHMIN_TTL_DAKIKA` | 1440 | Toplu tahminlerin onay süresi |
| `TOPLU_SAKLAMA_GUN` | 14 | Bitmiş iş sonuçlarının saklama süresi |
| `MAX_ESZAMANLI_ISLEM` | 2 | Tek + toplu işin paylaştığı eşzamanlılık sınırı |
| `ONBOARD_DATA_DIR` | sistem geçici dizini (compose: `/app/data/onboarding`) | İş durumu/sonuçlar `…/toplu/` altında (onboarding ile aynı volume) |

> `MAX_ESZAMANLI_ISLEM` artırılırsa LLM/GPU yetmeyebilir; ayrıca uvicorn `--workers` artırılırsa sınır worker başına uygulanır (bkz. `es_zamanli_sinir.py`).
> Env değerleri compose'ta tanımlı değilse varsayılan geçer; değiştirmek için `docker/docker-compose.yml`'e eklenmeli.

## Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `400` "içinde .xml yok" | `satici_vkn` yok ve zip'te `<vkn>/` klasörleri de yok — iki düzenden birini kullanın |
| `400` "Güvensiz dosya yolu" | Zip'te `\` ya da `../` var (Windows "sıkıştır" araçları) — `tar -a -c -f x.zip klasör` ya da 7-Zip |
| `403` "şu VKN'ler adına yetki yok" | Zip'teki bir VKN anahtarın kapsamında değil — hiçbir şey işlenmedi |
| `404` "kayıtlı şirket yok" | Şirketi önce kurun ([`musteri-onboard-zip.md`](musteri-onboard-zip.md)) |
| `413` | Zip 200 MB'tan büyük — bölün |
| Her fatura `onaysiz` + boş kayıt | LLM'e erişilemiyor (tünel/Ollama) — önce [`ssh-tunel-kurulumu.md`](ssh-tunel-kurulumu.md) |
| Fatura `onay_bekliyor` / `kur_bekliyor` | Hata değil: `onay=true` / `kur_secimi=...` ile yalnızca o faturaları yeniden gönderin |
| İş çok yavaş | Beklenen: tek yuva, LLM süresi. `yuzde`'yi izleyin; gerekirse `TOPLU_ISCI_SAYISI`/`MAX_ESZAMANLI_ISLEM`'i (kapasiteyi bilerek) artırın |
| Onayda `409` | Onay süresi doldu (tek istek 30 dk, toplu 24 sa) ya da zaten onaylanmış — faturayı yeniden işleyin |

## Nerede ne var

| Ne | Dosya |
|---|---|
| Uç noktalar, zip açma, kalıcı iş durumu, çalışan | `entegrasyon/toplu_fatura_api.py` |
| Tek-fatura iç fonksiyonuna bağlantı + süre uzatma | `entegrasyon/app.py::_toplu_islem`, `entegrasyon/model_eval_koprusu.py::tahmin_ttl_ayarla` |
| Zip akış yolu / boyut sınırı | `entegrasyon/security.py` |
| İstek günlüğü (hata mesajı dahil) | `entegrasyon/istek_gunlugu.py` |
| İş durumu (kalıcı) | `ONBOARD_DATA_DIR/toplu/<is_id>/` (`is.json`, `manifest.json`, `sonuclar.jsonl`) |
| Testler | `entegrasyon/tests/test_toplu_fatura.py`, `test_istek_gunlugu.py` |
