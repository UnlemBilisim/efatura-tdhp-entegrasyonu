# CLAUDE.md — E-Fatura KDV/Vergi Oran Doğrulama Sistemi

Bu dosya, bu dizinde çalışan Claude Code (ve diğer AI ajanları) için proje rehberidir.

## Proje nedir?

Var olan bir e-fatura → Tek Düzen Hesap Planı aktarım sisteminin **önüne**
eklenen bağımsız bir doğrulama katmanı: gelen UBL-TR XML e-faturayı otonom
olarak inceleyip KDV oranı (Faz 2'de ayrıca tevkifat ve istisna) açısından
mevzuata uygun olup olmadığına karar verir. Girdi: fatura (NACE kodu + beyan
edilen KDV oranı + kalem metni). Çıktı üç değerden biri: **uygun / uyumsuz /
insan incelemesi gerekli**. `uygun` dönerse fatura **sonra** Tek Düzen Hesap
Planı eşleme modülüne aktarılır — akış sırası bu şekilde (önce doğrulama,
sonra hesap kodu eşleme), 2026-07-17'de kullanıcı tarafından netleştirildi
(bkz. `PROJECT.md` §0.1). Sistem kullanıcıyla soru-cevaba girmez, tamamen
otonom çalışır.

**İki fazlı kapsam (2026-07-17):**
- **Faz 1 (şimdiki hedef):** Sadece NACE+KDV Excel referans tablolarıyla
  (`nace_kdv (1).xlsx`, `nace_kod_degisikligi_2026_03_24.xlsx`) kural tabanlı
  kontrol — "beyan edilen oran, NACE'nin excel'de izin verilen oranlarından
  biri mi". Mevzuat MCP'si, LLM ile kalem sınıflandırma, tevkifat/istisna
  kontrolü bu fazda YOK.
- **Faz 2 (sonra):** Sıralı agent workflow + mevzuat MCP aracı (tarih bazlı,
  mevzuat.gov.tr/GİB kaynaklı) entegre edilir; tevkifat, istisna, çok-oranlı
  NACE'lerde LLM ile kalem/alt-kategori sınıflandırması eklenir.

Bu repo yalnızca **doğrulama katmanını** kapsar. Faturayı Tek Düzen Hesap
Planı'na eşleyen vektör-benzerlik modülü ayrı bir sistemdir, bu repoda değildir
ve **dokunulmaz** — bu katman ona girdi vermez, ondan girdi de almaz; sadece
kendi kararı `uygun` olduğunda faturayı ona iletir.

## Durum

Faz 1'in ilk iki alt-adımı tamamlandı (2026-07-17): (1) UBL-TR fatura
parser'ı (`src/efatura_kdv/ubl_parser.py`), `ubls/` altındaki 1828 gerçek
fatura üzerinde hatasız test edildi (şema: `docs/reference/ubl-fatura-yapisi.md`).
(2) NACE→oran kural kontrol modülü (`src/efatura_kdv/nace_kural_kontrolu.py`)
— `nace_kdv (1).xlsx`'in `2026_KOD_DEGISIKLIKLERI` sayfasını (2026 itibarıyla
tam güncel NACE-KDV tablosu) kullanır, fatura tarihinden bağımsızdır
(kullanıcı kararı), `kontrol_et()` §0.1'deki 5 adımlı mantığı uygular (şema:
`docs/reference/nace-kdv-excel-yapisi.md`). **2026-07-20 düzeltmesi:** bu
sayfa dosyada bir noktada kaybolmuştu (kod `KeyError` ile çöküyordu),
`nace_kod_degisikligi_2026_03_24.xlsx` + ana tablo + istisna sayfası
birleştirilerek yeniden oluşturuldu ve `kontrol_et()` gerçek kodlarla test
edilerek doğrulandı — detay: `docs/reference/nace-kdv-excel-yapisi.md`. Faz 2 için referans dosyası
(`kdv_oran_referans2.xlsx` — I/II sayılı liste, tevkifat kodları, NACE_KDV/
NACE_ISTISNA) repoya yüklü ve `NACE_KDV` sayfası güncel tutuluyor, ama Faz 2
mevzuat MCP + agent workflow tasarımı henüz koda dökülmedi — bkz. PROJECT.md
§3.6, §3.7, §0.1.

