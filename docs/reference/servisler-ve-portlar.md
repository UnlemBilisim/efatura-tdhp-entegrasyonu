# Servis, Port ve Ortam Değişkeni Envanteri

> **Tür:** reference — kesin teknik başvuru. Kodla birebir senkron olmalı;
> isim/varsayılan değer uyuşmazlığı kabul edilemez.
>
> ✅ **Doğrulandı** (2026-07-27): Aşağıdaki tüm portlar ve varsayılan değerler
> koddan okunarak yazıldı (dosya/satır referansları verilmiştir), çalışan
> sistemde ayrıca gözlemlendi.

## Portlar

| Port | Servis | Kim başlatır | Zorunlu mu |
|---|---|---|---|
| **8000** | Mcp_mimarisi API (FastAPI) | `docker compose up` (`app` container, supervisord) | Outbox faturalar için evet — ama sadece `127.0.0.1`'den (içeride entegrasyon kullanır) |
| **8100** | entegrasyon servisi (FastAPI) | `docker compose up` (`app` container, supervisord) | Evet — dış API bu, `0.0.0.0`'a açık |
| **5434** | PostgreSQL (Docker, iç port 5432) | `docker compose up` (`postgres` container) | Evet |
| **11434** | Ollama (embedding) | `docker compose up` (`ollama` container) | RAG için evet |
| **11435** | SSH tüneli → uzak GPU'daki Ollama | **Kullanıcı elle açar / systemd servisi** (container dışı, host seviyesinde) | LLM için evet |

