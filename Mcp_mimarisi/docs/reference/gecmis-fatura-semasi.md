# Geçmiş Fatura Kalemleri — Şema (çapraz kontrol katmanı)

Kod: `src/efatura_kdv/gecmis_kontrol.py`, migrasyon:
`scripts/gecmis_faturalari_yukle.py`. Mimari karar ve gerekçe:
`PROJECT.md` §3.9.

## Amaç

Bir fatura kaleminin **daha önce hangi KDV oranıyla kesildiğini** gösteren
bir çapraz kontrol/bilgi katmanı. Karar mekanizmasına (NACE kural kontrolü)
dokunmaz — sadece ek bir uyarı/güven sinyali üretir. Bkz. PROJECT.md §3.9
("§3.7'nin sınıflandırma yasağını neden ihlal etmediği").

## Kapsam: sadece `outbox` faturalar

`ubls/` klasöründeki 1828 dosyanın 1448'i `inbox` (bize kesilmiş), 380'i
`outbox` (bizim kestiğimiz). Sadece **outbox** dosyalar bu tabloya
kaydedilir — hepsi tek bir satıcı VKN'sinde (`0460351893`) doğrulandı
(2026-07-21, `parse_ubl_invoice` ile 380 dosyanın tamamı okunup satıcı
VKN'si karşılaştırıldı, hiçbiri farklı çıkmadı, hiç parse hatası olmadı).

## PostgreSQL Şeması

```sql
CREATE TABLE gecmis_fatura_kalemleri (
    id                    SERIAL PRIMARY KEY,
    satici_vkn            TEXT NOT NULL,
    kalem_adi_normalize   TEXT NOT NULL,   -- küçük harf + boşluk temizlenmiş
    kalem_adi_orijinal    TEXT NOT NULL,   -- kullanıcıya gösterim için ham hal
    oran                  NUMERIC NOT NULL,
    istisna_kodu          TEXT,            -- doluysa oran istisna kaynaklı (bkz. aşağı)
    fatura_no             TEXT NOT NULL,
    fatura_tarihi         DATE,
    kaynak_dosya          TEXT NOT NULL    -- hangi ubls/*.xml dosyasından geldiği (izlenebilirlik)
);

CREATE INDEX idx_gecmis_eslesme
    ON gecmis_fatura_kalemleri (satici_vkn, kalem_adi_normalize);
```

- `kalem_adi_normalize`: `kalem_adi.strip().lower()` + fazla boşlukların tek
  boşluğa indirgenmesi. Eşleşme burada yapılır — TAM string eşleşmesi,
  bulanık/benzerlik skoru kullanılmaz (kullanıcı kararı, 2026-07-21: basit,
  öngörülebilir, yanlış-pozitif eşleşme riski yok).
- Bir faturada aynı kalem adı birden fazla KDV kırılımıyla geçebilir (nadir)
  — bu durumda her kırılım ayrı bir satır olur.
- `kaynak_dosya`: bir eşleşme sonucunun hangi gerçek faturaya dayandığını
  sonradan doğrulayabilmek için (denetim/izlenebilirlik).
- `istisna_kodu` (2026-07-22 eklendi — bkz. aşağıdaki "İstisna kalemleri"
  bölümü): kalemin sayısal KDV oranı yoksa ama bir istisna kodu (ör. 301,
  ihracat) varsa `oran=0.0` + bu sütun dolu olarak kaydedilir.

## İstisna kalemleri de kaydediliyor (2026-07-22 düzeltmesi)

> ⚠️ **Bulunan hata (2026-07-22):** `AKK2025000000003-988e5bd8-cc92-468f-8058-816d8a9e89a5-outbox.xml`
> gerçek bir ihracat istisnası (kod 301, "11/1-a Mal İhracatı") taşıyan bir
> fatura, kullanıcı tarafından "istisna olmasına rağmen yakalanmamış" diye
> bildirildi. Kök neden: kalemin `vergi_tipi_kodu` alanı doğru `0015` (KDV)
> idi ama `Percent` (oran) alanı hiç yoktu (istisna kapsamında satıcı oran
> yazmamış — normal bir durum). `FaturaKalemi.kdv_oranlari` property'si
> `oran is not None` filtresi uyguladığı için bu kalemler için BOŞ liste
> dönüyordu; eski `_outbox_kalemlerini_topla()` de `for oran in
> kalem.kdv_oranlari:` döngüsüyle satır ürettiği için bu kalemler SESSİZCE
> atlanıyordu — istisna bilgisi hiçbir yere kaydedilmiyordu. (3 fatura bu
> yüzden migrasyonda "veri eksikliği" diye işaretlenmişti — aslında veri
> eksikliği değil, istisna kaynaklıydı.)
>
> **Düzeltme:** `scripts/gecmis_faturalari_yukle.py`'deki
> `_outbox_kalemlerini_topla()` artık kalemin `kdv_oranlari` boşsa
> `kalem_nace_esleme.kalem_istisna_kodlari()` (`_`-prefiksi kaldırılıp
> public yapıldı, kod tekrarını önlemek için) ile kalemde/fatura genelinde
> bir istisna kodu arıyor — varsa `oran=0.0` + `istisna_kodu` dolu olarak
> kaydediyor. Aynı düzeltme `gecmis_kontrol.py`'ye eklenen
> `fatura_kalemlerini_kayit_icin_hazirla()` ortak fonksiyonuyla
> `faturayi_gecmise_kaydet()` akışına (API/web arayüzü otomatik kayıt) da
> uygulandı — tek kaynak, iki yerde tekrar yazılmadı.
>
> ✅ **Sonuç, gerçek Postgres ile doğrulandı:** Migrasyon artık **380/380**
> outbox faturasını işliyor (önceden 377/380), 961 kalem-oran satırı (939'dan
> +22). `AKK2025000000003`'ün 8 kalemi artık `oran=0.0, istisna_kodu='301'`
> ile veritabanında. `gecmis_kontrol_et()` bu bilgiyi bilgi notunda ayrı
> gösteriyor: "`%0, istisna kodu 301 (2 kez, son: 2025-02-07)`" — sıradan
> %0 satırlarından (istisnasız) ayırt ediliyor. `faturayi_gecmise_kaydet()`
> akışı da (API `/fatura/coklu-kontrol` üzerinden) aynı faturayla gerçek
> `curl` isteğiyle test edildi: ilk gönderim → `gecmise_kaydedildi: true`,
> tekrar gönderim → `false` (yinelenen engellendi, davranış korundu).

## Sorgu deseni

```sql
SELECT oran, istisna_kodu, COUNT(*) AS kac_kez, MAX(fatura_tarihi) AS son_gorulme
FROM gecmis_fatura_kalemleri
WHERE satici_vkn = %s AND kalem_adi_normalize = %s
GROUP BY oran, istisna_kodu
ORDER BY kac_kez DESC;
```

Bu sorgu `gecmis_kontrol.py`'deki `gecmis_oranlari_getir()` fonksiyonunun
temelidir — bir (satıcı, kalem adı) çifti için "hangi oranlarla (ve hangi
istisna koduyla), kaç kez kesilmiş" özetini döner. `GROUP BY`'a
`istisna_kodu` eklenmesi (2026-07-22), aynı oranın istisnalı/istisnasız
görülme sayılarını ayrı satırlar olarak gösteriyor.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):** Şema,
> `scripts/gecmis_faturalari_yukle.py` ile gerçek 380 outbox faturasından
> üretilen kalem verisiyle dolduruldu. `GecmisFaturaDeposu`/`gecmis_kontrol_et()`
> gerçek DB ile 3 senaryoda test edildi: aynı fikirde (uyumlu, "%20 (21
> kez)..."), farklı fikirde (uyarı, "UYARI: ... mevzuat değişmiş olabilir"),
> hiç görülmemiş kalem (bilgi yok). `POST /fatura/gecmis-kontrol` endpoint'i
> gerçek `curl` isteğiyle aynı 3 senaryoyu doğru döndü.