**Faz 1'in 3. alt-adımı da tamamlandı (2026-07-20, sonradan basitleştirildi):**
kalem (satır) bazında oran kontrolü (`src/efatura_kdv/kalem_nace_esleme.py`).
VKN→NACE excel lookup YAZILMADI — satıcının NACE kod(ları) fatura ile
birlikte dışarıdan (`SaticiNaceBilgisi`) geliyor (kullanıcı kararı: sistem
sadece fatura sahibinin kestiği faturalarda çalışır).

**⚠️ Mimari basitleştirme (aynı gün, kullanıcı kararı):** İlk sürüm kalem
metnine bakıp LLM (Ollama/glm-5.2:cloud) ile "hangi NACE'ye ait" tespiti
yapıyordu. Kullanıcı bunu KALDIRDI: **artık kalem içeriği hiç okunmuyor,
LLM yok.** Yeni mantık: satıcının TÜM NACE kod(lar)ının izin verdiği oranlar
tek bir **havuzda** birleştirilir; kalemin oranı bu havuzdaysa `uygun`,
değilse `insan_incelemesi_gerekli`. `kalem_nace_esle()`, `_llm_nace_sec()`,
`NaceCozumTipiTablosu`, `EslemeGuveni` tamamen kaldırıldı.
`satir_bazli_kontrol_et(fatura, satici_nace, oran_tablosu)` artık sadece
`nace_kdv (1).xlsx`/`NaceOranTablosu`'nu kullanıyor,
`kdv_oran_referans2.xlsx`'e bu akışta ihtiyaç kalmadı. Satır bazında KDV
kırılımı yoksa fatura genelindeki tek bir orana düşülür, birden fazla farklı
oran karışıksa insan incelemesine düşer (bu kısım değişmedi). Detay:
PROJECT.md §0.2 alt-adım 3, `docs/explanation/akis-sirasi-ve-faz-plani.md`.

**İstisna farkındalığı + GENEL istisna doğrulaması eklendi (2026-07-20):**
Oran uyuşmazlığı tespit edildiğinde artık iki farklı davranış var:
(1) NACE'den bağımsız, işlem-türüne bağlı **GENEL istisna kodları**
(`GENEL_ISTISNA_KODLARI`) tespit edilirse karar `uygun` oluyor
(`_genel_istisna_dogrulamasi()`); (2) diğer istisna kodları (NACE'ye özgü
13/ı, 13/c gibi, ya da dolgu kodlar) hâlâ sadece bilgi notu ekliyor
(`_fatura_istisna_notu()`), karar `insan_incelemesi_gerekli` kalıyor.

**Kapsam genişletildi (aynı gün):** Kullanıcı repoya GİB'in resmi
`Istisna_Kodlari_GIB.xlsx` kılavuzunu (V1.42, Mart 2026) ekledi —
`GENEL_ISTISNA_KODLARI` artık bu kaynağın 7 kategorisinin TAMAMINDAN
(Kısmi/Tam İstisna, İhraç Kayıtlı Satışlar, Özel Matrah, ÖTV İstisna,
Konaklama Vergisi İstisna, Diğer İşlem Türü) türetilen **107 kod**
içeriyor — önceki liste sadece 4 kodluk (301/302/311/701) bir alt kümeydi.
"Gerçek istisna olmayan" dolgu kodlar (`151`, `250`, `350`, `351` —
"İstisna Olmayan Diğer"/"Diğerleri") bilinçli olarak hariç tutuldu. Detay:
`docs/reference/istisna-kodlari-gib-yapisi.md`. Gerçek bir ihracat
faturasıyla (`AKK2025000000071`, kod 301 → uygun), bir regresyon
faturasıyla (kod 351 → hâlâ insan incelemesi gerekli) ve sentetik
faturalarla (kod 701, kod 235 → uygun) test edildi.

**Sıradaki adım:** Faz 2 (mevzuat MCP + tevkifat + istisna), bkz. PROJECT.md
§3.6, §3.7.