> ⚠️ **11435 tünelini ajan açamaz** — SSH parola/anahtar istiyor. Yerelde
> komut kullanıcının kendi notlarında saklanıyor (`System/` dışına taşındı,
> 2026-07-28).
>
> ✅ **Uygulandı** (2026-07-28): Sunucuda bu tünel artık elle değil,
> `autossh` + `systemd` ile kalıcı bir servis olarak çalışır — kurulum
> adımları: [`ssh-tunel-kurulumu.md`](../how-to/ssh-tunel-kurulumu.md).
> Servis dosyası: [`docker/systemd/efatura-llm-tunnel.service`](../../docker/systemd/efatura-llm-tunnel.service).

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı): `baslat.sh`/`durdur.sh`
> (host modunda üç süreci elle başlatan script'ler) kaldırıldı — tek
> çalıştırma yolu artık `docker compose up` (detay:
> [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md)).

Docker container içinde servisler `0.0.0.0` dinler. Host'a yayınlanan adres
porta göre değişir (`docker/docker-compose.yml`): **8100** dış ekibin kendi
makinelerinden erişebilmesi için `0.0.0.0`'a (tüm arayüzler), **8000**
`127.0.0.1`'e (sadece bu makine) yayınlanır — Postgres (5434) ve Ollama
(11434) de aynı şekilde `127.0.0.1`'de. Dış erişim reverse proxy üzerinden
HTTPS ile verilmelidir.

> ✅ **Düzeltildi** (2026-10-01, kullanıcı kararı — TODO.md "/fatura/
> gecmis-kontrol keyfi VKN sorgusu"): Bu bölüm 2026-07-27'den beri "Compose
> portları host'un 127.0.0.1 adresine yayınlar" diyordu — bu, 2026-09-30'da
> 8100'ün (ve yanlışlıkla 8000'in de) `0.0.0.0`'a açılmasıyla BAYATLAMIŞTI,
> fark edilmemişti. Şimdi hem kod (`docker/docker-compose.yml`) hem bu
> paragraf düzeltildi: 8000 `entegrasyon`'un aynı container içinde
> `localhost:8000` ile zaten eriştiği, dış ekibin hiç çağırmadığı bir port
> olduğu için tekrar `127.0.0.1`'e alındı — `MCP_INTERNAL_API_TOKEN`'ın
> (VKN-bazlı yetki kontrolü olmayan tek bir dahili token) LAN'a maruz
> kalması engellendi. Gerçek ortamda doğrulandı: `docker compose up -d
> --no-deps app` sonrası `docker ps` → `127.0.0.1:8000->8000` /
> `0.0.0.0:8100->8100`, her iki servis de `/saglik` ve `/durum` ile sağlıklı.

## Ortam değişkenleri

| Değişken | Varsayılan | Okuyan | Yoksa ne olur |
|---|---|---|---|
| `DATABASE_URL` | **yok** | `model_eval/core/db.py:36`, `Mcp_mimarisi/.../nace_kural_kontrolu.py`, `gecmis_kontrol.py` | `RuntimeError` — açık hata verir, sessizce geçmez |
| `MCP_MIMARISI_BASE_URL` | `http://localhost:8000` | `entegrasyon/mcp_mimarisi_istemcisi.py:17` | Varsayılana düşer |
| `MODEL_EVAL_OLLAMA_HOST` | `http://localhost:11435` | `entegrasyon/model_eval_koprusu.py:37` | Varsayılana düşer (tünel portu) |
| `OLLAMA_HOST` | `http://localhost:11434` | `model_eval/core/constants.py:10` | Varsayılana düşer (yerel) |
| `MCP_INTERNAL_API_TOKEN` | **yok** | `Mcp_mimarisi/.../auth.py`, MCP istemcisi | Dahili endpoint'ler kapalı kalır |
| `MAX_REQUEST_BYTES` | `10485760` | iki HTTP middleware'i | 10 MB toplam istek sınırı uygulanır |

> ✅ **Uygulandı** (2026-09-28): `EFATURA_API_TOKEN` env değişkeni
> **kaldırıldı**. Dış API anahtarları artık `public.api_anahtarlari`
> tablosunda şirkete bağlı olarak tutuluyor
> (`entegrasyon/api_anahtarlari.py`, `entegrasyon/auth.py::require_api_key`).
> Üretme/iptal: `entegrasyon/api_anahtari_yonet.py`, bkz.
> [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md) §2.1.

### Neden iki farklı Ollama portu?

Bilinçli bir ayrım (`model_eval_koprusu.py:80-88` yorumunda gerekçesi var):

- **11435 (tünel)** → LLM çıkarımı. `gemma4:31b-cloud` gibi bulut modelleri
  yerelde yok, uzak GPU sunucusuna gitmesi gerekiyor.
- **11434 (yerel)** → RAG embedding (`embeddinggemma`). Yerelde kurulu; tünele
  yönlendirmek gereksiz ağ riski ekliyor ve gerçek testte
  "Connection reset by peer" hatasına yol açtı.

> ✅ **Uygulandı** (2026-07-28, tarihsel — o zamanki host script'i için;
> 2026-09-28'de `baslat.sh` kaldırıldı): Gömülü/varsayılan parola hiçbir
> zaman Docker Compose yolunda yoktu, host script'inde vardı ve kaldırıldı.
> **Docker Compose'da (tek geçerli yol) `POSTGRES_PASSWORD` env var'ı
> zorunludur** (`docker/docker-compose.yml:35`, `:66`,
> `:?POSTGRES_PASSWORD env var tanımlı olmalı`) — tanımlı değilse
> `docker compose up` açıkça hata verip durur, sessizce bir varsayılana
> düşmez. **Dikkat:** bu, yalnızca `postgres` container'ı **ilk kez
> oluşturulurken** geçerli parolayı belirler — halihazırda var olan bir
> container'ın parolasını değiştirmez; ilk oluşturmada hangi parola
> kullanıldıysa sonraki her `docker compose up` çağrısında da **aynı**
> `POSTGRES_PASSWORD` verilmelidir (aksi halde PostgreSQL bağlantı
> reddeder). Detay: [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md).

## PostgreSQL tabloları

İki bileşen aynı sunucuyu paylaşır, **farklı tabloları** kullanır — birbirinin
tablosuna dokunmazlar:

| Tablo | Sahibi | İçerik |
|---|---|---|
| `nace_oranlari` | Mcp_mimarisi | NACE kodu → izin verilen KDV oranları |
| `gecmis_fatura_kalemleri` | Mcp_mimarisi | Geçmiş outbox kalemleri (emsal kontrolü) |
| `islenmis_faturalar` | Mcp_mimarisi | Claim tablosu (aynı fatura iki kez işlenmesin) |
| `model_eval_sonuclar` | model_eval | Tahmin sonuçları + onay kayıtları |
| `model_eval_bekleyen_tahminler` | model_eval | Süreli, sunucu taraflı onay kayıtları |
| `api_anahtarlari` | entegrasyon | Şirkete bağlı API anahtarlarının sha256 özeti + izinli VKN listesi (her zaman `public` şemada) |

> ✅ **Uygulandı** (2026-07-28): Bu tabloların tam yedeği `pg_dump -F c` ile
> alınıp `db-yedek/efatura_kdv_yedek.dump`'a kaydedildi (2138 + 1120 + 1
> satır doğrulandı). Bu klasör `.gitignore`'dadır (gerçek fatura verisi
> içerir) — sunucuya ayrı, güvenli bir kanaldan taşınmalı, `pg_restore`
> ile geri yüklenir. Detay: [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md).

## Vektör veritabanı ve Excel referans dosyaları (SQL dışı veri katmanları)