## Otomatik kayıt — `faturayi_gecmise_kaydet()` (2026-07-21, MVP için eklendi)

Migrasyon (`scripts/gecmis_faturalari_yukle.py`) tek seferlik, geriye dönük
veri yüklemesi içindi. MVP'de kullanıcının (muhasebecinin) her yeni kestiği
faturayı manuel migrasyon çalıştırmadan otomatik biriktirebilmesi için
`gecmis_kontrol.py`'ye `faturayi_gecmise_kaydet()` eklendi — bu, API'nin
`POST /fatura/coklu-kontrol` endpoint'i ve web arayüzü tarafından, bir
fatura **başarıyla** kontrol edildikten (VKN uyuşmazlığı/parse hatası
olmadıktan) sonra otomatik çağrılır.

**Güvenlik:** Bu fonksiyon kendisi VKN doğrulaması YAPMAZ — çağıran taraf
(`satir_bazli_kontrol_et()`) zaten `satici_vkn`'nin faturanın gerçek satıcı
VKN'siyle eşleştiğini garanti ettiği için, bu fonksiyona kadar ulaşan her
fatura otomatik olarak outbox'tur.

**Yinelenen kayıt engeli:** `fatura_no` zaten tabloda varsa hiçbir satır
yazılmadan `False` döner — aynı faturanın tekrar tekrar yüklenmesi "kaç kez
kesilmiş" istatistiğini şişirmez.

```sql
-- Kontrol (yazmadan önce)
SELECT 1 FROM gecmis_fatura_kalemleri WHERE fatura_no = %s LIMIT 1;

-- Yeni satırlar (her kalem-oran/istisna çifti için)
INSERT INTO gecmis_fatura_kalemleri
    (satici_vkn, kalem_adi_normalize, kalem_adi_orijinal, oran, istisna_kodu, fatura_no, fatura_tarihi, kaynak_dosya)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
```

