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
| **8000** | Mcp_mimarisi API (FastAPI) | `baslat.sh` | Outbox faturalar için evet |
| **8100** | entegrasyon servisi (FastAPI) | `baslat.sh` | Evet — dış API bu |
| **5434** | PostgreSQL (Docker, iç port 5432) | `baslat.sh` → `docker run` | Evet |
| **11434** | Ollama (yerel, embedding) | `baslat.sh` → `ollama serve` | RAG için evet |
| **11435** | SSH tüneli → uzak GPU'daki Ollama | **Kullanıcı elle açar** | LLM için evet |

> ⚠️ **11435 tünelini ajan açamaz** — SSH parola/anahtar istiyor. Yerelde
> komut kullanıcının kendi notlarında saklanıyor (`System/` dışına taşındı,
> 2026-07-28).
>
> ✅ **Uygulandı** (2026-07-28): Sunucuda bu tünel artık elle değil,
> `autossh` + `systemd` ile kalıcı bir servis olarak çalışır — kurulum
> adımları: [`ssh-tunel-kurulumu.md`](../how-to/ssh-tunel-kurulumu.md).
> Servis dosyası: [`docker/systemd/efatura-llm-tunnel.service`](../../docker/systemd/efatura-llm-tunnel.service).

Her iki FastAPI servisi de `--host "$BIND_HOST"` ile başlatılır
(`baslat.sh:73`, `baslat.sh:102`), varsayılan `0.0.0.0` (tüm ağ arayüzleri).
Güvenlik etkisi: [`../explanation/guvenlik-durumu-2026-07-27.md`](../explanation/guvenlik-durumu-2026-07-27.md).

> ✅ **Uygulandı** (2026-07-28): `BIND_HOST` env var eklendi (`baslat.sh:24`)
> — auth henüz eklenmediği için sunucuda geçici bir azaltma önlemi olarak,
> dış ekibin bilinen IP aralığına özel bir iç ağ adresi verilebilir:
> `BIND_HOST=10.0.x.x POSTGRES_PASSWORD=... ./baslat.sh`. Varsayılan
> davranış (env var verilmezse `0.0.0.0`) değişmedi. Gerçek testte
> doğrulandı: `BIND_HOST=127.0.0.1` ile çalıştırıldığında servisler yalnızca
> `localhost`'ta dinledi (`lsof` ile teyit edildi), env var verilmediğinde
> yine `*:` (tüm arayüzler) oldu. Bu, kalıcı çözüm değildir — asıl çözüm
> kimlik doğrulamadır (bkz. güvenlik durumu belgesi).

## Ortam değişkenleri

| Değişken | Varsayılan | Okuyan | Yoksa ne olur |
|---|---|---|---|
| `DATABASE_URL` | **yok** | `model_eval/core/db.py:36`, `Mcp_mimarisi/.../nace_kural_kontrolu.py`, `gecmis_kontrol.py` | `RuntimeError` — açık hata verir, sessizce geçmez |
| `MCP_MIMARISI_BASE_URL` | `http://localhost:8000` | `entegrasyon/mcp_mimarisi_istemcisi.py:17` | Varsayılana düşer |
| `MODEL_EVAL_OLLAMA_HOST` | `http://localhost:11435` | `entegrasyon/model_eval_koprusu.py:37` | Varsayılana düşer (tünel portu) |
| `OLLAMA_HOST` | `http://localhost:11434` | `model_eval/core/constants.py:10` | Varsayılana düşer (yerel) |

### Neden iki farklı Ollama portu?

Bilinçli bir ayrım (`model_eval_koprusu.py:80-88` yorumunda gerekçesi var):

- **11435 (tünel)** → LLM çıkarımı. `gemma4:31b-cloud` gibi bulut modelleri
  yerelde yok, uzak GPU sunucusuna gitmesi gerekiyor.
- **11434 (yerel)** → RAG embedding (`embeddinggemma`). Yerelde kurulu; tünele
  yönlendirmek gereksiz ağ riski ekliyor ve gerçek testte
  "Connection reset by peer" hatasına yol açtı.

> ✅ **Uygulandı** (2026-07-28): `baslat.sh`'teki gömülü parola kaldırıldı.
> `POSTGRES_PASSWORD` artık zorunlu env var (`baslat.sh:15`, `: "${POSTGRES_PASSWORD:?...}"`)
> — tanımlı değilse script açıkça hata verip durur, sessizce eski
> `efatura` parolasına düşmez. Kullanım: `POSTGRES_PASSWORD=<parola> ./baslat.sh`.
> **Dikkat:** bu, yalnızca container **ilk kez oluşturulurken** geçerli
> parolayı belirler (`docker run -e POSTGRES_PASSWORD=...`) — halihazırda
> var olan bir container'ın parolasını değiştirmez; container'ı oluştururken
> hangi parola kullanıldıysa sonraki her `./baslat.sh` çağrısında da **aynı**
> `POSTGRES_PASSWORD` verilmelidir (aksi halde PostgreSQL bağlantı reddeder).
> Gerçek testte doğrulandı: env var olmadan çalıştırıldığında script
> `POSTGRES_PASSWORD env var tanımlı olmalı` hatasıyla durdu; doğru parolayla
> her iki servis de sağlıklı ayağa kalktı.
>
> Docker Compose ile çalıştırıldığında (`docker-compose.yml`) aynı disiplin
> zaten uygulanıyordu — `POSTGRES_PASSWORD` env var'ı orada da zorunlu
> (`docker-compose.yml:21`, `:47`). Detay: [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md).

## PostgreSQL tabloları

İki bileşen aynı sunucuyu paylaşır, **farklı tabloları** kullanır — birbirinin
tablosuna dokunmazlar:

| Tablo | Sahibi | İçerik |
|---|---|---|
| `nace_oranlari` | Mcp_mimarisi | NACE kodu → izin verilen KDV oranları |
| `gecmis_fatura_kalemleri` | Mcp_mimarisi | Geçmiş outbox kalemleri (emsal kontrolü) |
| `islenmis_faturalar` | Mcp_mimarisi | Claim tablosu (aynı fatura iki kez işlenmesin) |
| `model_eval_sonuclar` | model_eval | Tahmin sonuçları + onay kayıtları |

> ✅ **Uygulandı** (2026-07-28): Bu tabloların tam yedeği `pg_dump -F c` ile
> alınıp `db-yedek/efatura_kdv_yedek.dump`'a kaydedildi (2138 + 1120 + 1
> satır doğrulandı). Bu klasör `.gitignore`'dadır (gerçek fatura verisi
> içerir) — sunucuya ayrı, güvenli bir kanaldan taşınmalı, `pg_restore`
> ile geri yüklenir. Detay: [`docker-ile-calistirma.md`](../how-to/docker-ile-calistirma.md).

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

## Durum dosyaları (`.calistirma/`)

`baslat.sh` tarafından yönetilir, elle düzenlenmemeli:

| Dosya | İçerik |
|---|---|
| `*.pid` | Süreç kimlikleri (`durdur.sh` bunları kullanır) |
| `*.log` | Servis logları — **dış ekip JSON'u burada görünür** |
| `mcp_venv/` | Mcp_mimarisi için izole venv (~40 MB) |

Log izleme (manuel test için):

```bash
tail -f .calistirma/entegrasyon.log | grep -A 45 "DIŞ EKİP JSON"
```
