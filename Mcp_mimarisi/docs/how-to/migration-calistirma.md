# Veritabanı Migration'larını Çalıştırma (Alembic)

> ✅ **Uygulandı (2026-07-22):** Şema artık `scripts/excel_to_postgres.py` /
> `scripts/gecmis_faturalari_yukle.py` içindeki elle `CREATE TABLE IF NOT
> EXISTS` yerine Alembic migration'larıyla (`alembic/versions/`) versiyonlanıyor
> (bkz. `GOREV_MIMARI_DUZELTME.md` #2). Bu iki script hâlâ var ve veri
> YÜKLEME (excel/ubls klasöründen okuyup satır ekleme) işini yapmaya devam
> ediyor — sadece tablo ŞEMASINI oluşturma sorumluluğu Alembic'e taşındı.

## Neden Alembic

Önceden şema versiyon/rollback takibi olmadan elle yönetiliyordu — her
script kendi `CREATE TABLE IF NOT EXISTS`'ini çalıştırıyordu. Bu, birden
fazla ortamda (geliştirme, sunucu) şemanın senkron kalıp kalmadığını takip
etmeyi zorlaştırıyordu.

## Kurulum

```bash
python3 -m pip install alembic==1.16.5
```

(`requirements.txt`'e eklendi.)

## Bağlantı

`alembic/env.py`, `DATABASE_URL` env var'ını okuyup `alembic.ini`'deki
`sqlalchemy.url`'in yerine geçiriyor — projenin geri kalanıyla
(`nace_kural_kontrolu.py`, `gecmis_kontrol.py`) aynı desen. `alembic.ini`'ye
bağlantı bilgisi elle yazılmaz.

```bash
export DATABASE_URL="postgresql://efatura:efatura@localhost:5434/efatura_kdv"
```

## Mevcut (zaten kurulu) bir veritabanında ilk kullanım

Bu proje Alembic'e geçmeden önce zaten `nace_oranlari` ve
`gecmis_fatura_kalemleri` tabloları elle oluşturulmuş bir veritabanı ile
çalışıyorsa (örn. bu projenin geliştirme DB'si veya production'a ilk
deploy), migration `9846b14dc658` (ilk şema) bu tabloları YENİDEN
oluşturmaya ÇALIŞIR ve tablo zaten var olduğu için hata verir. Bunun yerine:

```bash
# Tabloları yeniden oluşturmadan, "bu migration zaten uygulanmış" diye işaretle:
alembic stamp 9846b14dc658

# Sonrasında yeni migration'ları normal şekilde uygula:
alembic upgrade head
```

**Sıfırdan (tablosuz) yeni bir veritabanında** ise doğrudan:

```bash
alembic upgrade head
```

yeterli — tüm migration zincirini baştan çalıştırır.

## Yeni migration ekleme

```bash
alembic revision -m "kisa_aciklama"
```

Oluşan `alembic/versions/<hash>_kisa_aciklama.py` dosyasındaki `upgrade()`/
`downgrade()` fonksiyonlarını elle doldur (bu proje autogenerate yerine elle
yazmayı tercih ediyor — `op.create_table`/`op.add_column` gibi Alembic
operation'larıyla, tam kontrol için).

## Mevcut durumu görüntüleme

```bash
alembic current   # DB'nin şu an hangi revizyonda olduğunu gösterir
alembic history    # tüm migration zincirini listeler
```

## Geçmiş

- `9846b14dc658` — ilk şema: `nace_oranlari`, `gecmis_fatura_kalemleri`
  (mevcut elle-kurulmuş şemanın olduğu gibi kaydı, yeni bir şey eklemez).
- `7ec7f9c705a3` — `islenmis_faturalar` claim tablosu (bkz.
  `docs/reference/gecmis-fatura-semasi.md` "race condition düzeltmesi"
  bölümü).

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-22):**
> Geliştirme DB'sinde (`efatura-kdv-postgres` Docker container, port 5434)
> `alembic stamp 9846b14dc658` ile mevcut tablolar işaretlendi, ardından
> `alembic upgrade head` ile `7ec7f9c705a3` gerçekten çalıştırılıp
> `islenmis_faturalar` tablosu oluşturuldu. `alembic current` çıktısı
> `7ec7f9c705a3 (head)` olarak doğrulandı.