`kaynak_dosya` bu durumda gerçek bir dosya adı değil, `"coklu-kontrol-api"`
veya `"web-arayuz-coklu"` gibi bir kaynak etiketi taşır — hangi giriş
noktasından geldiğini ayırt etmek için.

> ⚠️ **Kritik hata bulundu ve düzeltildi (2026-07-21, aynı gün):**
> `test/web_arayuz.py`'nin ilk çoklu-dosya sürümü, kullanıcının kendi şirket
> VKN'sini formda hiç sormuyordu — bunun yerine doğrudan `fatura.satici.vkn`
> (faturanın kendi satıcısı) kullanıyordu. Bu, bir Turkcell **inbox**
> faturasının (satıcı VKN'si `9860008925`) yanlışlıkla "biz kesmişiz" gibi
> bu tabloya kaydedilmesine yol açtı — §3.9'un temel kapsam kısıtlamasını
> (sadece outbox) ihlal ediyordu. Hatalı kayıt tespit edilip (beklenmeyen
> VKN görülünce) silindi; form artık kullanıcının kendi VKN'sini zorunlu
> istiyor ve bunu faturanın gerçek satıcısıyla karşılaştırıyor (API
> tarafında bu kontrol baştan doğruydu, sadece web arayüzünde eksikti).
> Düzeltme gerçek inbox (reddedildi, kaydedilmedi) ve outbox (kabul edildi)
> faturalarıyla yeniden doğrulandı.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):** Yeni bir
> test faturası (`TEST_COKLU_9999`) ile: ilk gönderimde `gecmise_kaydedildi:
> true` + veritabanında 8 yeni satır; ikinci (aynı) gönderimde
> `gecmise_kaydedildi: false` + satır sayısı değişmedi (çiftlenme yok). Test
> verisi doğrulama sonrası temizlendi, tablo orijinal 377 fatura/939 satır
> durumuna döndürüldü.

## `islenmis_faturalar` — race condition düzeltmesi (2026-07-22)

> ⚠️ **Bulunan sorun (mimari denetim, `GOREV_MIMARI_DUZELTME.md` #1):**
> `faturayi_gecmise_kaydet()`'teki eski "`SELECT fatura_no var mı` → yoksa
> `INSERT`" mantığı iki ayrı adımdı, aralarında transaction/lock yoktu ve
> `fatura_no` üzerinde UNIQUE constraint de yoktu (sadece `(satici_vkn,
> kalem_adi_normalize)` index'i vardı). İki eşzamanlı istek aynı faturayı
> gönderirse ikisi de "yok" görüp ikisi de yazabiliyordu — çok kullanıcılı
> MVP'de bu, "kaç kez kesilmiş" istatistiğinin çift sayılmasına yol açardı.
>
> **Çözüm:** Ayrı, hafif bir "claim" tablosu eklendi:
>
> ```sql
> CREATE TABLE islenmis_faturalar (
>     fatura_no TEXT PRIMARY KEY,
>     islenme_zamani TIMESTAMPTZ NOT NULL DEFAULT now()
> );
> ```
>
> `fatura_no`'ya doğrudan `gecmis_fatura_kalemleri`de UNIQUE koyulamıyor
> çünkü bir fatura N kalem-satırı üretiyor (aynı `fatura_no` ile birden
> fazla satır normal) — bu yüzden ayrı bir claim tablosu gerekti.
> `faturayi_gecmise_kaydet()` (`src/efatura_kdv/gecmis_kontrol.py`) artık
> tek transaction içinde önce
> `INSERT INTO islenmis_faturalar (fatura_no) VALUES (%s) ON CONFLICT (fatura_no) DO NOTHING RETURNING fatura_no`
> çalıştırıyor — satır dönmezse (PRIMARY KEY çakıştı, biri önce commit
> etmiş) hiçbir şey yazmadan `False` dönüyor; satır dönerse aynı
> transaction'da asıl kalem satırları yazılıp commit ediliyor. Bu,
> PostgreSQL'in constraint garantisiyle atomik bir "kazanan tek istek"
> deseni kuruyor, ayrı bir uygulama-seviyesi lock gerekmiyor.
>
> ✅ **Gerçek Postgres ile doğrulandı:** 10 eşzamanlı thread'den aynı
> `fatura_no` (`RACE_TEST_001`) ile `faturayi_gecmise_kaydet()` çağrıldı —
> sadece 1 tanesi `True` döndü, 9 tanesi `False`; hem `gecmis_fatura_kalemleri`
> hem `islenmis_faturalar`'da tam olarak 1 kayıt oluştuğu doğrulandı. Test
> verisi sonrasında silindi.
>
> Şema artık Alembic migration'ları olarak da kayıtlı — bkz.
> `docs/how-to/migration-calistirma.md`, migration `7ec7f9c705a3`.