> ✅ **Uygulandı (2026-07-22):** Adım-adım INFO seviyesi loglama eklendi
> (`src/efatura_kdv/api.py::_tek_fatura_kontrol_et` — `[MCP 1/3]`/
> `[MCP 2/3]`/`[MCP 3/3]` etiketli satırlar: XML ayrıştırma sonucu, NACE
> kontrolü başlangıcı, her kalemin kararı, nihai sonuç). Ayrıca
> `logging.basicConfig()` eklendi — önceden root logger'da hiç handler
> yoktu, bu yüzden `kalem_nace_esleme.py`'nin kendi INFO logları (KALEM #N
> satırları) da dahil hiçbir `_logger.info(...)` çağrısı hiçbir yere
> yazdırılmıyordu (sessizce yutuluyordu). `entegrasyon/` ile uçtan uca
> testte "loglar yetersiz, her adımı terminalde göremiyorum" geri
> bildirimi üzerine eklendi. Kullanım: `proje-calistirma.md` "Her adımı
> canlı terminalde izlemek" bölümü.

> ⚠️ Bu bölüm en hızlı bayatlayan bölümdür. Kodla çelişen bir cümle görürsen
> düzelt, ayrı onay bekleme.

## Mimari (özet)

### Faz 1 (şimdiki hedef)

```
[UBL-TR E-Fatura] → [NACE kodu + beyan edilen KDV oranı]
        ↓
[Bu proje: NACE→Oran Excel Kural Kontrolü — LLM/MCP yok, deterministik]
        ↓
   Karar: uygun (→ Hesap Planı Eşleme modülüne aktar) / insan incelemesi gerekli
```

- **Hesap Planı Eşleme Modülü (dış sistem, DOKUNULMAZ):** Geçmiş faturalarla
  vektör benzerliği kurarak doğru Tek Düzen Hesap Planı kodunu bulur. Bu
  proje ona girdi vermez — tam tersine, **bu projenin `uygun` kararı onu
  tetikler** (akış sırası 2026-07-17'de tersine çevrildi, bkz. PROJECT.md
  §0.1). Fatura önce burada doğrulanır, doğruysa TDHP eşlemesine gider.
- **NACE+KDV Excel Referans Tabloları (yüklü):** `nace_kdv (1).xlsx` +
  `nace_kod_degisikligi_2026_03_24.xlsx`. Her NACE (FAALIYETKODU) için hangi
  KDV oranlarının (%0/%1/%10/%20/istisna) geçerli olduğunu satır satır
  listeler. `2026_KOD_DEGISIKLIKLERI` sayfası Faz 1'in TEK kaynağıdır (fatura
  tarihinden bağımsız — kullanıcı kararı, 2026-07-17). Şema detayı:
  `docs/reference/nace-kdv-excel-yapisi.md`.
- **Kontrol mantığı:** Beyan edilen oran, NACE'nin excel'de izin verilen
  oranlarından biriyse `uygun`; değilse veya NACE excelde bulunamazsa
  `insan incelemesi gerekli` (Faz 1'de kesin `uyumsuz` üretilmez — bkz.
  PROJECT.md §0.1 adım 4-5 gerekçesi).

### Faz 2 (sonraki hedef — mevzuat MCP entegrasyonu)

```
[Faz 1 çıktısı] → [Sıralı Agent Workflow] ⇄ [Mevzuat MCP Aracı — tarih bazlı sorgu]
        ↓
   Karar: uygun / uyumsuz / insan incelemesi gerekli (tevkifat + istisna dahil)
```

- **KDV Referans Tablosu (yüklü, henüz koda entegre değil):** `kdv_oran_referans2.xlsx`
  — I/II sayılı liste oranları, tevkifat kodları (601-6xx), NACE_KDV/
  NACE_ISTISNA sayfaları. Statik taban; güncel mevzuat MCP'den gelenle
  çelişirse MCP kazanır (tarih bazlı, güncel). Şema:
  `docs/reference/nace-kdv-excel-yapisi.md`.
- **Sıralı Agent Workflow:** NACE tabanlı beklenti kurma → (çok-oranlıysa)
  kalem metnini NACE'nin kapalı alt-kategori kümesinden birine LLM ile atama /
  eksik veri kontrolü → MCP'den fatura tarihine göre oran/tevkifat/istisna
  kuralı çekme → karşılaştırma → karar üretimi. (Bkz. PROJECT.md §3.7.)