PostgreSQL'in yanında sistemin bağımlı olduğu iki veri kaynağı daha var,
ikisi de **git'e/Docker image'a farklı şekilde davranır**:

| Kaynak | Nerede | Image'a gömülü mü | Taşıma yolu |
|---|---|---|---|
| ChromaDB vektör veritabanı | `model_eval/vector_db/` (container'da `/app/model_eval/vector_db`) | Hayır — `.gitignore`+`.dockerignore`'da hariç | `docker cp` + `efatura-vector-db` volume (bkz. `docker-ile-calistirma.md` §5.5) |
| NACE/KDV Excel aktarım kaynağı | `Mcp_mimarisi/exceller/*.xlsx` | **Evet** — `docker/Dockerfile` COPY ile | Excel PostgreSQL'e aktarılır |
| Şirkete özel mizan | PostgreSQL `mizan_alt_kirilim` | Hayır | PostgreSQL yedeği/geri yüklemesi |

> ✅ **Uygulandı** (2026-07-29): `docker/docker-compose.yml`'deki `app` servisine
> `efatura-vector-db` named volume eklendi — daha önce ChromaDB verisi
> hiçbir kalıcı volume'a bağlı değildi, container yeniden oluşturulduğunda
> (`down`+`up`, image güncelleme) RAG'ın öğrendiği onaylı kayıtlar sessizce
> sıfırlanıyordu.

## HTTP endpoint envanteri

**Mcp_mimarisi (8000)** — `Mcp_mimarisi/src/efatura_kdv/api.py`

| Metot | Yol | Satır |
|---|---|---|
| GET | `/saglik` | 240 |
| POST | `/fatura/kontrol-et` | 298 |
| POST | `/fatura/gecmis-kontrol` | 308 |
| POST | `/fatura/coklu-kontrol` | 326 |

**entegrasyon (8100)** — `entegrasyon/app.py`

| Metot | Yol | Satır |
|---|---|---|
| GET | `/` (test arayüzü) | 193 |
| GET | `/durum` | 198 |
| POST | `/fatura/onayla` | 207 |
| POST | `/fatura/isle` | 237 |

Dış ekibin kullanacağı tek endpoint `POST /fatura/isle` —
sözleşme: [`../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md).

> ❌ **İptal edildi** (2026-07-28): `entegrasyon/v2_api.py` altında asenkron
> bir v2 API (`/api/v1/*`, 4 endpoint) tasarlanmıştı — bu kod repoda duruyor
> ama `app.py`'ye **bağlı değil**, yukarıdaki tabloya dahil değil çünkü
> sunucuda çalışmıyor/erişilebilir değil. Gerekçe:
> [`../explanation/v2-api-tasarim-karari.md`](../explanation/v2-api-tasarim-karari.md).

## Loglar

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı): `baslat.sh`/`durdur.sh`
> ve onların yönettiği `.calistirma/` durum dizini kaldırıldı — sistem
> artık sadece Docker ile çalıştırılıyor. Loglar container'ların stdout'una
> JSON olarak basılır (`log_ortak.py::loglamayi_kur`, `LOG_DIR` set
> edilmediği için dosya handler'ı hiç kurulmaz), `supervisord` bunu
> `docker/supervisord.conf` üzerinden Docker'ın log akışına verir. Rotasyon
> `docker/docker-compose.yml`'deki `logging:` ayarıyla (10MB × 5 dosya, her
> üç serviste de) sağlanır.

Log izleme (manuel test için):

```bash
docker compose logs -f app | grep -A 45 "DIŞ EKİP JSON"
```

## Docker registry

> ✅ **Uygulandı** (2026-07-29): Image `docker.unlemcloud.com/unlembilisim/efatura-kdv-tdhp-sistemi`
> adıyla kurumsal registry'ye push edildi (`1.0.0` ve `latest`). Kurulum ve
> bilinen `413` tuzağı: [`../how-to/docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md) §0.

| Alan | Değer |
|---|---|
| Registry | `docker.unlemcloud.com` |
| Repository | `unlembilisim/efatura-kdv-tdhp-sistemi` |
| Yayınlanan tag'ler | `1.0.0`, `latest` |

> **Not:** `npm.unlemcloud.com` üzerinden npm paketi olarak yayınlama
> denendi (`@unlembilisim/efatura-kdv-tdhp-sistemi`) ama servis yöneticisi
> bu adresin yanlış olduğunu, kod dağıtımının Docker registry üzerinden
> yapılması gerektiğini bildirdi (2026-07-29). `package.json`/`.npmrc`
> dosyaları repoda kalıyor ama **kullanılan asıl dağıtım kanalı Docker'dır.**
