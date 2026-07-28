# PostgreSQL kurulumu ve Faz 1 verisinin taşınması

Faz 1'in NACE+oran verisi 2026-07-21'de excel'den PostgreSQL'e taşındı
(gerekçe: çoklu-kullanıcı/eşzamanlı erişim — bkz. `PROJECT.md` §3.6.1,
`docs/reference/nace-kdv-excel-yapisi.md` "PostgreSQL Şeması"). Bu dosya,
yerel bir geliştirme ortamında bu veritabanını sıfırdan ayağa kaldırma
adımlarını anlatır.

## 1. PostgreSQL'i çalıştır (Docker)

```bash
docker run --name efatura-kdv-postgres \
    -e POSTGRES_USER=efatura \
    -e POSTGRES_PASSWORD=efatura \
    -e POSTGRES_DB=efatura_kdv \
    -p 5434:5432 \
    -d postgres:16
```

> ⚠️ **Port 5434 kullanılıyor, 5432 değil** (2026-07-21'de tespit edildi):
> Bu makinede zaten iki yerel PostgreSQL kurulumu (`/Library/PostgreSQL/16`,
> `/Library/PostgreSQL/17`) 5432 ve 5433 portlarını kullanıyordu — standart
> `5432:5432` port eşlemesi "address already in use" hatasıyla başarısız
> oldu. Container'ı **5434** host portuna (container içinde hâlâ 5432)
> bağladık; kullanıcının kendi ortamında port çakışması yoksa 5432 de
> kullanılabilir, ama bu makinede 5434 gerekiyor.

Docker kurulu değilse: `brew install --cask docker`, ardından Docker Desktop
uygulamasını açıp ilk kurulum adımlarını (izin, arka plan servisi)
tamamlamak gerekir. Docker Desktop "manually paused" durumda olabilir —
Whale menüsünden/Dashboard'dan unpause etmek gerekir.

## 2. Bağlantı bilgisini env var olarak ayarla

```bash
export DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv"
```

Bu env var'ı kalıcı yapmak için `~/.zshrc`'ye eklenebilir. `NaceOranTablosu`
(`src/efatura_kdv/nace_kural_kontrolu.py`) bu değişkeni okur; tanımlı
değilse `RuntimeError` fırlatır.

## 3. Python bağımlılığını kur

```bash
python3 -m pip install psycopg2-binary
```

## 4. Excel verisini PostgreSQL'e taşı (migrasyon)

```bash
python3 scripts/excel_to_postgres.py
```

Bu betik `nace_kdv (1).xlsx`'in `2026_KOD_DEGISIKLIKLERI` sayfasını okuyup
`nace_oranlari` tablosunu (yoksa oluşturarak) doldurur. Tekrar
çalıştırıldığında tabloyu güvenle yeniden doldurur (idempotent — `TRUNCATE`
+ `ON CONFLICT DO UPDATE`).

## 5. Doğrula

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from efatura_kdv.nace_kural_kontrolu import NaceOranTablosu, kontrol_et
tablo = NaceOranTablosu()
print(kontrol_et('471100', 20.0, tablo))
"
```

Excel dosyaları (`nace_kdv (1).xlsx` vb.) repoda referans/yedek olarak
kalmaya devam ediyor ama artık kod tarafından okunmuyor — veri kaynağı
değişikliği gerektiğinde (ör. yeni bir NACE güncellemesi geldiğinde) önce
excel güncellenir, sonra `scripts/excel_to_postgres.py` tekrar çalıştırılır.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):** Yukarıdaki
> adımlar bu ortamda gerçekten çalıştırıldı (Docker container port 5434,
> `postgres:16`). Migrasyon 2138 NACE kodunu doğru yazdı; `NaceOranTablosu`
> gerçek DB bağlantısıyla doğru sonuç üretti (`532009` → `uygun`, bilinmeyen
> kod → `insan_incelemesi_gerekli`). Mock DB testinin yerini artık gerçek
> DB testi aldı — önceki "test edilemedi" notu geçersiz.