- **Mevzuat MCP Aracı:** İki katmana ayrılır (bkz. PROJECT.md §3.6):
  (1) offline **Mevzuat İzleme & Etiketleme Pipeline** — mevzuat.gov.tr/GİB'i
  izler, kuralları tarih aralıklı olarak **Mevzuat Kural Deposu**na yazar;
  (2) sorgu-anı **MCP aracı** — bu depoyu tarih+kapsam filtresiyle sorgular,
  yapılandırılmış sonuç (oran/kod/kaynak) döner. Model ham mevzuat metnini o
  an yorumlayıp oran üretmez.

## Kritik gerçekler (mevzuat + sistem tasarımına dayalı — varsayım yapma)

- **Geçmiş fatura verisi etiketsizdir, bu yüzden kategori sınıflandırmasında
  KULLANILMAZ:** Geçmiş faturalarda SADECE kalem metni + o günkü KDV oranı
  var; kategori/sınıflandırma etiketi YOK. Bu yüzden kategori taksonomisi
  geçmiş faturalardan değil **NACE + Kategori Excel referans tablosundan**
  gelir. Bağımsız bir "geçmiş faturalarla vektör benzerliği kurup kategori
  bul" adımı YOKTUR — bu, 2026-07-17'de kullanıcıyla netleştirildi (kullanıcı
  ilk tasarımdaki bu hatayı düzeltti, bkz. PROJECT.md §3.7).
- **Bazı NACE kodları tek oranla çözülemez** ("KALEM_GEREKLI" işaretli —
  ör. tarım kodları %1/%20, gayrimenkul 681100: %1/%10/%20). Bu kodlarda kalem
  metni, NACE'ye özel kapalı bir alt-kategori seçenek kümesinden LLM ile
  sınıflandırılır; ek veri (gayrimenkulde net alan, ruhsat tarihi, 6306
  kapsamı gibi) faturada yoksa "insan incelemesi gerekli" ile erken çıkılır.
- **Tevkifat çok değişkenlidir:** Sadece hizmet tipine değil ALICININ kim
  olduğuna (belirlenmiş alıcı listesi) ve tutar alt sınırına (2026: KDV dahil
  12.000 TL) bağlıdır. Hizmet tipine bakıp alıcıyı/tutarı atlamak yanlış karar
  üretir.
- **Kalem açıklamaları muğlaktır:** Genelde serbest metin (ör. "E-Şirket") ve
  tek başına yeterli değildir; satıcı kimliği/NACE'i ile birlikte
  değerlendirilmelidir.
- **Fatura XML'i NACE kodu TAŞIMAZ.** 1828 gerçek faturanın tamamı incelendi
  (2026-07-17) — NACE hiçbir bloğunda (satıcı, alıcı, kalem) geçmiyor. NACE,
  satıcının VKN'sine bağlı ayrı bir kaynaktan (kullanıcı ayrıca ekleyecek)
  gelecek. "Faturadan NACE'yi parse et" gibi bir adım YOKTUR — bkz.
  `docs/reference/ubl-fatura-yapisi.md`, PROJECT.md §0.2.
- **`cac:TaxTotal` KDV dışı vergi türleri de taşıyabilir.** Gerçek örnek:
  Turkcell faturasında aynı vergi bloğunda KDV (%20, kod 0015) yanında Özel
  İletişim Vergisi (%10, kod 4081) ve Telsiz Kullanım Taksiti (%0, kod 8006)
  var. `TaxTypeCode == 0015` kontrolü olmadan bunları KDV zannetmek yanlış
  oran okumasına yol açar — bkz. `docs/reference/ubl-fatura-yapisi.md`.

## Değişmez kurallar

1. **Kategori ile oran ayrıdır — oran her zaman mevzuat MCP'den, fatura
   tarihine göre gelir; NACE/Excel taksonomisi ve LLM asla oran üretmez/
   ezberden söylemez.**
   > KDV oranları ve tevkifat kodları sık ve yürürlük-tarihli değişir; NACE
   > tablosundan veya modelden "hatırlanan" bir oranı kullanmak, yürürlükten
   > kalkmış bir oranın sessizce uygulanmasına yol açar — bu doğrudan
   > mevzuata aykırı bir muhasebe kaydı demektir.
   >
   > **Faz 1 istisnası:** Mevzuat MCP'si henüz yok (bkz. PROJECT.md §0.1).
   > Faz 1'de excel tablosu geçici referans olarak kullanılıyor ama bu bir
   > "oran üretme" değil, "beyan edilen oran listede mi" eşleşme kontrolü —
   > LLM hiçbir noktada oran uydurmuyor. Bu kural, Faz 2'de MCP devreye
   > girdiğinde tam anlamıyla uygulanacak.
