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

> ⚠️ **11435 tünelini ajan açamaz** — SSH parola/anahtar istiyor. Komut
> [`../../çalıştırma.txt`](../../çalıştırma.txt) içinde.

Her iki FastAPI servisi de `--host 0.0.0.0` ile başlatılır
(`baslat.sh:65`, `baslat.sh:94`) — yani tüm ağ arayüzlerinden erişilebilir.
Güvenlik etkisi: [`../explanation/guvenlik-durumu-2026-07-27.md`](../explanation/guvenlik-durumu-2026-07-27.md).

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

`baslat.sh` `DATABASE_URL`'i **koşulsuz ezer** (`baslat.sh:15`) — ortamda güçlü
bir parola tanımlasanız bile her başlatmada gömülü değer geçerli olur.

## PostgreSQL tabloları

İki bileşen aynı sunucuyu paylaşır, **farklı tabloları** kullanır — birbirinin
tablosuna dokunmazlar:

| Tablo | Sahibi | İçerik |
|---|---|---|
| `nace_oranlari` | Mcp_mimarisi | NACE kodu → izin verilen KDV oranları |
| `gecmis_fatura_kalemleri` | Mcp_mimarisi | Geçmiş outbox kalemleri (emsal kontrolü) |
| `islenmis_faturalar` | Mcp_mimarisi | Claim tablosu (aynı fatura iki kez işlenmesin) |
| `model_eval_sonuclar` | model_eval | Tahmin sonuçları + onay kayıtları |

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
