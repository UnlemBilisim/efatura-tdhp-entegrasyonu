# NACE→KDV Oranı Excel Referans Dosyaları — Şema

Faz 1 kural kontrolünün (bkz. [`PROJECT.md`](../../PROJECT.md) §0.1) veri
kaynağı `nace_kdv (1).xlsx`'tir (kod: `src/efatura_kdv/nace_kural_kontrolu.py`).
`kdv_oran_referans2.xlsx` Faz 2 için hazırlanmış daha geniş bir referans
şablonudur (I/II sayılı liste, tevkifat kodları, NACE_KDV/NACE_ISTISNA). Üç
dosya da repo köküne yüklüdür.

> ✅ **Uygulandı (2026-07-20), sonra ⚠️ geri alındı (aynı gün):** `NACE_KDV`
> sayfası kısa bir süre `src/efatura_kdv/kalem_nace_esleme.py`'deki
> `NaceCozumTipiTablosu` tarafından okunuyordu (kalem→NACE eşleme ön-adımı,
> LLM'e ihtiyaç var mı sorusu için). Kullanıcı aynı gün mimariyi
> basitleştirdi (kalem içeriğine bakılmıyor, LLM kaldırıldı — bkz.
> `docs/explanation/akis-sirasi-ve-faz-plani.md`) — `NaceCozumTipiTablosu`
> ve dolayısıyla `NACE_KDV` sayfasının kod tarafından kullanımı **kaldırıldı**.
> Şu an Faz 1 akışı SADECE `nace_kdv (1).xlsx`/`NaceOranTablosu`'nu
> kullanıyor. `kdv_oran_referans2.xlsx`'in TÜM sayfaları (KILAVUZ, I/II
> sayılı liste, TEVKIFAT_KODLARI, NACE_KDV, NACE_ISTISNA) yeniden kodda
> kullanılmıyor — hepsi Faz 2 referans şablonu olarak duruyor.

## `nace_kdv (1).xlsx`

4 sayfa içerir:

### Sayfa: `2025_KESIM_BOLUM_GRUP_SINIF` (A1:T2157)

NACE hiyerarşisinin tam kırılımı + her en-detaylı faaliyet kodu için geçerli
KDV oranları. Faz 1 kontrolünün **birincil kaynağı** — sorgu buradan yapılır.

Sütunlar: `KESIMKODU, KESIMADI, BOLUMKODU, BOLUMADI, GRUPKODU, GRUPADI,
SINIFKODU, SINIFADI, FAALIYETKODU, FAALIYETADI, KDV%0, KDV %1, KDV %10,
KDV %20, KDV İSTİSNASI, AÇIKLAMA`

- `FAALIYETKODU`: 6 haneli NACE faaliyet kodu — faturadaki NACE koduyla
  eşleştirilecek anahtar alan.
- `KDV%0 / KDV %1 / KDV %10 / KDV %20`: dolu (ör. `'1'`, `20`) ise o oran bu
  NACE için geçerlidir, boş (`None`) ise geçerli değildir. **Birden fazla
  sütun aynı anda dolu olabilir** (ör. tarım kodlarında hem `KDV %1` hem
  `KDV %20` dolu) — bu proje içinde "çok oranlı NACE" denen durum budur.
- `KDV İSTİSNASI`: doluysa (ör. `13/ı`) istisna madde referansıdır.

### Sayfa: `2024_KDV_ORANLARI` (A1:O2218)

2024 yılı faaliyet kodu bazlı oranlar + 2024→2025 kod eşlemesi. Sütunlar:
`KESİM KODU, KESİM ADI, BÖLÜM KODU, BÖLÜM ADI, SINIF KODU, SINIF ADI, 2024
FAALİYET KODU, 2025 FAALİYET ADI, KDV %1, KDV %10, KDV %20, KDV İSTİSNASI,
2025 FAALİYET KODU, 2025 FAALİYET ADI, AÇIKLAMA`. Faturanın tarihi 2024'e
aitse bu sayfa kullanılabilir; `AÇIKLAMA` sütunu kodun 2024 listesinde olup
olmadığını not eder (ör. `"2024 Yılı Listesinde VAR"`).