2. **Son söz kalemindir, NACE'nin değil.** NACE sadece beklenti üretir ve
   hızlı yol (yüksek güvenli, tipik %20 durumları) için çapraz kontroldür;
   kalem içeriği NACE ile çelişirse kalem önceliklidir.
   > NACE şirketin ana faaliyet kodudur, faturadaki somut işlemi garanti etmez
   > (bir şirket ana faaliyeti dışında satış/hizmet faturalayabilir).
3. **Belirsizlik dürüstçe belirsizdir — zorla tahmin edilmez.** Karar için
   gereken bilgi faturada yoksa (ör. gayrimenkul NACE 681100'de net alan/ruhsat
   tarihi/6306 kapsamı) sistem "insan incelemesi gerekli" döner, tahmin
   üretmez.
   > Sistem otonom çalışır; insan onayı olmadan üretilen hatalı bir otomatik
   > karar doğrudan canlı muhasebe kaydına düşer — geri alınması vergi/muhasebe
   > süreçlerinde maliyetlidir.

## Proje kapsamı ve çalışma düzeni

- **Ne inşa ediyoruz** (kapsam, mimari kararlar, riskler, faz planı): [`project.md`](project.md)
- **Her commit'e tek satır:** [`docs/CHANGELOG.md`](docs/CHANGELOG.md)

## Çalışma tarzı

- **Türkçe yaz:** commit mesajı, dokümantasyon, kod içi yorum, agent/skill
  promptları — hepsi Türkçe.
- **İş kuralı tek yerde yaşar:** Oran/tevkifat/istisna karar mantığı yalnızca
  mevzuat MCP aracı + doğrulama workflow'unda yaşar. Bunu Excel/statik tabloya
  sızdırma — NACE/Excel taksonomisi SADECE kategori/beklenti üretir, oran asla.
- **Dokunmadan önce oku, dokunma:** Hesap Planı Eşleme modülüne (bu repo
  dışında, "BUNA DOKUNMUYORUZ") değişiklik önerme; sadece onun ürettiği çıktıyı
  (kalem metni, NACE, tutar, tarih, alıcı, hesap planı kodu) girdi olarak kullan.
- **Mevzuat detaylarında ezbere yazma:** Oran, tevkifat kodu, yürürlük tarihi
  gibi güncel mevzuat detaylarında emin değilsen web araması/MCP ile teyit et.
  "Muhtemelen şudur" diye kod veya doküman yazma.
- **Canlı sisteme dokunma:** Gerçek mevzuat.gov.tr/GİB MCP'sine veya gerçek
  muhasebe kaydına yazma/deneme yapma; geliştirme ve test için mock/fixture
  kullan.
- **Kritik bir değişiklik yaptıktan sonra ilgili `docs/` dosyasını güncelle —
  aynı görevin parçası, ayrı bir adım değil.** "Kritik" = davranışı, güvenlik
  sınırını, ortam değişkenini veya mimari akışı değiştiren her şey. Hangi
  belge güncellenir Diátaxis türüne göre değişir (bkz. aşağı). Güncellenen
  bölüme `> ✅ Uygulandı (TARİH): ...` notu ekle.

## Dökümantasyon (Diátaxis)

- 🎓 `docs/tutorials/` — öğrenme odaklı, adım adım (yeni katılan biri için)
- 🔧 `docs/how-to/` — görev odaklı tarifler (çalıştırma, deploy, yeni X ekleme)
- 📖 `docs/reference/` — kesin teknik başvuru (MCP aracı şeması, KDV/tevkifat
  tabloları, env değişkenleri)
- 💡 `docs/explanation/` — tasarım/arka plan (neden böyle, alternatifler nelerdi)
- 📜 `docs/CHANGELOG.md` — **her commit'e tek satır** (zorunlu)

Navigasyon: [`docs/README.md`](docs/README.md).
