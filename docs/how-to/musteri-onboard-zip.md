# Yeni şirketleri zip ile kurma (`POST /musteri/onboard`)

> **Tür:** how-to — somut adımlar. API sözleşmesinin kesin tanımı:
> [`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md) §9.
> Veri dosyalarının formatı: [`teslim/ONBOARDING-VERI-FORMATI.md`](../../teslim/ONBOARDING-VERI-FORMATI.md).
>
> ✅ **Uygulandı** (2026-10-06): `entegrasyon/musteri_onboard_api.py`. Aşağıdaki akış Docker içinde,
> gerçek PostgreSQL + RAG ile geçici bir veritabanında uçtan uca denendi (mock şirket 6 sn'de
> kuruldu). **2026-10-16:** kayıtlı şirket artık güncellenir (aşağıya bakın); gerçek veritabanıyla test edildi
> (`model_eval/tests/test_musteri_guncelle_orkestrasyon.py`).

## Bu nedir?

Dış ekip (ya da biz) bir ya da birden fazla **yeni şirketin** verisini **tek bir zip** olarak yükler;
sistem zip'i güvenle açar, her şirketi sırayla kurar (PostgreSQL şeması, mizan, yevmiye eşleştirme,
RAG emsal havuzu) ve sonucu şirket bazında bildirir. Daha önce aynı iş yalnızca komut satırından
(`scripts/musteri_onboard_toplu.py --onboarding-kok <klasör>`) yapılabiliyordu — kurulum mantığı
**aynı**, yalnızca bir HTTP kapısı eklendi.

**Ne yapmaz:** mevcut bir şirketi güncellemez (atlar), fatura işlemez (o `POST /fatura/isle`'nin işi).

## Başlamadan önce

| Gereksinim | Nasıl kontrol edilir |
|---|---|
| Docker sistemi ayakta | `curl http://127.0.0.1:8100/durum` → `{"model_eval_hazir": true, ...}` |
| Yerel Ollama + `embeddinggemma` (RAG adımı için) | `curl localhost:11434/api/tags` listede `embeddinggemma` görünmeli |
| Anahtarda **onboard yetkisi** | Aşağıdaki Adım 1 |

LLM tüneli (11435) onboarding için **gerekmez** — yalnızca fatura işlemede kullanılır. RAG adımı
embedding istediği için Ollama kapalıysa o şirket `hata` verir (kurulum idempotent, düzeltip tekrar yüklenebilir).

## Adım 1 — Anahtara onboard yetkisi ver (biz yaparız)

Anahtarlar varsayılan olarak bu uç noktayı **kullanamaz** (`403`). Yetki bilinçli olarak verilir:

```bash
cd docker
# Var olan müşavir anahtarına yetki:
docker compose --env-file ../.env exec -T app python3 /app/entegrasyon/api_anahtari_yonet.py \
  onboard-yetkisi --etiket <musavir-etiketi>
# Geri almak için sonuna --kaldir

# Ya da yeni anahtarı baştan yetkili üret (anahtar yalnızca bir kez gösterilir):
docker compose --env-file ../.env exec -T app python3 /app/entegrasyon/api_anahtari_yonet.py \
  olustur --etiket <musavir-etiketi> --vkn 1111111111 --onboard-yetkisi

# Durumu gör (yetkililer "[onboard yetkili]" ile işaretlenir):
docker compose --env-file ../.env exec -T app python3 /app/entegrasyon/api_anahtari_yonet.py listele
```

> **Yalnızca onboard yapan anahtar:** `--vkn`/`--tum-sirketler` vermeden, sadece `--onboard-yetkisi` ile de
> anahtar üretilebilir (`olustur --etiket <ad> --onboard-yetkisi`). Böyle bir anahtar **başlangıçta hiçbir şirkete
> yetkili değildir**; zip ile kurduğu her yeni şirkete otomatik yetki kazanır. Mevcut (zaten kurulu) bir VKN
> zip'te gelirse `atlandi` olur ve anahtar o şirkete **yetki kazanmaz**. Başarılı her onboarding sonunda yeni VKN
> anahtarın kapsamına eklenir; anahtarın değeri değişmez.

## Adım 2 — Zip'i hazırla

Kökte her şirket için bir klasör; **klasör adı şirketin 10 haneli VKN'si**:

```
yukleme.zip
├── 6677889900/
│   ├── mizan.xlsx            zorunlu
│   ├── faturalar/*.xml       zorunlu (son 6 ay; dosya adı önemsiz)
│   ├── yevmiye.xlsx          zorunlu (ya da yevmiye.csv)
│   └── nace.txt              opsiyonel
└── 1122334455/ ...
```

- Dosya adları **tam olarak** böyle olmalı (büyük/küçük harf fark etmez). Başka dosyalar yok sayılır.
- Tek bir sarmalayıcı klasör (macOS "Sıkıştır" gibi) sorun değildir.
- Mizan ve yevmiye sütun formatları ve sık yapılan hatalar (örn. hesap kodu hücresinin metin olması):
  `teslim/ONBOARDING-VERI-FORMATI.md`.

Terminalden hazırlamak için (klasörün içinde `<vkn>/` klasörleri olduğu bir üst dizinden):

```bash
cd onboarding_klasoru && zip -r ../yukleme.zip . -x "*.DS_Store"
```

## Adım 3 — Yükle

```bash
curl -X POST http://127.0.0.1:8100/musteri/onboard \
  -H "Authorization: Bearer $API_ANAHTARI" \
  -H "Content-Type: application/zip" \
  --data-binary @yukleme.zip
```

Cevap `202` — işlem **arka planda** sürer:

```json
{"is_id": "bb45a020e67d4701a24655d04217cf59", "durum": "kuyrukta",
 "sirketler": ["1122334455", "6677889900"], "atlanan_dosya": 0, "gecersiz_klasorler": []}
```

Zip hatalıysa (bozuk, güvensiz, şirket klasörü yok) `400` döner ve hiçbir şey kurulmaz.

## Adım 4 — İlerlemeyi izle

```bash
curl -H "Authorization: Bearer $API_ANAHTARI" http://127.0.0.1:8100/musteri/isler/<is_id>
```

İş `durum`: `kuyrukta` → `calisiyor` → `bitti`. Cevapta ayrıca **`yuzde`** (0–100, genel ilerleme) ve her şirket için `adim` +
`yuzde` (`sema` 25 → `mizan` 50 → `eslestirme` 75 → `rag` 100) bulunur; yüzde basamaklıdır, RAG adımı uzunsa aynı değerde
bir süre kalabilir. Şirket `durum`:

| Durum | Anlamı | Ne yapmalı |
|---|---|---|
| `bekliyor` / `calisiyor` | Sırada / işleniyor | Bekle (mock şirket ~6 sn; gerçek veri, fatura sayısına göre daha uzun) |
| `kuruldu` | Şema, mizan, RAG tamam; VKN anahtarın kapsamına eklendi | `ozet`'te mizan satırı ve fatura eşleşme oranına bak |
| `guncellendi` | Kayıtlı şirket: fark bulundu, **yalnızca fark** uygulandı (`ozet`'te parça parça) | Geçmiş tablosuna bak |
| `degismedi` | Kayıtlı şirket, gelen veri mevcutla aynı — hiçbir şey yazılmadı | Normal |
| `atlandi` | Kayıtlı şirket ama anahtar o VKN'ye yetkili değil — hiçbir şey değişmedi | Yetki gerekiyorsa `vkn-ekle` |
| `hata` | Bu şirket kurulamadı; diğerleri etkilenmedi. Neden `ayrinti`'de | Aşağıdaki "Sorun giderme" |

`ozet` örneği: `{"mizan_satir_sayisi": 21, "fatura_eslesme": "2/2", "yon_belirsiz": 0, "nace_kodlari": ["107101"]}`.
**`fatura_eslesme` düşükse** (örn. `40/100`) yevmiyedeki `fatura_no`'lar XML'deki `cbc:ID` ile uyuşmuyor
demektir; `yon_belirsiz` > 0 ise klasör adındaki VKN yanlış olabilir (o faturalar RAG'a yazılmaz).

Kurulumdan sonra fatura işlemeye hazır olduğunu şöyle doğrula:
`GET /kayitli-sirketler` listesinde VKN görünmeli.

## Güvenlik ve davranış kuralları

- **Kayıtlı şirket GÜNCELLENİR, ezilmez** (2026-10-16): anahtar o VKN adına yetkiliyse gelen veri mevcutla karşılaştırılır; aynıysa hiçbir şey yazılmaz,
  farklıysa yalnızca fark uygulanır, eski değer + zaman `onboarding_guncelleme_gecmisi` tablosuna loglanır. Yetkisizse `atlandi`.
  Kısmi zip mümkün (yalnız `mizan.xlsx` / `nace.txt` / `faturalar`+`yevmiye`). Mizan tam hesap planı sayılır: dosyada olmayan hesap silinir (eski değeri
  geçmişte), ama dosya boşsa ya da hesapların >%50'si silinecekse uygulanmaz (`uyari`). RAG emsalleri yalnızca eklenir/güncellenir, hiç silinmez.
- **Yarım kalan kurulum:** Bir şirket ortada hata verirse "yarım" olarak işaretlenir. Aynı anahtarla zip'i
  düzeltip yeniden yüklerseniz kurulum **tamamlanır** (başka anahtar bunu yapamaz, `atlandi` alır).
- **Zip güvenli açılır:** `../` yolları, parola korumalı zip, 20.000'den fazla girdi, tek dosya >100 MB, açılmış
  toplam >1 GB ya da şüpheli sıkıştırma oranı reddedilir; yalnızca izinli dosya adları diske yazılır.
- **Müşterinin ham verisi iş bitince sunucudan silinir**; yalnızca kurulum sonucu (iş kaydı) kalır.
- **Sınırlar:** zip en çok 200 MB (`ONBOARD_MAX_ZIP_BYTES`), aynı anda en çok 5 bekleyen iş (`429`),
  şirketler **sırayla** işlenir.
- Başka bir anahtarın işini sorgularsanız `404` alırsınız (varlığı sızdırılmaz).
- Her yükleme ve bitiş, audit loga (`entegrasyon.audit`) yazılır: hangi anahtar, hangi VKN'ler, sonuç.
  Ham veri ya da anahtar loga yazılmaz.

## Sorun giderme

| Belirti | Neden / çözüm |
|---|---|
| `401` | Anahtar yok, geçersiz ya da iptal |
| `403` "onboard yetkisi yok" | Adım 1'i yapın |
| `400` "işlenecek şirket klasörü bulunamadı" | Kökte `<10 haneli VKN>/` klasörü yok ya da dosya adları yanlış |
| `400` "Güvensiz dosya yolu" / "zip bomb" | Zip'te `../` var ya da aşırı sıkıştırılmış dosya — zip'i yeniden hazırlayın |
| `413` | Zip 200 MB'tan büyük — şirketleri birkaç zip'e bölün |
| `429` | 5 bekleyen iş var; biri bitince tekrar deneyin |
| Şirket `hata` + "eksik dosya" | `mizan.xlsx`, `faturalar/*.xml` ya da `yevmiye.xlsx|csv` yok |
| Şirket `hata` + embedding/Ollama | Yerel Ollama kapalı ya da `embeddinggemma` yok; düzeltip aynı anahtarla yeniden yükleyin |
| Şirket `atlandi` ama beklemiyordunuz | VKN zaten kurulu (ya da başka anahtarın yarım kurulumu). Kayıtlı VKN'ler: `GET /kayitli-sirketler` |
| İş bir süre sonra `bitti` ama şirketler `hata: ...yarıda kaldı` | Uygulama iş sürerken yeniden başladı — zip'i yeniden yükleyin |

Ayrıntılı loglar: `docker compose logs app | grep -i onboard`. Hata mesajları dosya yollarını sızdırmaz
(`<zip>` ile değiştirilir).

## Kendin dene (mock zip ile)

Elimizde mock bir şirket var: `onboarding_test/6677889900/`. Gerçek veritabanını kirletmeden denemek için
**geçici bir veritabanı** (`model_eval_test`) kullanılır — bkz. [`sistemi-test-etme.md`](sistemi-test-etme.md).
Birim ve entegrasyon testleri (veritabanı/Ollama gerektirmeden): `entegrasyon/tests/test_musteri_onboard.py`
(26 test: güvenli zip açma, iş durumu, atlama/yeniden deneme, HTTP uçları).

> ⚠️ **Prod DB'sine test verisi yazma.** Mock şirketi gerçek `DATABASE_URL` ile onboard edersen
> `tenant_<vkn>` şeması ve `tdhp_invoices_<vkn>` ChromaDB koleksiyonu kalıcı olarak oluşur; silmek
> için `DROP SCHEMA tenant_<vkn> CASCADE` ve koleksiyon silme gerekir.

## Nerede ne var?

| Ne | Dosya |
|---|---|
| Uç noktalar, güvenli zip açma, iş kuyruğu, çalışan | `entegrasyon/musteri_onboard_api.py` |
| Şirket kurulumu (şema + mizan + yevmiye + RAG) | `scripts/musteri_onboard_toplu.py::musteriyi_onboard_et` |
| Onboard yetkisi (anahtar tablosu, `require_onboard_yetkisi`) | `entegrasyon/api_anahtarlari.py`, `entegrasyon/auth.py`, `entegrasyon/api_anahtari_yonet.py` |
| 200 MB zip sınırı (gövde belleğe alınmaz) | `entegrasyon/security.py` |
| İş durumu (kalıcı) | `ONBOARD_DATA_DIR` → compose'ta `efatura-onboarding` volume'ü (`/app/data/onboarding`) |
| Env değişkenleri | [`servisler-ve-portlar.md`](../reference/servisler-ve-portlar.md) |

## Güncelleme geçmişini sorgulama (kayıtlı şirket)

Her güncellemede eski değer + yeni değer + zaman + iş/anahtar, şirketin **kendi şemasındaki** `onboarding_guncelleme_gecmisi` tablosuna yazılır
(varsayılan şirkette `public`). Örnek (sunucuda):

```bash
docker exec efatura-sistemi-postgres-1 psql -U efatura -d efatura_kdv -c "
  SET search_path TO tenant_<VKN>, public;
  SELECT guncelleme_zamani, alan, islem, anahtar, eski_deger, yeni_deger, istemci
  FROM onboarding_guncelleme_gecmisi ORDER BY id DESC LIMIT 20;"
```

`alan`: `nace` | `mizan` | `rag`; `islem`: `eklendi` | `guncellendi` | `silindi`. İlk KURULUMDAKİ toplu yazma loglanmaz (geçmiş yalnızca güncellemeleri izler).
Mizanda değişen satırın `updated_at` sütunu da yenilenir.