### Sayfa: `2024_2025_DONUSUM_KODLARI` (A1:D2219)

Salt kod eşleme tablosu: `20241231_NACE_REV2, 20241231_NACE_REV2 TANIMI,
20250101_NACE_REV2.1, 20250101_NACE_REV2.1 TANIMI`. Faturadaki NACE kodu
birincil sayfada bulunamazsa, bu tablo üzerinden eski/yeni kod dönüşümü
denenebilir.

### Sayfa: `KDV İSTİSNASI OLAN NACE KODLARI` (A1:P123)

Birincil sayfayla aynı sütun şeması, sadece istisna kodu olan (`KDV
İSTİSNASI` dolu) satırların alt kümesi. Ayrı bir filtrelenmiş görünüm.

### Sayfa: `2026_KOD_DEGISIKLIKLERI` (yeni, 2026-07-17) — **2026 itibarıyla tam güncel NACE-KDV tablosu**

> ✅ Uygulandı (2026-07-17, 2 aşamalı): İlk aşamada bu sayfa sadece
> `nace_kod_degisikligi_2026_03_24.xlsx`'teki 15 değişikliği (18 satır)
> listeleyen bir özet olarak eklenmişti (script: `nace_2026_sayfa_ekle.py`).
> Kullanıcı isteği üzerine ikinci aşamada (script: `nace_2026_tam_liste.py`,
> tek seferlik kullanıldı, repo'ya dahil değil) **tüm** `2025_KESIM_
> BOLUM_GRUP_SINIF` kodları bu sayfaya taşınarak sayfa **2026 itibarıyla
> geçerli tam NACE-KDV tablosuna** dönüştürüldü:
>
> - 26 eski (değişen/birleşen/bölünen) `FAALIYETKODU` bu sayfaya dahil
>   **edilmedi**.
> - 18 yeni/güncellenmiş kod, doğru hiyerarşi + güncel KDV oranıyla
>   eklendi (bazıları — `432301`, `619099`, `289399/289302/289303` — zaten
>   2025 sayfasında bağımsız kod olarak vardı; bu durumlarda duplike
>   oluşmadan tek satır, güncel bilgiyle tutuldu).
> - Geri kalan **2120 kod**, 2025 sayfasından birebir aynen kopyalandı.
> - Toplam: **2138 satır** (2153 − 26 eski + 18 yeni − 7 zaten-var-olan
>   çakışma = 2138; tam doğrulandı: duplike yok, eksik/fazla kod yok).
> - `2025_KESIM_BOLUM_GRUP_SINIF` sayfasına **hâlâ dokunulmadı** — eski
>   kodlar orada olduğu gibi duruyor, bu sayfa ayrı bir "2026 görünümü".
>
> Sütunlar: `DEĞİŞİKLİK TÜRÜ, ESKİ KOD, YENİ KOD, YENİ FAALİYET ADI,
> KESIMKODU, KESIMADI, BOLUMKODU, BOLUMADI, GRUPKODU, GRUPADI, SINIFKODU,
> SINIFADI, KDV%0, KDV %1, KDV %10, KDV %20, KDV İSTİSNASI, AÇIKLAMA`.
> Değişmeyen kodlarda `DEĞİŞİKLİK TÜRÜ` ve `ESKİ KOD` **boştur** (sadece
> `YENİ KOD` sütunu doludur — bu sütun artık fiilen "FAALIYETKODU" gibi
> okunmalı). Değişen kodlarda `ESKİ KOD` birden fazla kod içerebilir
> (virgülle ayrılmış, BİRLEŞME durumunda — ör. `051001, 051002`).
>
> **İstisna düzeltmesi:** `071000` ve `089200`'e birleşen eski kodlardan
> ikisi (`072908`, `089906`), `KDV İSTİSNASI OLAN NACE KODLARI` sayfasında
> `13/c` istisna koduyla kayıtlıydı; değişiklik dosyası bunu belirtmiyordu
> (sadece `KDV%20` diyordu). Kullanıcı onayıyla bu istisna bilgisi
> `2026_KOD_DEGISIKLIKLERI` sayfasında `071000`/`089200` satırlarına da
> eklendi — birincil sayfadaki `071000`/`089200` kayıtları ise
> **değiştirilmedi**.
>
> ✅ **Uygulandı (2026-07-20):** Bu sayfa 2026-07-17'de eklenmişti ama
> `nace_kdv (1).xlsx` dosyasının o tarihten sonraki bir noktada eski haline
> (17'den önceki hale) döndüğü tespit edildi — dosyanın işletim sistemi
> değişiklik tarihi 2026-07-16'ydı ve sayfa fiilen **yoktu**; bu yüzden
> `NaceOranTablosu.__init__` (`src/efatura_kdv/nace_kural_kontrolu.py`)
> `KeyError: Worksheet 2026_KOD_DEGISIKLIKLERI does not exist` ile
> çöküyordu — Faz 1 kural kontrolü fiilen çalışmıyordu. Kullanıcı onayıyla
> sayfa `nace_kod_degisikligi_2026_03_24.xlsx` (15 değişiklik) +
> `2025_KESIM_BOLUM_GRUP_SINIF` (2153 kod) + `KDV İSTİSNASI OLAN NACE
> KODLARI` (13/c düzeltmesi) birleştirilerek yeniden oluşturuldu (tek
> seferlik script, repo'ya dahil değil). Sonuç doğrulandı: 2138 satır,
> duplike yok, eski kodlar (`051001`, `072908`, `611099` vb.) sayfada
> bulunmuyor, `071000`/`089200` istisna notu (`13/c`) korunuyor.
> `kontrol_et()` çalıştırılıp gerçek kodlarla (`032102`, `222606`, `108907`)
> test edildi — beklenen kararları üretiyor. Değişiklik öncesi dosya
> `nace_kdv (1)_yedek_2026-07-20.xlsx` olarak yedeklendi.

## `nace_kod_degisikligi_2026_03_24.xlsx`

Tek sayfa (`Sayfa1`, A1:AA1012). Sütunlar: `Tür, NACE Kodu, Yeni Kod, NACE
Açıklama, KDV 0, KDV 1, KDV 10, KDV 20` (+ boş sütunlar AA'ya kadar).

- `Tür`: `BİRLEŞME` gibi bir değişiklik türü (bazı satırlarda boş).
- `NACE Kodu` / `Yeni Kod`: eski kod → yeni/birleşmiş kod eşlemesi.
- `KDV 0/1/10/20`: yeni kodun oranı (sayısal, ör. `20.0`).

2026-03-24 tarihli daha güncel bir kod değişikliği/birleşme notu.

> ✅ Uygulandı (2026-07-17): Bu dosyadaki 1011 satırın **996'sı** sadece "bu
> kod 2026'da da aynen geçerli" bilgisi taşır (`Tür` boş, `Yeni Kod` boş,
> KDV sütunları boş) — bunlar zaten `nace_kdv (1).xlsx` birincil sayfasında
> mevcuttur, ayrıca işlenmesi gerekmez. Gerçek değişiklik sadece **15
> kayıttır**, `Tür` sütunu bunlarda doludur ve 3 alt türe ayrılır:
>
> - **BİRLEŞME**: birden fazla eski kod tek bir yeni kodda birleşir. Değişen
>   satırın kendisi `Yeni Kod` + oranı taşır; hemen altındaki
>   `Tür=boş, NACE Kodu=dolu` satırları o birleşimin içine giren eski
>   kodlardır (ör. `051001, 051002` → `051000`).
> - **KOD DEĞİŞİKLİĞİ**: tek satırda eski kod (`NACE Kodu`) → yeni kod
>   (`Yeni Kod`) + yeni oran, doğrudan eşleme.
> - **BÖLÜNME**: tek eski kod birden fazla yeni koda ayrılır. Değişen satırın
>   kendisi eski kodu taşır (`NACE Kodu`); hemen altındaki
>   `Tür=boş, Yeni Kod=dolu` satırları bölünmenin sonucu yeni kodlardır (ör.
>   `282904` → `289399, 289302, 289303`).
>
> Bazı "yeni kodlar" (ör. `432301`, `619099`) zaten birincil sayfada
> bağımsız bir NACE kodu olarak mevcuttu — bu durumda eski kod duplike
> edilmeden sadece o mevcut satırın KDV oranı güncellendi.

## PostgreSQL Şeması (2026-07-21 — Faz 1 veri kaynağı excel'den DB'ye taşındı)

> ✅ **Uygulandı (2026-07-21):** `nace_kural_kontrolu.py`'deki `NaceOranTablosu`
> artık `nace_kdv (1).xlsx`'i doğrudan açmıyor; `2026_KOD_DEGISIKLIKLERI`
> sayfasındaki veri, `scripts/excel_to_postgres.py` migrasyon betiğiyle
> aşağıdaki `nace_oranlari` tablosuna bir kereye mahsus taşındı ve
> `NaceOranTablosu` artık bu tabloyu `DATABASE_URL` env var'ıyla sorguluyor.
> Gerekçe: çoklu-kullanıcı/eşzamanlı erişim ihtiyacı (bkz. PROJECT.md
> §3.6.1) — excel dosyası eşzamanlı erişimde uygun değil, ayrıca bu Faz 2'nin
> zaten planlanan PostgreSQL Mevzuat Kural Deposu kararının erken uygulanması.
> Excel dosyaları (`nace_kdv (1).xlsx` vb.) repoda referans/yedek olarak
> duruyor ama artık kod tarafından okunmuyor.

```sql
CREATE TABLE nace_oranlari (
    nace_kodu     TEXT PRIMARY KEY,   -- 2026_KOD_DEGISIKLIKLERI."YENİ KOD"
    kdv_0         BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_1         BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_10        BOOLEAN NOT NULL DEFAULT FALSE,
    kdv_20        BOOLEAN NOT NULL DEFAULT FALSE,
    kaynak_satir  JSONB              -- ham excel satırı (denetim/izlenebilirlik için)
);
```

Her `kdv_*` sütunu excel'deki karşılık gelen `KDV%0`/`KDV %1`/`KDV %10`/
`KDV %20` sütununun dolu/boş durumunu birebir yansıtır — bir NACE'nin birden
fazla `TRUE` sütunu olması "çok oranlı NACE" durumudur (excel'deki anlamıyla
aynı). `kaynak_satir`, migrasyon sırasında hangi ham excel satırından
türetildiğini saklar — ileride bir tutarsızlık şüphesi doğarsa excel'e geri
dönüp karşılaştırmaya gerek kalmadan JSONB üzerinden doğrulanabilir.

Bağlantı `DATABASE_URL` env var'ı ile yapılandırılır (bkz.
`docs/how-to/postgres-kurulum.md`). Şema `NaceOranTablosu.izin_verilen_oranlar()`
dışına sızmaz — `kontrol_et()` ve üstü hâlâ sadece `list[float]` görür, DB'ye
geçiş çağıran koddan tamamen izole.

> ✅ **Uygulandı (2026-07-28):** `nace_kodu` sütunu Excel'deki `YENİ KOD`
> değerini **noktasız** taşır (ör. `254004`, `25.40.04` değil) — bu, taşıma
> script'inin (`excel_to_postgres.py:59`) hiç normalizasyon yapmadan
> `str(kod).strip()` kullanmasından kaynaklanır. Gerçek bir faturada
> (AKL2026000000211, NACE `25.40.04` noktalı gönderildi) bu format farkı
> yüzünden kod tabloda **var olduğu halde** "bulunamadı" denip fatura
> sessizce `insan_incelemesi_gerekli`'ye düşüyordu. Düzeltme:
> `nace_kural_kontrolu.py::_nace_kodu_normalize_et()` eklendi — tablo
> yüklenirken (`_tabloyu_yukle`) VE sorgu anında (`izin_verilen_oranlar`)
> aynı normalizasyon (`.strip().replace(".", "")`) uygulanır, böylece
> çağıran taraf NACE kodunu noktalı ya da noktasız gönderse de doğru
> eşleşir. Canlı serviste (`/fatura/isle`, `satici_nace_kodlari: ["25.40.04"]`)
> doğrulandı — düzeltmeden önce `genel_karar: insan_incelemesi_gerekli`,
> sonra `genel_karar: uygun` döndü.

## Faz 1 sorgu sırası (güncel, 2026-07-17 — tarih ayrımından vazgeçildi)

> ⚠️ Bir ara deneme (2026-07-17, aynı gün) eski kodları birincil sayfadan
> silip yerine yeni kodları yazmıştı; kullanıcı bu yaklaşımı **geri aldı**
> (`nace_kdv (1)_yedek_2026-07-17.xlsx` yedeğinden geri yükleme) ve bunun
> yerine ayrı `2026_KOD_DEGISIKLIKLERI` sayfası eklenmesini istedi.
>
> İlk kural kontrol modülü sürümü fatura tarihine göre bu sayfa ile
> `2025_KESIM_BOLUM_GRUP_SINIF` arasında seçim yapıyordu. Kullanıcı aynı gün
> bu tarih ayrımından **vazgeçti** ("en güncel nace kodlarını kullansın") —
> artık fatura tarihinden bağımsız, HER ZAMAN `2026_KOD_DEGISIKLIKLERI`
> (2026 itibarıyla geçerli tam NACE-KDV tablosu) kullanılıyor.
> `2025_KESIM_BOLUM_GRUP_SINIF` sayfası artık Faz 1 sorgusunda kullanılmıyor
> (dosyada arşiv olarak duruyor, silinmedi).

1. `2026_KOD_DEGISIKLIKLERI` sayfasında `YENİ KOD` sütununda ara — bu sayfa
   2026 itibarıyla geçerli tam NACE-KDV tablosudur, tek adım yeterlidir.
2. Bulunamazsa → `insan incelemesi gerekli` (bkz. `PROJECT.md` §0.1 adım 5).
   Not: artık geçersiz olan eski bir kod (ör. `051001`) bu sayfada
   bulunamaz — bu KASITLI bir davranıştır, eski kod ayrıca yeni koda
   yönlendirilmez.

> ✅ Uygulandı (2026-07-17): Bu şema `python3 + openpyxl` ile dosyalar
> doğrudan okunarak doğrulandı (varsayım değil, gerçek içerik). Faz 1 kural
> kontrolü kodu (`src/efatura_kdv/nace_kural_kontrolu.py`) bu sıraya göre
> yazıldı ve 6 senaryoda doğrulandı.

---

## `kdv_oran_referans2.xlsx` (Faz 2 referans şablonu)

Faz 2 (mevzuat MCP, tevkifat, istisna — bkz. PROJECT.md §3.6-3.7) için
hazırlanmış daha geniş bir referans dosyası. 6 sayfa:

| Sayfa | İçerik |
|---|---|
| `KILAVUZ` | Kullanım notu — "3 kademeli çalışma mantığı" (I sayılı liste → II sayılı liste → NACE) özetlenir. Kaynak: 2007/13033 sayılı Karar eki. |
| `I_SAYILI_LISTE_%1` | %1 KDV'ye tabi kalemler (gıda, tarım ürünleri vb.), `liste_no/bolum/sira_no/oran/durum/kalem_tanimi/...` şemasıyla, 22 satır. |
| `II_SAYILI_LISTE_%10` | %10 KDV'ye tabi kalemler, aynı şema, 39 satır. |
| `TEVKIFAT_KODLARI` | 601-6xx tevkifat kodları: `kod, tur, kalem_tanimi, tevkifat_orani, durum, sadece_belirlenmis_alici, alt_sinir_kdv_dahil, not, yururluk_basi`. 28 satır. CLAUDE.md'deki "tevkifat alt sınırı 12.000 TL" gerçeği bu sayfada `alt_sinir_kdv_dahil` sütunuyla doğrulanır. |
| `NACE_KDV` | NACE koduna göre KDV kategorisi/beklenen oran. Şema: `nace_kodu, faaliyet_adi, kesim, bolum_adi, sinif_adi, aday_oranlar, cozum_tipi, beklenen_oran, istisna_maddesi, aciklama`. `cozum_tipi`: `KESIN` (tek aday oran, `beklenen_oran` dolu) veya `KALEM_GEREKLI` (birden fazla aday — istisna dahil, `beklenen_oran` boş, kalem bazında çözülmeli). Bu, PROJECT.md §3.7'deki NACE tek-oranlı/çok-oranlı ayrımının somut karşılığıdır. |
| `NACE_ISTISNA` | Sadece istisna kodu olan NACE'lerin filtrelenmiş görünümü, 119 satır. |

> ✅ Uygulandı (2026-07-17): `NACE_KDV` sayfası, `nace_kdv (1).xlsx`'in
> `2026_KOD_DEGISIKLIKLERI` (2026 itibarıyla güncel) sayfasından türetilerek
> güncellendi — 2153 eski satır yerine 2138 güncel satır (`nace_kodu` =
> `YENİ KOD`). Dönüşüm mantığı: dolu KDV%0/%1/%10/%20 sütunları +
> (varsa) istisna kodu `aday_oranlar`a birleştirilir; tek aday oran (istisna
> hariç) varsa `cozum_tipi=KESIN` + `beklenen_oran` dolu, birden fazla aday
> (istisna dahil) varsa `cozum_tipi=KALEM_GEREKLI` + `beklenen_oran` boş —
> bu, dönüşümden önceki sayfanın kendi deseniyle (119 istisnalı satır
> örneklerinden doğrulandı) birebir aynı mantıktır. Duplike/eksik NACE kodu
> yok; tek istisna `431200` (şantiyenin hazırlanması) — kaynak veride
> (`2026_KOD_DEGISIKLIKLERI`) bu kodun oranı hiç belirtilmemiş, bu yüzden
> `aday_oranlar` boş ve `cozum_tipi=KALEM_GEREKLI` kalıyor (veri eksikliği,
> dönüşüm hatası değil — Faz 1/2 mantığında bu zaten "insan incelemesi
> gerekli"ye düşer). Diğer 5 sayfaya (KILAVUZ, I/II sayılı liste,
> TEVKIFAT_KODLARI, NACE_ISTISNA) dokunulmadı. Yedek:
> `kdv_oran_referans2_yedek_2026-07-17.xlsx`.
>
> ✅ **Uygulandı (2026-07-20):** `2026_KOD_DEGISIKLIKLERI` sayfası aynı gün
> onarıldıktan sonra (bkz. yukarıdaki 2026-07-20 notu) `NACE_KDV` sayfası
> **yeniden** türetildi — bu sayfa hâlâ eski 2153 satırlık haliyle
> kalmıştı, kaynak sayfa değiştiği için senkron değildi. Aynı dönüşüm
> mantığı tekrar uygulandı: 2138 satır (1360 `KESIN` + 778
> `KALEM_GEREKLI`), duplike/eksik yok, `071000`/`089200` istisna notu
> (`13/c`, `KALEM_GEREKLI`) ve `431200` özel durumu (boş `aday_oranlar`)
> doğrulandı. Diğer 5 sayfaya yine dokunulmadı. Yedek:
> `kdv_oran_referans2_yedek_2026-07-20.xlsx`.
