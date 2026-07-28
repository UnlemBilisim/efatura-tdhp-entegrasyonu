# API'yi çalıştırma

Faz 1 doğrulama katmanı 2026-07-21'de bir HTTP API'ye (FastAPI) kavuştu —
önceden sadece Python import ile (tek kullanıcı, tek süreç) kullanılabiliyordu.
Gerekçe ve mimari karar: `PROJECT.md` §3.8.

## Ön koşul: PostgreSQL kurulu ve dolu olmalı

API başlarken `NaceOranTablosu`'nu PostgreSQL'den okur — önce
`docs/how-to/postgres-kurulum.md`'deki adımları tamamla (Docker ile Postgres
ayağa kaldırma + `scripts/excel_to_postgres.py` migrasyonu).

## Bağımlılıkları kur

```bash
python3 -m pip install -r requirements.txt
```

## API'yi başlat

```bash
export DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv"
python3 -m uvicorn efatura_kdv.api:app --app-dir src --host 0.0.0.0 --port 8000
```

`DATABASE_URL` tanımlı değilse API başlangıçta (`lifespan` içinde) net bir
`RuntimeError` ile durur — sessizce yarım çalışmaz.

> Not: `uvicorn` komutu bazı ortamlarda doğrudan PATH'te olmayabilir
> ("command not found: uvicorn") — bu durumda `python3 -m uvicorn ...`
> şeklinde çalıştırmak gerekir (paket kullanıcı dizinine kurulu olabilir).

## Etkileşimli dokümantasyon

FastAPI otomatik Swagger arayüzü üretir:

```
http://localhost:8000/docs
```

## Endpoint'ler

Tam şema: `docs/reference/api-semasi.md`. Özet:

- `GET /saglik` — servis ayakta mı, NACE tablosu yüklü mü.
- `POST /fatura/kontrol-et` — ham UBL-TR XML + satıcı VKN + satıcı NACE
  kod(lar)ı alır, kalem bazlı KDV oran kontrolü sonucunu döner.
- `POST /fatura/gecmis-kontrol` — kalem adı + beyan edilen oran alır,
  satıcının bu kalemi geçmişte (outbox faturalarda) hangi oran(lar)la
  kestiğini döner. **Karar üretmez**, sadece bilgi/uyarı notu — ayrı bir
  endpoint, ana kontrole otomatik karışmaz (bkz. PROJECT.md §3.9).

## Örnek istek

```bash
curl -X POST http://localhost:8000/fatura/kontrol-et \
  -H "Content-Type: application/json" \
  -d @- <<'JSON'
{
  "fatura_xml": "<Invoice>...</Invoice>",
  "satici_vkn": "9860008925",
  "satici_nace_kodlari": ["532009"]
}
JSON
```

## Çoklu-kullanıcı davranışı

`NaceOranTablosu` uygulama başlarken **bir kez** PostgreSQL'den okunup
bellekte tutulur (`src/efatura_kdv/api.py` içindeki `_lifespan`) — her HTTP
isteği bu paylaşılan tabloyu okur, kendi DB bağlantısını açmaz. Birden fazla
kullanıcı aynı anda farklı faturaları bağımsız isteklerle gönderebilir;
istekler arasında paylaşılan mutable state yoktur (her istek kendi
`Fatura`/`SatirKontrolSonucu` nesnelerini üretir). Referans veri (NACE→oran)
değiştiğinde: migrasyonu tekrar çalıştır, sonra API sürecini yeniden başlat
(hot-reload yok, bilinçli basit tutuldu — referans veri nadiren değişiyor).

> ✅ **Gerçek PostgreSQL ile doğrulandı (2026-07-21):** Kullanıcı Docker'ı
> kurduktan sonra (Docker Desktop "manually paused" durumundaydı, unpause
> edildi) container port 5434'te ayağa kaldırıldı, migrasyon çalıştırıldı,
> API bu gerçek DB'ye karşı `uvicorn` ile başlatılıp `curl` ile gerçek HTTP
> istekleriyle test edildi: `GET /saglik` ✅, gerçek fatura ile
> `POST /fatura/kontrol-et` → doğru `uygun` kararı ✅, 5 eşzamanlı istek →
> tutarlı sonuç ✅, bozuk XML → 400 ✅, VKN uyuşmazlığı → 400 ✅. Önceki mock
> DB testinin yerini gerçek test aldı.

## Geçmiş fatura çapraz kontrolü kurulumu (opsiyonel, ayrı katman)

`/fatura/gecmis-kontrol` endpoint'i için `ubls/` klasöründeki outbox
faturaların da PostgreSQL'e taşınması gerekir:

```bash
python3 scripts/gecmis_faturalari_yukle.py
```

Bu betik `gecmis_fatura_kalemleri` tablosunu (yoksa oluşturarak) doldurur.
Şema ve gerekçe: `docs/reference/gecmis-fatura-semasi.md`, `PROJECT.md` §3.9.

Örnek istek:
```bash
curl -X POST http://localhost:8000/fatura/gecmis-kontrol \
  -H "Content-Type: application/json" \
  -d '{
    "satici_vkn": "0460351893",
    "kalemler": [
      {"kalem_adi": "DIN 15412 RS 5 P TRAVERS", "beyan_edilen_oranlar": [20.0]}
    ]
  }'
```

> ✅ **Gerçek Postgres ile doğrulandı (2026-07-21, sayılar 2026-07-22'de
> istisna düzeltmesiyle güncellendi — bkz. `docs/reference/gecmis-fatura-semasi.md`
> "İstisna kalemleri de kaydediliyor" bölümü):** 380/380 outbox faturasından
> 961 kalem-oran satırı yüklendi. Gerçek `curl` isteğiyle 3 senaryo test
> edildi: geçmişle uyumlu, geçmişle çelişen (uyarı notu), hiç görülmemiş kalem.

## Veritabanı bağlantısı — connection pool (2026-07-22)

`GecmisFaturaDeposu`, her sorgu/yazma için artık kendi `ThreadedConnectionPool`'unu
kullanıyor (varsayılan `minconn=2, maxconn=10`) — önceden her istek yeni bir
`psycopg2.connect()` açıp kapatıyordu, çok kullanıcılı yükte Postgres'in
`max_connections`'ını hızla tüketebiliyordu (bkz. `GOREV_MIMARI_DUZELTME.md`
#3). Eşzamanlı istek sayısı `maxconn`'u aşarsa client `503` alır (bkz.
`docs/reference/api-semasi.md` "Hata yönetimi" bölümü) — bu durumda pool
boyutu `GecmisFaturaDeposu(maxconn=...)` ile artırılabilir, aşırı
büyütülmesi Postgres'in kendi `max_connections`'ına dikkat gerektirir.

> ✅ **Gerçek Postgres ile doğrulandı (2026-07-22):** 10 eşzamanlı thread
> (varsayılan `maxconn=10` sınırında) hatasız tamamlandı; `docker stop` ile
> DB kapatılıp gerçek bir istekle `503` alındığı, `docker start` sonrası
> otomatik normale döndüğü doğrulandı.
