# E-Fatura KDV/Vergi Oran Doğrulama Sistemi — Mevzuat Uyum Katmanı

> **Amaç:** Gelen UBL-TR e-faturaları, kesen tarafın gözünden kaçmış KDV oranı /
> tevkifat / istisna hatalarına karşı otonom olarak denetleyen bir doğrulama
> katmanı. Sıralı agent workflow + tarih bazlı mevzuat MCP aracı ile çalışır;
> var olan Tek Düzen Hesap Planı eşleme sistemine ek olarak devreye girer,
> onu değiştirmez.

Bu belge projenin teknik kapsamını, mimari kararlarını, gerçek altyapı
değerlerini ve faz planını içerir. Günlük çalışma kuralları için ayrıca
[`CLAUDE.md`](CLAUDE.md).

---

## 0. Hızlı Bağlam (TL;DR)

- **Ne:** Var olan e-fatura → Tek Düzen Hesap Planı (TDHP) aktarım sisteminin
  **önüne** eklenen bağımsız bir doğrulama katmanı (bkz. §0.1 — akış sırası
  2026-07-17'de değişti). Girdi: UBL-TR e-fatura (NACE kodu + beyan edilen
  KDV oranı + kalem metni). Çıktı: `uygun / uyumsuz / insan incelemesi
  gerekli`. `uygun` dönerse fatura TDHP eşleme modülüne aktarılır; değilse
  TDHP eşlemesine hiç gitmez.
- **Ölçek (bugün):** Henüz üretimde değil — tasarım fazı. Hedef: **yüksek
  hacim, latency/maliyet kritik** (kullanıcı onayı, 2026-07-17) — bu yüzden
  MCP tasarımı canlı sorgu yerine önceden etiketlenmiş bir depo üzerinden
  çalışacak şekilde kuruluyor (bkz. §3.6, ama bu **Faz 2**, bkz. §0.1).
- **Durum:** Mimari netleştirme aşaması. Referans Excel dosyaları repoya
  yüklendi: `nace_kdv (1).xlsx` (NACE faaliyet kodu → geçerli KDV oranları:
  %0/%1/%10/%20/istisna, çok sayfalı: 2025 kesim/bölüm/grup/sınıf kırılımı,
  2024 oranları, 2024→2025 dönüşüm kodları, istisna listesi) ve
  `nace_kod_degisikligi_2026_03_24.xlsx` (NACE kod birleşme/değişiklik
  eşlemesi + yeni kodun oranı). İkisi de "NACE kodu → izin verilen oran(lar)"
  sorgusu için kaynak.
- **Kritik kural:** Oran her zaman MCP'den (tarih bazlı, Faz 2'den itibaren)
  gelir, kategori NACE+Excel taksonomisinden gelir — ikisi asla karışmaz;
  belirsizlik varsa insana yönlendirilir, tahmin edilmez.

### 0.1 Akış sırası ve faz planı değişikliği (2026-07-17)

İlk tasarımda doğrulama katmanı TDHP eşlemesinden **sonra** çalışan, onun
çıktısını tüketen bir katman olarak tasarlanmıştı. Kullanıcı bunu düzeltti:
doğrulama **önce** çalışmalı — fatura önce KDV oranı açısından kontrol edilir,
oran doğruysa TDHP koduna aktarılır, değilse orada durulur ve uyarılır. TDHP
eşleme modülü artık "girdi kaynağı" değil, doğrulamadan geçmiş faturaların
gittiği bir **sonraki adım**.

Ayrıca kapsam iki faza bölündü:

- **Faz 1 (şimdi):** Sadece NACE+Excel referans tablosu kullanılarak kural
  tabanlı kontrol. Mevzuat MCP'si, Kural Deposu, izleme/etiketleme pipeline'ı
  (§3.6) bu fazda **yok** — hepsi Faz 2'ye ertelendi.
- **Faz 2 (sonra):** §3.6'daki mevzuat MCP mimarisi (offline etiketleme +
  sorgu-anı kural deposu) entegre edilir, tarih bazlı güncel oran/tevkifat/
  istisna kontrolü eklenir.

**Faz 1 kontrol mantığı (kesinleşti, 2026-07-17):**
1. Faturadan NACE kodu (FAALIYETKODU) + beyan edilen KDV oranı okunur.
2. `nace_kdv (1).xlsx`'te o NACE kodu aranır → o satırda dolu olan
   KDV%0/%1/%10/%20/İSTİSNA sütunları "bu NACE'nin kesebileceği oranlar"
   listesini oluşturur (bazı kodlarda birden fazla sütun doludur, ör. tarım
   kodlarında hem %1 hem %20 — bu proje içinde "çok oranlı NACE" denen durum
   budur).
3. Beyan edilen oran bu listede **varsa** → `uygun`. Çok oranlı bir NACE'de
   hangi alt-kategoriye (ör. gayrimenkulde 681100'ün %1/%10/%20 seçeneklerinden
   hangisi) ait olduğu Faz 1'de **doğrulanmaz** — oran listede olduğu sürece
   yeterli kabul edilir (kullanıcı onayı, 2026-07-17). Alt-kategori
   doğrulaması (LLM ile kalem metni sınıflandırma, bkz. eski §3.7 taslağı)
   Faz 1 kapsamında **değildir**.
4. Beyan edilen oran listede **yoksa** → `insan incelemesi gerekli` (kesin
   `uyumsuz` denmez — Faz 1'de kalem metni analizi olmadığı için temkinli
   davranılır, golden rule 3 ile tutarlı).
5. NACE kodu excel referansında hiç bulunamazsa (kapsam dışı kod, ya da kod
   `nace_kod_degisikligi_2026_03_24.xlsx`'teki bir değişiklik/birleşme
   sonrası farklı bir koda taşınmışsa) → yine `insan incelemesi gerekli`.

**Gerekçe:** Kullanıcı bunu 2026-07-17'de açıkça belirtti — "biz oran
üretmeyeceğiz, sadece elimize gelecek faturaların içindeki oranların excel'deki
NACE-oran eşleşmesiyle karşılaştırılması" ilk faz için yeterli ve mevzuat MCP'si
gibi ağır bir altyapı olmadan da değer üretir. Bu, golden rule 3'ü (belirsizlik
tahmin edilmez) daha da sıkı uygular: Faz 1'de kalem/tevkifat/istisna nüansı
yok, bu yüzden "oran listede yok" ile "NACE hiç yok" durumlarının ikisi de
`uyumsuz` değil `insan incelemesi gerekli` döner.

> ✅ Onaylandı (2026-07-17): Kullanıcı akış sırası tersine çevirme kararını,
> Faz 1/Faz 2 ayrımını ve yukarıdaki 5 adımlı kontrol mantığını onayladı.

### 0.2 Faz 1'in alt-adımları: fatura parse etme → NACE-oran kural kontrolü → çoklu-NACE seçimi (2026-07-17)

Faz 1'in kendisi sıralı alt-adımlara bölündü (kullanıcı isteği, 2026-07-17).
§0.1'deki 5 adımlı kontrol mantığı bu alt-adımların birleşiminden oluşuyor.

**Alt-adım 1 (tamamlandı): UBL-TR fatura parser'ı.**
`ubls/` klasöründeki 1828 gerçek fatura XML'i (`*-inbox.xml`/`*-outbox.xml`)
incelenerek `src/efatura_kdv/ubl_parser.py` yazıldı — `parse_ubl_invoice()`
fonksiyonu satıcı/alıcı (VKN/TCKN/unvan), fatura tipi, kalemler (ad, tutar,
miktar) ve her kalemin/faturanın vergi kırılımlarını (KDV oranı, tevkifat
kodu/oranı, istisna kodu/açıklaması) çıkarır. Şema detayları ve gerçek
fatura örneklerinden çıkan kritik bulgular (NACE'nin XML'de hiç olmaması,
`cac:TaxTotal`'ın KDV-dışı vergi türleri de taşıyabilmesi, istisna kodunun
bazen sadece genel toplamda olması, bazı faturalarda satır seviyesinde hiç
vergi kırılımı olmaması) `docs/reference/ubl-fatura-yapisi.md`'de belgelendi.
1828 faturanın tamamı üzerinde hatasız çalıştığı doğrulandı.

**Kritik gerçek — NACE kodu XML'de yok:** Fatura kendisi NACE kodu taşımıyor.
NACE, satıcının VKN'sine bağlı **ayrı bir kaynaktan** gelecek. Parser bu
yüzden NACE alanı döndürmez/beklemez — NACE eşlemesi ayrı bir adımda
(alt-adım 3) yapılacak.

**Alt-adım 2 (tamamlandı, sonradan basitleştirildi): NACE→oran kural kontrol
modülü.** `nace_kdv (1).xlsx`'e kullanıcı tarafından 2026 itibarıyla geçerli
tam NACE-KDV tablosu eklendi (`2026_KOD_DEGISIKLIKLERI` sayfası, 2138 satır
— 15 gerçek kod değişikliği/birleşme/bölünme + değişmeyen 2120 kod; detay:
`docs/reference/nace-kdv-excel-yapisi.md`). Bu veriye dayanarak
`src/efatura_kdv/nace_kural_kontrolu.py` yazıldı: `NaceOranTablosu` bu tek
sayfayı yükler, `kontrol_et(nace_kodu, beyan_edilen_oran, tablo)` §0.1'deki
5 adımlı mantığı uygular ve `KontrolSonucu` (karar + gerekçe) döner.
**Girdi arayüzü bilinçli olarak bağımsızdır** — doğrudan `(nace_kodu, oran)`
alır, `Fatura`/`FaturaKalemi` nesnesine bağımlı değildir; çünkü NACE henüz
kalemlere bağlanmadı (alt-adım 3 bekliyor).

> ✅ Güncellendi (2026-07-17): İlk sürüm fatura tarihine göre eski
> (`2025_KESIM_BOLUM_GRUP_SINIF`) / yeni (`2026_KOD_DEGISIKLIKLERI`) sayfa
> arasında seçim yapıyordu. Kullanıcı bu tarih ayrımından vazgeçti — modül
> artık fatura tarihinden bağımsız, HER ZAMAN `2026_KOD_DEGISIKLIKLERI`
> (en güncel NACE-KDV tablosu) sayfasını kullanıyor. `kontrol_et()` artık
> `fatura_tarihi` parametresi almıyor. 6 senaryoda (tek/çok oranlı NACE,
> artık geçersiz olan eski kod, geçerli yeni kod, bulunamayan kod) yeniden
> doğrulandı.

**Alt-adım 3 (tamamlandı, 2026-07-20): çoklu-NACE'li şirketlerde satır
bazında NACE seçimi.** Bir şirketin (VKN) birden fazla NACE kodu olabilir
(ana faaliyet + tali faaliyetler). Gelen faturanın **hangi kalemi hangi NACE
kodu altına girdiğini** belirleyen mantık — kullanıcı bunu satır (kalem)
bazında yapılacak şekilde netleştirdi (2026-07-17): aynı faturadaki farklı
kalemler farklı NACE'lere düşebilir, fatura başına tek bir NACE varsayılmaz.

> ✅ Uygulandı (2026-07-20): `src/efatura_kdv/kalem_nace_esleme.py` yazıldı.
> **Kritik kapsam kararı (2026-07-20):** VKN→NACE excel lookup dosyası
> YAZILMADI — kullanıcı netleştirdi ki gelen faturayla birlikte **satıcının
> NACE kod(ları) da dışarıdan (üst sistemden) gelir**; sistem sadece fatura
> sahibinin (satıcının) kestiği faturalarda çalışabilir. Bu bilgi
> `SaticiNaceBilgisi(vkn, nace_kodlari)` dataclass'ı olarak fonksiyonlara
> parametre geçilir.
>
> **⚠️ Mimari basitleştirme (2026-07-20, aynı gün, kullanıcı kararı):** İlk
> sürümde kalem METNİNE bakarak "bu kalem hangi NACE'ye ait" tespiti
> yapılıyordu (sayısal eleme + LLM ile kapalı-küme seçim, Ollama/glm-5.2:cloud
> üzerinden). Kullanıcı bunu KALDIRDI: *"kalem içeriğine bakmayalım sadece
> kalemin kdv oranına bakalım, nace kodlarındaki yetkilerine bakalım"*.
>
> **Yeni (ve şu anki) mantık — kalem içeriği ASLA okunmaz, LLM YOK:**
> Satıcının TÜM NACE kod(lar)ının izin verdiği oranlar tek bir **"izin
> verilen oranlar havuzu"**nda birleştirilir (`_izin_verilen_oranlar_havuzu()`
> — ör. NACE-A sadece `%20`, NACE-B `%1/%10/%20` destekliyorsa havuz =
> `{1, 10, 20}` olur). Kalemin beyan edilen oranı bu havuzda varsa `uygun`,
> yoksa `insan_incelemesi_gerekli` — hangi kalemin hangi NACE'ye ait olduğu
> hiç aranmaz, sorulmaz. Eski `kalem_nace_esle()`, `_llm_nace_sec()`,
> `NaceCozumTipiTablosu`, `EslemeGuveni`, `KalemNaceEslemesi` tamamen
> kaldırıldı — `test/llm_gerekce_tanisi.py` de silindi.
>
> **Satır bazında KDV kırılımı olmayan kalemler** (ör. TEMELFATURA/telekom,
> gerçek örneklerde yaygın): faturanın genel toplamındaki BENZERSİZ oran
> sayısına bakılır — tam **1** farklı oran varsa tüm kalemler o oranla
> beyan edilmiş gibi işlenir (kullanıcı kararı, 2026-07-20); **0** veya
> **2+** farklı oran varsa `insan incelemesi gerekli` (tahmin edilmez). Bu
> kısım DEĞİŞMEDİ.
>
> Fonksiyon: `satir_bazli_kontrol_et(fatura, satici_nace, oran_tablosu) ->
> FaturaSatirBazliSonuc` — artık `cozum_tipi_tablosu` parametresi YOK (LLM
> kalktığı için `kdv_oran_referans2.xlsx`/`NACE_KDV` sayfasına ihtiyaç
> kalmadı, sadece `nace_kdv (1).xlsx`/`NaceOranTablosu` kullanılıyor). Her
> kalem için `SatirKontrolSonucu` üretir (artık `eslesme` alanı yok, bunun
> yerine `nace_kodlari_kontrol_edildi` + `izin_verilen_oranlar_havuzu`),
> `genel_karar` property'si en temkinli satırı fatura genel kararına
> yansıtır. `nace_kural_kontrolu.kontrol_et()` bu akışta artık DOĞRUDAN
> çağrılmıyor — `NaceOranTablosu.izin_verilen_oranlar()` doğrudan
> kullanılıyor (aynı excel/tablo, farklı kullanım şekli).
>
> 6 senaryoda gerçek `ubls/` faturalarıyla (ve bir sentetik "karışık genel
> toplam" örneğiyle) test edildi: tek-NACE-havuzda, tek-NACE-havuzda-değil,
> çoklu-NACE-havuz-birleşip-buluyor, çoklu-NACE-havuz-birleşse-de-bulamıyor,
> genel-toplam-tek-oran, genel-toplam-karışık-oran. Hepsi beklenen kararı
> üretti; LLM'e hiç gidilmediği için testler anlık tamamlandı (önceki
> sürümde bazı LLM çağrıları 10-70 saniye sürüyordu).
>
> ✅ Uygulandı (2026-07-20, aynı gün): **Gerekçeye NACE atıfı eklendi.**
> Kullanıcı gerekçe metninde TAM OLARAK hangi NACE kodu sayesinde `uygun`
> kararı verildiğini görmek istedi — önceki gerekçe sadece birleşik havuzu
> gösteriyordu (ör. "havuzda [1,10,20]"), hangi NACE'nin bu oranı
> desteklediği belirtilmiyordu. `_izin_verilen_oranlar_havuzu()` artık her
> NACE'nin kendi oranlarını da ayrıca (`{nace_kodu: oranlar}`) döndürüyor;
> yeni `_nace_gerekce_metni()` beyan edilen her oran için "%20 -> NACE
> ['532009']" formatında hangi NACE(ler)in bu oranı meşru kıldığını
> listeliyor. Birden fazla NACE aynı oranı destekliyorsa hepsi gösterilir
> (kalem içeriği incelenmediği için "hangisi doğru" iddia edilmez, sadece
> hangi NACE'lerin bu oranı desteklediği dürüstçe belirtilir). Gerçek
> çoklu-NACE senaryolarıyla test edildi.

> ✅ Uygulandı (2026-07-20, iki aşamalı): **İstisna farkındalığı ve GENEL
> istisna doğrulaması eklendi.**
>
> **Aşama 1:** Manuel test sırasında gerçek bir ihracat faturasında
> (`AKK2025000000071`, istisna kodu `301` = "11/1-a Mal İhracatı") sistemin
> %0 oranını NACE'nin izin verdiği listeyle (`%20`) uyuşmuyor diye
> `insan_incelemesi_gerekli`ye düşürdüğü, ama gerekçede istisnaya dair
> hiçbir ipucu vermediği görüldü. `_fatura_istisna_notu()` eklendi — oran
> uyuşmazlığında istisna kodu varsa gerekçeye bilgi notu ekleniyor.
>
> **Aşama 2 (kullanıcı onayıyla kapsam genişletildi):** Kullanıcı "istisna
> zaten geçerliyse neden hâlâ insan incelemesi gerekiyor" diye sordu.
> Ayrım netleştirildi: **NACE'den bağımsız, işlem-türüne bağlı GENEL istisna
> kodları** (`GENEL_ISTISNA_KODLARI = {"301", "302", "311", "701"}` —
> ihracat, uluslararası taşımacılık, ihraç kayıtlı satış) artık
> `_genel_istisna_dogrulamasi()` ile gerçekten doğrulanıyor ve tespit
> edilirse karar `uygun` oluyor. **Bilinçli olarak HARİÇ tutulanlar:** `350`
> ("Diğerleri") ve `351` ("İstisna Olmayan Diğer") — web araştırmasıyla
> teyit edildi ki bunlar gerçek bir istisna maddesi değil, özel kodu
> olmayan/istisna-dışı %0 durumları için kullanılan genel dolgu kodlar;
> bunları geçerli istisna saymak yanlış "uygun" kararına yol açardı. Bu
> kodlarda hâlâ `_fatura_istisna_notu()`'nun bilgi notu (ama karar
> `insan_incelemesi_gerekli`) devrede. NACE'ye özgü istisnalar (13/ı, 13/c
> gibi, `NACE_ISTISNA` sayfasındaki 119 kod) bu turda BAĞLANMADI — hâlâ Faz
> 2 kapsamında, sadece bilgi notu üretiyorlar.
>
> Gerçek fatura ile test edildi: `301` istisnalı ihracat faturası artık
> `uygun` dönüyor (gerekçede istisna kodu + açıklaması belirtiliyor); `351`
> kodlu (gerçek istisna olmayan) bir Turkcell faturası regresyon testinde
> hâlâ doğru şekilde `insan_incelemesi_gerekli` kalıyor.

> ✅ Uygulandı (2026-07-20, aynı gün, kapsam büyük ölçüde genişletildi):
> **`GENEL_ISTISNA_KODLARI` GİB'in resmi kod listesinden 107 koda çıkarıldı.**
> Kullanıcı repoya `Istisna_Kodlari_GIB.xlsx` dosyasını ekledi (GİB e-Belge
> Uygulamaları - UBL-TR Kod Listeleri Kılavuzu, V1.42, Mart 2026 — 7 kategori:
> Kısmi İstisna 201-250, Tam İstisna 301-351, İhraç Kayıtlı Satışlar 701-704,
> Özel Matrah 801-812, ÖTV İstisna 101-151, Konaklama Vergisi İstisna 001,
> Diğer İşlem Türü 555). Önceki liste (`301`, `302`, `311`, `701`) web
> araştırmasıyla teyit edilmiş ama sadece 4 kodluk eksik bir alt kümeydi.
>
> Bu resmi kaynak, `701`'in de gerçekten geçerli olduğunu doğruladı (kendi
> kategorisinde: "İhraç Kayıtlı Satışlar", 701-704) — önceki web
> araştırmasında bu kod hiçbir GİB kategorisinde bulunamamıştı, şüpheliydi.
>
> Liste programatik olarak (openpyxl ile) okunup, sadece açıklama metninde
> "İstisna Olmayan" veya salt "Diğerleri" geçen 4 dolgu kod (`151`, `250`,
> `350`, `351`) hariç tutularak **107 kod**a genişletildi ve statik bir
> Python `set` olarak koda gömüldü. Detay şema:
> `docs/reference/istisna-kodlari-gib-yapisi.md`. Gerçek ve sentetik
> senaryolarla test edildi: `301` (ihracat, gerçek fatura) → uygun, `351`
> (dolgu kod, regresyon) → hâlâ insan_incelemesi_gerekli, `701` (ihraç
> kayıtlı satış, sentetik) → uygun, `235` (transit/gümrük antrepo, önceki
> listede yoktu, sentetik) → artık uygun.

---

## 1. Altyapı (Gerçek Değerler)

Bu proje henüz koda dökülmedi (bkz. §0 Durum) — bu bölümdeki tüm altyapı
kararları (barındırma ortamı, süreç modeli, kalıcı veri stratejisi) agent
workflow ve mevzuat MCP aracı tasarımı netleşip prototip test edildikten sonra
doldurulacak. Şu an bilinen tek gerçek: sistem, var olan Hesap Planı Eşleme
modülünden **çıktı tüketen** ayrı bir süreç/servis olarak tasarlanıyor, onun
içine gömülmüyor. Ayrıca yüksek hacim/düşük latency hedefi netleşti (§0) —
bu, mevzuat MCP'sinin canlı kaynağa değil, önceden hazırlanmış bir yerel
depoya sorgu atacağı anlamına geliyor (bkz. §3.6).

### Bağımlı sistemler

| Sistem | Adres/Konum | Not |
|---|---|---|
| Hesap Planı Eşleme Modülü | Bu repo dışında | Vektör benzerlik ile Tek Düzen Hesap Planı kodu üretir. **BUNA DOKUNULMUYOR** — bu proje sadece onun çıktısını (kalem metni, NACE, tutar, tarih, alıcı) girdi olarak kullanır. Bu modülün vektör benzerliği KDV kategorisi ÜRETMEZ, muhasebe hesap kodu üretir — ikisi karıştırılmamalı. |
| Mevzuat kaynağı (İzleme Pipeline üzerinden) | mevzuat.gov.tr / GİB | Kullanıcı onayı: sıfırdan inşa edilecek (2026-07-17). Erişim yöntemi (resmi API mi, scraping mi) henüz tasarlanmadı. |

---

## 2. Ağ, Erişim ve Sırlar

Henüz tasarlanmadı — mevzuat kaynağına erişim yöntemi (API mi, scraping mi)
bu konuşmanın ilerleyen adımlarında netleşecek. Netleşince bu bölüm gerçek
env değişkenleriyle doldurulacak; şu an placeholder bırakmak yerine bölüm
bilerek boş tutuluyor.

> **Sırlar:** Mevzuat kaynağına erişim için bir API anahtarı gerekirse koda,
> log'a veya hata çıktısına yazılmayacak; nereye konulacağı MCP tasarımıyla
> birlikte kararlaştırılacak.

---

## 3. Mimari Kararlar (Bu Projeye Özel)

### 3.1 Doğrulama katmanı, hesap planı eşleme sisteminden ayrı tutulur — ve ondan ÖNCE çalışır
Bu sistem var olan vektör-benzerlik tabanlı hesap planı eşleme modülüyle aynı
sürece gömülmez, ayrı bir katman olarak kalır — ama akış sırası §0.1'de
belirtildiği gibi **ondan önce**dir: fatura önce KDV oranı açısından
doğrulanır, `uygun` ise TDHP eşlemesine gider, değilse TDHP eşlemesine hiç
girmez. **Gerekçe:** Çalışan ve doğrulanmış TDHP modülünü riske atmadan yeni,
hataya daha açık bir mevzuat-yorumlama katmanını izole tutmak; ayrıca iki
modülün sorumluluğu netçe ayrışıyor (oran doğrulama vs. hesap kodu bulma).
Sıranın ters çevrilmesinin gerekçesi: yanlış oranlı bir fatura zaten
TDHP'ye hiç girmemeli, sonradan "düzeltilecek" bir kayıt üretilmemeli.

### 3.2 Kategori ve oran kaynakları kesin olarak ayrılır
KDV oranı, tevkifat kodu ve istisna durumu HER ZAMAN mevzuat MCP aracından,
faturanın kendi tarihine göre sorgulanır — kategori taksonomisi (§3.7) hiçbir
zaman oran üretmez. **Gerekçe:** Statik bir tablodan veya bir LLM'in "hatırladığı"
oranı kullanmak, yürürlükten kalkmış bir oranın sessizce uygulanması riskini
taşır. Bu ayrım projenin en kritik güvenlik-benzeri kısıtıdır (bkz.
`CLAUDE.md` Değişmez Kural 1).

> **Faz 1 istisnası (§0.1):** Faz 1'de mevzuat MCP'si henüz yok; NACE+Excel
> tablosu geçici olarak "oran kaynağı" gibi kullanılıyor. Bu, Değişmez Kural
> 1'i ihlal etmez çünkü Faz 1'in ürettiği oran bir **üretim/tahmin** değil,
> sadece "beyan edilen oran, excel'in izin verdiği listede mi" şeklinde bir
> **eşleşme kontrolü** — LLM oran uydurmuyor, statik tablo bir referans
> aralığı olarak kullanılıyor. Faz 2'de bu kontrol, tarih bazlı güncel MCP
> sorgusuyla değiştirilecek/desteklenecek.

### 3.3 NACE çapraz kontroldür, otorite değildir
NACE kodu (ana + tali) beklenen oran/kategori için hem taksonominin kaynağı
hem de bir "hızlı yol"/çelişki kontrolüdür. Kalem içeriği ile NACE beklentisi
çeliştiğinde kalem kazanır. **Gerekçe:** NACE şirketin ana faaliyet alanını
gösterir, faturadaki somut işlemi garanti etmez; NACE'i otorite kabul etmek
sistematik yanlış pozitif/negatiflere yol açar.

### 3.4 Belirsizlik durumunda insana yönlendirme, tahmin değil
Karar için gerekli bilgi (ör. gayrimenkul satışında net alan, ruhsat tarihi,
6306 kapsamı) faturada yoksa sistem "insan incelemesi gerekli" döner.
**Gerekçe:** Sistem otonom çalışıyor ve çıktısı doğrudan muhasebe kaydına
gidebilir; yanlış bir otomatik "uygun" kararı, vergi/ceza riski doğurabilecek
şekilde geri alınması zor bir sonuç üretir. Belirsizliği gizlemek yerine açıkça
işaretlemek daha ucuzdur.

### 3.5 Geliştirme yaklaşımı: skill → hızlı model testi → production kodu
Agent workflow önce bir skill (yeniden kullanılabilir prompt/yönerge dosyası)
olarak yazılıp hızlı bir modelde (ör. Codex üzerinden) test edilecek; sonuçtan
memnun kalınırsa production koduna dökülecek. **Gerekçe:** Mevzuat yorumlama
mantığı gibi doğruluğu kritik ama iterasyon hızı da önemli olan bir bileşende,
önce ucuz/hızlı bir döngüde doğru davranışı netleştirip sonra kalıcı koda
yatırım yapmak, doğrudan koda gömülüp sonradan pahalıya düzeltilecek yanlış
varsayımlardan daha güvenli.

### 3.6 Mevzuat MCP'si iki katmana ayrılır: offline etiketleme + sorgu-anı hızlı erişim
Mevzuat MCP'si tek bir "canlı GİB/mevzuat.gov.tr tarayıcısı" değildir. İki ayrı
bileşene bölünür:
1. **Mevzuat İzleme & Etiketleme Pipeline** (offline, periyodik): mevzuat.gov.tr
   / GİB kaynağını izler, yeni/değişen KDV oranı, tevkifat, istisna kurallarını
   yakalar ve her kuralı yapılandırılmış + tarih aralıklı olarak bir
   **Mevzuat Kural Deposu**na yazar: `{konu, kapsam (NACE/mal-hizmet/tevkifat
   türü), oran veya tevkifat_kodu, yürürlük_başlangıç, yürürlük_bitiş,
   kaynak_referansı}`.
2. **Mevzuat MCP Aracı** (sorgu anında, hızlı): Fatura işlenirken bu depoyu
   tarih + kapsam filtresiyle sorgular. Sonuç her zaman **yapılandırılmış
   alan** olarak döner (oran/kod/kaynak) — LLM ham mevzuat metnini o an
   yorumlayıp oran üretmez, depodaki etiketlenmiş alanı okur. Depoda o
   tarih/kapsam için eşleşen kural yoksa veya çelişen birden fazla kural
   varsa araç bunu açıkça bildirir → "insan incelemesi gerekli".

**Gerekçe:** Sistem yüksek hacimde çalışacak ve latency/maliyet kritik
(bkz. §5 Riskler); her fatura kalemi için canlı GİB taraması yapmak hem yavaş
hem maliyetli olur. Kuralları önceden etiketleyip yapılandırılmış bir depoda
tutmak, sorgu anında hızlı ve deterministik bir arama sağlarken golden rule
#1'i de korur (oran her zaman "kaynak" alandan gelir, modelin serbest
yorumundan değil). Bu karar kullanıcıyla 2026-07-17 tarihli görüşmede
netleştirildi; ekip arkadaşının önerdiği "RAG mantığı" burada mevzuat metnini
yorumlamak için değil, tarih/kapsama göre doğru kuralı *bulmak* için
kullanılıyor.

> ✅ Onaylandı (2026-07-17): Kullanıcı bu iki katmanlı tasarımı onayladı.

### 3.6.1 Etiketleme adımının somut akışı ve veri kaynağı

**Veri kaynağı:** GİB özelgeleri (resmi API varsa onun üzerinden, yoksa
scraping) + mevzuat.gov.tr için HTML scraping. `yargi-mcp` projesinin
`gib_mcp_module`'ü referans alınabilir (özelge arama/getirme deseni benzer;
bkz. `docs/explanation/mevzuat-mcp-mimarisi.md`).

**Kural Deposu teknolojisi:** PostgreSQL kullanılır (karar değişikliği,
2026-07-21 — önceki "SQLite ile başla" kararı yerine geçti). Gerekçe: sistem
çoklu-kullanıcı/eşzamanlı erişim senaryosunda çalışacak (birden fazla süreç
aynı anda depoyu okuyup/yazabilir); SQLite tek-yazar modelinde bu senaryoda
kilitlenme riski taşır, PostgreSQL gerçek eşzamanlı çoklu-bağlantı ve satır
kilitleme desteği sağlar. Yerel geliştirmede Docker ile çalıştırılır (bkz.
`docs/how-to/postgres-kurulum.md`).

> ✅ **Uygulandı (2026-07-21):** Faz 1'in NACE+oran verisi (önceden
> `nace_kdv (1).xlsx`/`NaceOranTablosu`) PostgreSQL'e taşındı — bu, Faz 2'nin
> Mevzuat Kural Deposu kararını erken uygulamaya koyar (aynı teknoloji
> kararı, farklı veri kümesi). Şema: `docs/reference/nace-kdv-excel-yapisi.md`
> §"PostgreSQL Şeması". Kod: `src/efatura_kdv/nace_kural_kontrolu.py`
> (`NaceOranTablosu` artık excel yerine `DATABASE_URL` env var ile
> PostgreSQL'den okuyor). Migrasyon betiği:
> `scripts/excel_to_postgres.py`. Mevzuat Kural Deposu'nun kendisi (tarih
> aralıklı kurallar, tevkifat, istisna) henüz yazılmadı — bu sadece
> teknoloji kararının Faz 1 parçasına erken uygulanmasıdır.
>
> ✅ **Gerçek PostgreSQL ile doğrulandı (2026-07-21, aynı gün ilerleyen
> saatlerde):** Kullanıcı Docker'ı kurdu, container port 5434'te (bu
> makinede zaten iki yerel Postgres kurulumu 5432/5433'ü tuttuğu için)
> ayağa kaldırıldı, migrasyon çalıştırılıp 2138 NACE kodu doğru yazıldı,
> `NaceOranTablosu`/`kontrol_et()` gerçek DB bağlantısıyla doğru sonuç
> üretti. Önceki "mock ile test edildi, gerçek DB yok" notu artık geçersiz.

**Etiketleme akışı (Katman 1 içinde, 3 adım):**
1. Scraper/parser ham mevzuat metnini (madde, tebliğ, özelge) çeker.
2. LLM bu ham metinden yapılandırılmış kural TASLAĞI çıkarır: `{konu, kapsam
   (NACE/mal-hizmet/tevkifat türü), oran veya tevkifat_kodu,
   yürürlük_başlangıç, yürürlük_bitiş, kaynak_referansı}`.
3. Taslak Kural Deposu'na DOĞRUDAN yazılmaz — bir "onay bekleyen kurallar"
   kuyruğuna düşer, insan (analist) onaylayınca depoya yazılır. Onaylanmamış
   taslaklar sorgu-anı MCP aracı tarafından hiçbir zaman okunmaz.

**Gerekçe:** Bu, LLM'in mevzuat yorumlama esnekliğini (ham metinden yapı
çıkarma) insan onayının güvenlik kapısıyla birleştiriyor — böylece Değişmez
Kural 1 (oran asla LLM'in o anki serbest yorumundan gelmez) ihlal edilmeden
etiketleme otomatikleştirilebiliyor. Periyodik cron (günlük/haftalık) ile
tetiklenir; manuel tetikleme ihtiyacı ortaya çıkarsa ayrıca eklenir.

> ✅ Onaylandı (2026-07-17): Kullanıcı bu akışı ve veri kaynağını onayladı.

### 3.7 Kategori sınıflandırma NACE'ye bağlıdır, geçmiş faturalarla bağımsız bir RAG adımı değildir
İlk taslakta "kalem metninden kategori çıkarma" için geçmiş faturalarla
vektör benzerliği kuran bağımsız bir Adım 1 önerilmişti. Bu **yanlıştı** ve
kullanıcı tarafından düzeltildi (2026-07-17): geçmiş faturalarda kategori
etiketi YOK (sadece kalem metni + o günkü oran var, bkz. `CLAUDE.md` Kritik
Gerçekler), dolayısıyla onlarla supervised bir sınıflandırma kurulamaz.

Karar: Kategori sınıflandırması **NACE'ye bağlı, kapalı kümeli bir
çözümlemedir**, bağımsız bir RAG/vektör adımı değildir:
- NACE ana/tali kodu, NACE+Kategori Excel referansında aranır.
- **Tek oranlıysa:** NACE'nin verdiği beklenti doğrudan kullanılır (hızlı
  yol); kalem metni sadece çelişki kontrolü için LLM ile bir kez taranır
  (golden rule 2 — kalem NACE ile çelişirse kalem kazanır).
- **Çok oranlıysa (KALEM_GEREKLI, ör. tarım %1/%20, gayrimenkul 681100
  %1/%10/%20):** Excel'de o NACE'ye özel kapalı bir alt-kategori/seçenek
  listesi bulunur; kalem metni LLM tarafından bu KAPALI kümeden birine
  atanır (zero-shot, açık uçlu değil). Karar için gereken ek veri (ör.
  gayrimenkulde net alan/ruhsat tarihi/6306 kapsamı) faturada yoksa erken
  çıkış: "insan incelemesi gerekli" (golden rule 3).
- Geçmiş fatura verisi (kalem+oran) bu sınıflandırmada **girdi olarak
  kullanılmaz**. En fazla ileride bir backtest/değerlendirme seti olarak
  (sistem çıktısını geçmiş gerçek oranlarla karşılaştırmak için) kullanılabilir
  — bu ayrı bir konudur, sınıflandırmanın kendisi değildir.

**Gerekçe:** Etiketsiz veriyle "öğrenilmiş" bir kategori sinyali kurmaya
çalışmak (embedding benzerliğiyle geçmiş oranlardan kategori tahmin etmek),
tutarsız/gürültülü olur (aynı kalem metni farklı dönemlerde farklı oranlarla
görülmüş olabilir) VE golden rule 1'i incelikle ihlal etme riski taşır (oran
sinyalinin sınıflandırmaya sızması). NACE+Excel taksonomisi kapalı, kontrol
edilebilir ve kaynağı bilinen bir küme olduğu için bu riski taşımaz.

> ✅ Onaylandı (2026-07-17): Kullanıcı bu düzeltmeyi onayladı — ama bu akış
> (LLM ile çok-oranlı NACE'lerde kalem sınıflandırma) **Faz 2** kapsamındadır
> (bkz. §0.1). Faz 1'de kalem metni sınıflandırması yapılmaz, sadece "beyan
> edilen oran, NACE'nin excel'de izin verilen oranlarından biri mi" kontrol
> edilir.

### 3.8 Faz 1 doğrulama katmanı bir HTTP API'si arkasında, çok kullanıcılı erişime açık

Sistem başlangıçta sadece Python import ile (tek süreç, tek kullanıcı — test
script'leri ve `test/web_arayuz.py`) kullanılabiliyordu. Kullanıcı isteğiyle
(2026-07-21) bu, çok-kullanıcı/eşzamanlı erişime uygun bir HTTP API'sine
taşındı — aynı gerekçe zincirinin devamı (§3.6.1'deki PostgreSQL kararıyla
birlikte): birden fazla kullanıcı/süreç aynı anda bağımsız fatura kontrolü
isteği gönderebilmeli.

**Mimari:**
- FastAPI (`src/efatura_kdv/api.py`), tek endpoint: `POST /fatura/kontrol-et`
  (ham UBL-TR XML + satıcı VKN + satıcı NACE kodları → kalem bazlı karar).
- `NaceOranTablosu` uygulama **başlarken bir kez** PostgreSQL'den yüklenir ve
  tüm istekler arasında bellek-içi paylaşılır (`lifespan` context) — her
  istek kendi DB bağlantısını açmaz; referans veri nadiren değiştiği için
  bu yeterli (değiştiğinde: migrasyon tekrar + API yeniden başlatma).
- İstekler arası paylaşılan mutable state yoktur — her istek kendi
  `Fatura`/`SatirKontrolSonucu` nesnelerini üretir, bu yüzden eşzamanlı
  istekler birbirini etkilemez.

**Kapsam dışı bırakılanlar (kullanıcı kararı, 2026-07-21):** Kimlik
doğrulama/yetkilendirme (auth) ve yük/eşzamanlılık testi bu adımda
**yapılmadı** — sadece HTTP API katmanı istendi. Bu ikisi ileride ayrıca ele
alınmalı (özellikle production'a çıkmadan önce auth şart).

Kurulum: `docs/how-to/api-calistirma.md`. Şema: `docs/reference/api-semasi.md`.

> ✅ **Uygulandı (2026-07-21):** `src/efatura_kdv/api.py` yazıldı, önce mock
> PostgreSQL bağlantısıyla, sonra kullanıcı Docker'ı kurup gerçek bir
> `postgres:16` container'ı (port 5434) ayağa kaldırdıktan sonra **gerçek**
> DB bağlantısıyla uçtan uca test edildi: `GET /saglik` ✅, gerçek fatura ile
> `POST /fatura/kontrol-et` → doğru `uygun` kararı ✅, 5 eşzamanlı istek →
> tutarlı sonuç ✅, bozuk XML → 400 ✅, satıcı VKN uyuşmazlığı → 400 ✅.

### 3.9 Geçmiş fatura kalemleri çapraz kontrol amaçlı ayrı bir katman — §3.7'nin sınıflandırma yasağını ihlal etmez

Kullanıcı isteğiyle (2026-07-21) `ubls/` klasöründeki geçmiş faturalar
PostgreSQL'e taşınıp yeni bir fatura geldiğinde "bu kalem daha önce hangi
oran(lar)la kesilmiş" diye çapraz kontrol yapan ayrı bir katman eklendi. Bu,
§3.7'nin **"geçmiş fatura verisi sınıflandırmada girdi olarak kullanılmaz"**
kararıyla ilk bakışta çelişiyor gibi görünse de kapsamı farklı — netleştirme
kullanıcıyla yapıldı (2026-07-21):

- **§3.7'nin yasakladığı şey:** geçmiş veriden kategori/oran ÖĞRENİP karar
  ÜRETMEK (embedding benzerliği ile "bu muhtemelen şu oran" tahmini) —
  golden rule 1'i ihlal eder (oran mevzuat kaynağı yerine geçmişten gelir).
- **Bu katmanın yaptığı şey:** karar mekanizmasına HİÇ dokunmuyor. NACE
  kural kontrolü kararı (uygun/insan incelemesi gerekli) her zaman olduğu
  gibi üretilmeye devam eder. Geçmiş veri SADECE ayrı bir bilgi/uyarı katmanı
  olarak eklenir:
  - NACE + geçmiş aynı fikirdeyse: gerekçeye ek güven sinyali ("bu kalem
    daha önce N kez bu oranla kesilmiş").
  - Farklı fikirdeyse: bir UYARI eklenir ("NACE kodu X oranı Y'yi
    destekliyor, ama bu kalem geçmişte şu tarih(ler)de Z oranıyla
    kesilmiş") — karar DEĞİŞMEZ, sadece inceleyen insana ek sinyal verilir.
  - Karar hiçbir zaman SADECE geçmiş veriye dayanarak üretilmez veya
    değiştirilmez (kullanıcı onayı, 2026-07-21).

**Kapsam — sadece kestiğimiz faturalar:** `ubls/` klasöründeki 1828 dosyanın
1448'i `inbox` (bize kesilmiş, biz alıcıyız), 380'i `outbox` (bizim
kestiğimiz, biz satıcıyız — hepsi tek bir satıcı VKN'sinde doğrulandı,
2026-07-21). Sadece **outbox** faturalar bu katmana kaydedilir — sistem
zaten sadece fatura sahibinin kestiği faturalarda çalışıyor (bkz. §0.2 alt
adım 3), inbox faturaların oranı bizim doğruluğumuzu yansıtmaz.

**Veri modeli:** kalem bazında (her fatura satırı ayrı kayıt — `satici_vkn,
kalem_adi_normalize, oran, fatura_no, fatura_tarihi`). Eşleşme normalize
edilmiş (küçük harf + boşluk temizleme) TAM string eşleşmesidir — bulanık/
benzerlik skoru kullanılmaz (kullanıcı kararı: basit, öngörülebilir, yanlış
eşleşme riski yok).

**Erişim:** ayrı bir endpoint, `POST /fatura/gecmis-kontrol` — ana
`POST /fatura/kontrol-et` akışına karışmaz, istemci isterse ayrıca çağırır.

Şema: `docs/reference/gecmis-fatura-semasi.md`. Migrasyon:
`scripts/gecmis_faturalari_yukle.py`. Kod: `src/efatura_kdv/gecmis_kontrol.py`.

> ✅ **İstisna kalemleri düzeltmesi (2026-07-22):** Oranı olmayan ama
> istisna kodu (ör. 301, ihracat) taşıyan kalemler önceden sessizce
> atlanıyordu — kullanıcı gerçek bir istisna faturasının (`AKK2025000000003`)
> geçmiş kontrolünde hiç görünmediğini fark edince bulundu ve düzeltildi.
> Artık bu kalemler `oran=0.0` + `istisna_kodu` sütunuyla kaydediliyor.
> Detay: `docs/reference/gecmis-fatura-semasi.md`.

### 3.9.1 MVP: çoklu fatura yükleme + otomatik geçmiş kaydı

Kullanıcı isteğiyle (2026-07-21, aynı gün) sistem ilk gerçek teste
hazırlanırken iki özellik eklendi:

1. **Çoklu fatura yükleme:** `POST /fatura/coklu-kontrol` (API) ve
   `test/web_arayuz.py` (web arayüzü) artık aynı satıcı VKN + NACE
   kod(lar)ıyla birden fazla fatura XML'ini tek seferde kabul ediyor.
   Kullanıcı senaryosu netleştirildi: "her oturumda bir şirket ve o
   şirketin bütün nace kodu verilir" — yani farklı şirketlerin faturaları
   aynı anda gönderilmiyor, format olarak zip/klasör değil tarayıcının
   native çoklu-dosya-seçimi (`<input multiple>`) kullanılıyor (kullanıcı
   kararı: "zip'lemeye gerek yok").
2. **Otomatik geçmiş kaydı:** Başarıyla kontrol edilen (VKN uyuşmazlığı/
   parse hatası olmayan) her fatura, kalem-oran satırları olarak otomatik
   `gecmis_fatura_kalemleri` tablosuna yazılıyor (`faturayi_gecmise_kaydet()`,
   bkz. `docs/reference/gecmis-fatura-semasi.md`). Yinelenen `fatura_no`
   tekrar yazılmıyor.

**Kapsam netleştirmesi (aynı gün, birkaç soru-cevap turu sonunda):**
Kullanıcı önce hem inbox hem outbox faturaların sisteme girebileceğini ama
sadece outbox'un kaydedilmesi gerektiğini belirtti; VKN karşılaştırma
mekanizması (fatura.satici.vkn vs fatura.alici.vkn) detaylandırıldıktan
sonra kullanıcı kapsamı sadeleştirdi: **"bu proje şuan sadece bizim
kestiğimiz faturaları incelemeli"** — yani inbox desteği eklenmedi, mevcut
VKN güvenlik kontrolü (kalem_nace_esleme.py, satici_nace.vkn ==
fatura.satici.vkn zorunluluğu) korundu ve otomatik kayıt bu kontrolün
üzerine inşa edildi (kontrolü geçen her fatura zaten outbox'tur).

> ⚠️ **Kritik hata bulundu ve düzeltildi (2026-07-21, aynı gün):**
> `test/web_arayuz.py`'nin ilk çoklu-dosya sürümü kullanıcının kendi şirket
> VKN'sini formda hiç sormuyordu, doğrudan faturanın kendi satıcı VKN'sini
> kullanıyordu — bu yüzden bir Turkcell **inbox** faturası yanlışlıkla
> "biz kesmişiz" gibi geçmiş veritabanına kaydedildi (yukarıdaki kapsam
> kararını fiilen ihlal etti). Tespit edilip (beklenmeyen VKN görülünce)
> aynı oturumda düzeltildi: form artık "Sizin şirketinizin VKN'si" alanını
> zorunlu istiyor. API tarafı (`/fatura/coklu-kontrol`) baştan doğru
> tasarlanmıştı — sadece web arayüzünde bu adım eksikti. Hatalı test kaydı
> temizlendi, düzeltme gerçek inbox (reddedildi) ve outbox (kabul edildi)
> faturalarıyla yeniden doğrulandı. **Ders:** Kullanıcı girdisi (VKN) ile
> faturadan çıkarılan veriyi (fatura.satici.vkn) karıştırmak, güvenlik
> kontrolünün amacını (yanlış satıcıya ait bilgiyle karşılaştırma yapmayı
> önlemek) sessizce boşa çıkarabiliyor — yeni bir giriş noktası (web
> arayüzü, API, script) eklerken var olan güvenlik kontrolünün GERÇEKTEN
> aynı şekilde uygulandığını (parametre kaynağı dahil) doğrulamak gerekiyor.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-21):** Gerçek
> `curl`/web isteğiyle test edildi — yeni fatura → kaydedildi, aynı fatura
> tekrar → kaydedilmedi (yinelenen engellendi), inbox (yanlış VKN) → 
> reddedildi/kaydedilmedi, karışık istek (1 geçerli + 1 bozuk XML) → geçerli
> işlendi, bozuk hata olarak işaretlendi, tüm istek düşmedi. Kod:
> `src/efatura_kdv/gecmis_kontrol.py` (`faturayi_gecmise_kaydet()`),
> `src/efatura_kdv/api.py` (`/fatura/coklu-kontrol`), `test/web_arayuz.py`.

**3 sekmeli sonuç görünümü (2026-07-21, aynı gün, sonraki bir isteğiyle):**
Kullanıcı çoklu fatura yükleme sonuçlarında VKN uyuşmayan (bize ait olmayan)
faturaların ayrı bir sekmede toplanmasını istedi — "bu faturayı biz
kesmedik, fatura bize gelsin diye uyarsın". `test/web_arayuz.py` artık 3
sekme gösteriyor: **Başarılı** (NACE kontrolü tamamlananlar), **VKN
Uyuşmazlığı** ("bu fatura bize ait değil" — yukarıdaki VKN güvenlik
kontrolü tetiklenince), **Diğer Hatalar** (bozuk XML/parse hatası gibi
teknik sorunlar). Bu üçünü ayırt edebilmek için `kalem_nace_esleme.py`'ye
`SaticiVknUyusmazligiHatasi` (ValueError alt sınıfı — geriye dönük uyumlu,
mevcut `except ValueError` blokları hâlâ yakalar) eklendi;
`satir_bazli_kontrol_et()`'teki VKN güvenlik kontrolü artık bu spesifik
exception'ı fırlatıyor. Sekme geçişi saf CSS+JS ile (harici kütüphane yok).

> ✅ **Uygulandı ve gerçek testle doğrulandı (2026-07-21):** 3 senaryo
> (outbox+doğru VKN → Başarılı, inbox+yanlış VKN iddiası → VKN Uyuşmazlığı,
> bozuk XML → Diğer Hatalar) `curl` ile tek istekte gönderildi, üç sekme de
> doğru sayıda (1/1/1) sonuç gösterdi.

### 3.10 Ana projeye (model_eval / TDHP tahmin pipeline'ı) entegrasyon — Adım 0, HTTP API üzerinden

Bu repo (Mcp_mimarisi) kendi başına bağımsız ama gerçek amacı, aynı
`AıData2/` çalışma alanındaki ayrı bir "ana proje"nin — TDHP (Tek Düzen
Hesap Planı) hesap kodu tahmin pipeline'ının (`~/Desktop/AıData2/model_eval/`,
RAG + ChromaDB + çoklu-model karşılaştırma, bkz. `model_eval/RESULTS.md`,
`model_eval/core/parsing.py`) **önüne** eklenmek. Kullanıcı netleştirdi
(2026-07-22): entegrasyon **HTTP API üzerinden, ayrık** olacak — iki proje
ayrı süreç olarak kalır, sadece ağ üzerinden konuşur (kod tabanı
birleştirilmez, monorepo yapılmaz).

> ⚠️ **Düzeltme (2026-07-22, aynı gün):** Bu bölüm ilk yazıldığında
> yanlışlıkla `~/Desktop/AIData/` (İngilizce "I", "2" yok — eski/yedek bir
> klasör, plan aşamasındaki `mimari.md`/`AGENTS.md` içeriyor) hedef
> alınmıştı. Kullanıcı düzeltti: gerçek, aktif geliştirilen "ana proje"
> `~/Desktop/AıData2/model_eval/`'dir (Türkçe "ı", aynı üst klasör —
> `Mcp_mimarisi` de onun altında). Kanıt: her iki projenin de aynı gerçek
> şirket VKN'sini (`0460351893`, Akyüzlü Dövme ve Kaldırma Ekipmanları)
> ve aynı `ubls/`/`Archive2` fatura verisini kullanması. `AIData/` içine
> yanlışlıkla eklenen notlar geri alındı (silindi); doğru entegrasyon
> kararı `~/Desktop/AıData2/model_eval/entegrasyon.md`'ye yazıldı.

**Neden ayrık (monorepo değil):** CLAUDE.md'deki "Hesap Planı Eşleme
Modülüne dokunulmuyor" kuralıyla tutarlı — Mcp_mimarisi, model_eval'ın
koduna hiç dokunmadan, sadece girdi/çıktı sözleşmesiyle (HTTP request/
response) entegre olur. Bu ayrım, model_eval'ın kendi geliştirme hızını
(ChromaDB/Ollama/çoklu-model deneyleri) etkilemeden Mcp_mimarisi'nin
bağımsız evrilmesini sağlar.

**Akış noktası — "Adım 0":** model_eval'ın `core/parsing.py`'deki
`parse_invoice_xml()` fonksiyonu, ham/henüz muhasebeleşmemiş bir XML
faturayı (`--data-format xml`, ground truth yok) okuyup TDHP tahmini için
hazırlar (bkz. `model_eval/yeni_faturalar_tdhp.md`,
`model_eval/results_new_invoices/` — gerçek çalıştırılmış örnekler, ör.
`AKK2026000000192`). Kullanıcı kararı: KDV doğrulama **Adım 0** olarak bu
fonksiyondan bile ÖNCE eklenir — ham XML doğrudan Mcp_mimarisi'nin
`POST /fatura/kontrol-et` endpoint'ine gönderilir:

```
[Ham UBL-TR XML]
      │
      ▼
Adım 0: Mcp_mimarisi POST /fatura/kontrol-et
  (satici_vkn + satici_nace_kodlari + fatura_xml)
      │
      ├── genel_karar = "uygun" ──────────────┐
      │                                        ▼
      │                    Adım 1: parse_invoice_xml() (core/parsing.py)
      │                    Adım 2: RAG (ChromaDB, rag_common.py)
      │                    Adım 3: Fine-tuned/bulut LLM → TDHP kodu tahmini
      │                    Adım 4: Borç=Alacak doğrulaması
      │
      └── genel_karar = "insan_incelemesi_gerekli" ──▶ TDHP tahminine HİÇ girmez
                                                        (insan incelemesi kuyruğu)
```

Bu, PROJECT.md §0.1'deki "akış sırası tersine çevrildi — doğrulama TDHP
eşlemesinden ÖNCE çalışır" kararının somut, sistemler-arası karşılığıdır.

**Sözleşme (model_eval tarafının bilmesi gereken):**
- İstek: `docs/reference/api-semasi.md`'deki `FaturaKontrolIstegi` şeması
  (`fatura_xml`, `satici_vkn`, `satici_nace_kodlari`).
- `satici_vkn`: `core/constants.py`'deki `DEFAULT_OWN_VKN` ile aynı değer
  (`0460351893`) — model_eval zaten şirketin kendi VKN'sini biliyor.
- Cevap: `genel_karar` alanı `"uygun"` ise TDHP pipeline'ı (Adım 1-4)
  çalıştırılır; `"insan_incelemesi_gerekli"` ise hiç çalıştırılmaz.
- `satici_nace_kodlari` model_eval tarafından sağlanmalıdır — Mcp_mimarisi
  VKN→NACE lookup yapmaz (bkz. §0.2 alt-adım 3).

Karşı taraftaki (model_eval) entegrasyon dokümanı:
`~/Desktop/AıData2/model_eval/entegrasyon.md`.

**Kapsam dışı (bu kararla birlikte netleşmedi, ayrıca ele alınmalı):**
production ortamında model_eval'ın hangi ağ adresinden Mcp_mimarisi
API'sine erişeceği (aynı makine varsayıldı, `localhost:8000`), zaman
aşımı/hata durumunda davranış (Mcp_mimarisi API'si erişilemezse fatura ne
olur), auth (bkz. §3.8'deki "auth kapsam dışı" kararı — bu, iki servis
arası çağrıda da geçerli).

> ✅ **Karar verildi (2026-07-22):** Kullanıcı entegrasyon şeklini (HTTP API,
> Adım 0) onayladı. Henüz KOD YAZILMADI — bu, model_eval tarafı ileride
> Adım 0 çağrısını eklerken referans alacağı bir sözleşme kararıdır.

### 3.11 Çok kullanıcılı MVP mimari denetimi — 4 teknik borç maddesi (2026-07-22)

§3.10'daki entegrasyon kararıyla birlikte, model_eval ile ortak bir "çok
kullanıcılı MVP'ye çıkmadan önce mimari sağlamlık" denetimi yapıldı
(görev promptu: `GOREV_MIMARI_DUZELTME.md`). Auth/rate-limiting bilinçli
olarak KAPSAM DIŞI bırakıldı (ayrı bir karar, kullanıcı henüz vermedi —
bkz. §6). Bulunan ve çözülen 4 madde:

1. **`fatura_no` mükerrer kayıt race condition** — `faturayi_gecmise_kaydet()`
   (`src/efatura_kdv/gecmis_kontrol.py`) artık `islenmis_faturalar` (yeni,
   `fatura_no TEXT PRIMARY KEY`) claim tablosuna `INSERT ... ON CONFLICT DO
   NOTHING RETURNING` ile tek transaction'da "kazanan tek istek" deseni
   kuruyor — eskiden "SELECT var mı → yoksa INSERT" iki ayrı adımdı, lock
   yoktu. Detay: `docs/reference/gecmis-fatura-semasi.md` "race condition
   düzeltmesi" bölümü.
2. **Migration sistemi (Alembic)** — şema artık `alembic/versions/`'daki
   iki migration'la versiyonlanıyor (`9846b14dc658`: mevcut şemanın kaydı,
   `7ec7f9c705a3`: `islenmis_faturalar`). `scripts/excel_to_postgres.py` /
   `scripts/gecmis_faturalari_yukle.py` hâlâ VERİ yükleme işini yapıyor,
   sadece şema oluşturma sorumluluğu Alembic'e taşındı. Detay:
   `docs/how-to/migration-calistirma.md`.
3. **DB connection pool** — `GecmisFaturaDeposu`, `psycopg2.pool.
   ThreadedConnectionPool` (varsayılan `minconn=2, maxconn=10`) kullanıyor;
   önceden her sorgu/yazma kendi `psycopg2.connect()`'ini açıp kapatıyordu.
   Detay: `docs/how-to/api-calistirma.md` "connection pool" bölümü.
4. **Hata yönetimi** — `api.py`'de `psycopg2.OperationalError` (DB down) ve
   `psycopg2.pool.PoolError` (pool tükendi) için özel `exception_handler`'lar
   eklendi, ikisi de client'a `503` + generic mesaj döner, ham hata sadece
   sunucu logunda. Genel `Exception` handler'ı da 500 + generic mesaja
   çevirir — önceden ham exception metni `detail`e sızıyordu. Detay:
   `docs/reference/api-semasi.md` "Hata yönetimi" bölümü.

> ✅ **Uygulandı ve gerçek Postgres ile doğrulandı (2026-07-22):** (1) 10
> eşzamanlı thread aynı `fatura_no` ile çağrıldı, sadece 1'i `True` döndü,
> DB'de tek kopya doğrulandı. (2) `alembic stamp` + `alembic upgrade head`
> ile mevcut geliştirme DB'sinde gerçekten çalıştırıldı, `islenmis_faturalar`
> oluştu. (3) 10 eşzamanlı sorgu (pool `maxconn=10` sınırında) hatasız
> tamamlandı. (4) `docker stop`/`docker start` ile gerçek DB kapatılıp
> açılarak `503`→`200` geçişi gerçek `curl` isteğiyle doğrulandı.

---

## 4. Teknoloji Yığını (Katmanlı)

| Katman | Teknoloji | Faz | Nerede |
|---|---|---|---|
| Girdi | UBL-TR XML e-fatura (NACE kodu + beyan edilen KDV oranı + kalem metni) | 1 | Parser: `src/efatura_kdv/ubl_parser.py` — TDHP eşleme modülünden ÖNCE (bkz. §0.1) |
| NACE→oran kural kontrolü | `nace_kdv (1).xlsx` (`2026_KOD_DEGISIKLIKLERI` sayfası), deterministik eşleşme (LLM yok) | 1 | ✅ `src/efatura_kdv/nace_kural_kontrolu.py` — bkz. §0.1, §0.2 |
| NACE tabanlı kategori/beklenti çözümleme + çok-oranlı NACE'lerde LLM zero-shot kapalı-küme sınıflandırma | NACE+Kategori Excel referansı (`kdv_oran_referans2.xlsx`/NACE_KDV) + LLM | 2 | Excel verisi yüklü, kod henüz yazılmadı — bkz. §3.7 |
| Oran/tevkifat/istisna doğrulama (tarih bazlı, güncel mevzuat) | Sıralı agent workflow + Mevzuat MCP aracı + `kdv_oran_referans2.xlsx` (I/II sayılı liste, tevkifat kodları) statik taban | 2 | Excel verisi yüklü, kod henüz yazılmadı |
| Mevzuat Kural Deposu | Yapılandırılmış, tarih aralıklı kural tablosu (`konu, kapsam, oran/kod, yürürlük_başlangıç/bitiş, kaynak`) | 2 | Bu repo (henüz yazılmadı) — bkz. §3.6 |
| Mevzuat İzleme & Etiketleme Pipeline | Offline/periyodik — mevzuat.gov.tr/GİB'i izler, kural deposunu günceller | 2 | Bu repo (henüz yazılmadı) — bkz. §3.6 |
| Mevzuat MCP Aracı | Sorgu anında, kural deposunu tarih+kapsam filtresiyle sorgular, yapılandırılmış sonuç döner | 2 | Bu repo (henüz yazılmadı) — bkz. §3.6 |
| Geliştirme/test | Skill tabanlı hızlı model testi (ör. Codex) → production kod | 1 ve 2 | — |

### Faz 1 veri akışı (şimdiki hedef, bkz. §0.1)

```
UBL-TR Fatura → [NACE kodu + beyan edilen KDV oranı]
   → nace_kdv (1).xlsx'te NACE (FAALIYETKODU) satırı aranır
        ├─ NACE bulunamadı → insan incelemesi gerekli
        └─ NACE bulundu → o satırda dolu olan oran sütunları (%0/%1/%10/%20/istisna) okunur
             ├─ Beyan edilen oran bu listede VAR → uygun → TDHP Eşleme modülüne aktar
             └─ Beyan edilen oran bu listede YOK → insan incelemesi gerekli

Karar: uygun / insan incelemesi gerekli   (Faz 1'de "uyumsuz" kesin kararı
henüz üretilmiyor — bkz. §0.1 adım 4-5 gerekçesi)
```

### Faz 2 veri akışı (mevzuat MCP entegre olduktan sonra)

```
UBL-TR Fatura → [kalem metni + NACE ana/tali + tutar + tarih + alıcı + beyan edilen oran/tevkifat/istisna]
   → NACE tabanlı beklenti kurma (Excel referansı, deterministik)
        ├─ Tek oranlı → hızlı yol: NACE beklentisi + kalem metni çelişki kontrolü (LLM, tek geçiş)
        └─ Çok oranlı (KALEM_GEREKLI) → kalem metni, NACE'ye özel kapalı alt-kategori kümesinden LLM ile sınıflandırılır
              └─ Karar için gereken ek veri faturada yoksa → ERKEN ÇIKIŞ: insan incelemesi gerekli
   → Mevzuat MCP sorgusu → Mevzuat Kural Deposu'nu tarih+kapsam filtresiyle sorgular (yapılandırılmış sonuç)
   → Karşılaştırma: beyan edilen vs olması gereken (kalem > NACE önceliğiyle, golden rule 2)
   → Karar: uygun / uyumsuz / insan incelemesi gerekli → uygun ise TDHP Eşleme modülüne aktar

(Ayrı, offline döngü: Mevzuat İzleme & Etiketleme Pipeline → mevzuat.gov.tr/GİB'i
izler → yeni/değişen kuralları Mevzuat Kural Deposu'na yazar. Bu döngü fatura
işleme anının dışındadır, latency'e girmez.)
```

---

## 5. Riskler

| Risk | Etki | Önlem / Durum |
|---|---|---|
| Mevzuat Kural Deposu, İzleme & Etiketleme Pipeline'ın gecikmesi/hatası yüzünden güncel olmayabilir | Depo güncellenmeden önce yürürlüğe giren yeni bir oran/tevkifat kuralı gözden kaçar → yanlış "uygun" kararı | AÇIK — pipeline'ın ne sıklıkla çalışacağı ve gecikme durumunda nasıl davranılacağı (ör. "depo son X günden eskiyse insan incelemesine düşür") henüz tasarlanmadı |
| Gayrimenkul (681100) gibi çok değişkenli NACE kodlarında faturada eksik bilgi | Sistem yanlışlıkla kesin karar üretebilir | Kısmen kapalı — tasarım kuralı olarak "her zaman insan incele" bayrağı planlanıyor (§3.7), uygulanması bekliyor |
| Tevkifat alt sınırı (2026: KDV dahil 12.000 TL) ve belirlenmiş alıcı listesi zamanla değişir | Statik tabloya güvenilirse eski eşik uygulanır | AÇIK — bu değerler de MCP üzerinden tarih bazlı doğrulanmalı, sabit kodlanmamalı |
| Çok-oranlı NACE kodlarında kalem metni belirsiz/yetersizse LLM yanlış alt-kategori seçebilir | Yanlış kategoriyle MCP'ye sorulur → yanlış oran/tevkifat kararı | AÇIK — düşük güven skorunda "insan incelemesi gerekli"ye düşürme eşiği henüz tasarlanmadı |
| Otonom sistem insan onayı olmadan çalışıyor | Yanlış "uygun" kararı doğrudan muhasebe kaydına gidebilir | Kısmen kapalı — "insan incelemesi gerekli" çıktısı tasarım kuralı olarak var, ama eşik/tetikleyici mantığı henüz kodlanmadı |

---

## 6. Kapsam Dışı

- Hesap Planı Eşleme modülünün (vektör benzerlik ile kod bulma) kendisi —
  var olan, dokunulmayan bir sistem.
- Kullanıcıyla soru-cevap / interaktif onay akışı — sistem tamamen otonom
  çalışır, çıktısı üç değerden biridir.
- Faturanın muhasebe kaydına otomatik yazılması — bu projenin çıktısı bir
  karardır (uygun/uyumsuz/insan incele), kayıt işlemi kapsam dışı.
- Geçmiş faturaların (kalem+oran) kategori sınıflandırma girdisi olarak
  kullanılması — bkz. §3.7, bilinçli olarak dışarıda bırakıldı.
- **(Faz 1 için ayrıca)** Mevzuat MCP'si, Kural Deposu, izleme/etiketleme
  pipeline'ı, LLM ile kalem/alt-kategori sınıflandırması, tevkifat kontrolü,
  istisna nüansı — bunların hepsi Faz 2'ye ertelendi (bkz. §0.1). Faz 1
  sadece NACE→oran excel eşleşmesidir.
- **(Faz 1 için ayrıca)** TDHP Eşleme modülünü doğrulama sonrası nasıl
  tetikleyeceği (entegrasyon mekanizması) — kullanıcı bunu bilinçli olarak
  sonraya bıraktı (2026-07-17), henüz tasarlanmadı.

---

## 7. Claude Code İçin Çalışma Notları

- Mevzuat detaylarında (oran, tevkifat kodu, yürürlük tarihi) emin değilsen
  ezbere yazma, web araması/MCP ile teyit et — bu veriler sürekli değişiyor.
- Referans Excel dosyaları repoya yüklendi (`nace_kdv (1).xlsx`,
  `nace_kod_degisikligi_2026_03_24.xlsx`) — içerikleri hakkında konuşurken
  önce dosyayı aç (openpyxl ile), "muhtemelen şöyle bir sütun vardır" deme.
  Sayfa adları ve sütun başlıkları için bkz. §0.1 ve
  `docs/reference/nace-kdv-excel-yapisi.md`.
- **Her tasarım adımını CLAUDE.md'deki "Kritik gerçekler" listesine karşı
  çapraz kontrol et** — ilk workflow taslağında bu atlandı (geçmiş faturalarda
  kategori etiketi olmadığı unutuldu, kullanıcı düzeltti). Yeni bir bileşen
  önerirken önce bu listeyi tekrar oku.
- **Faz 1 kapsamını genişletme:** Faz 1'e mevzuat MCP'si, tevkifat kontrolü
  veya LLM ile kalem sınıflandırması gibi Faz 2 parçalarını sessizce ekleme —
  kullanıcı bu ayrımı bilinçli olarak yaptı (2026-07-17), kapsam genişlemesi
  gerekiyorsa önce sor.
- Sıradaki adım: Faz 1 kural kontrolünün somut kodu/skill'i (NACE→oran
  eşleşmesi) — mevzuat MCP aracı tasarımı Faz 2'de ele alınacak.
- **Kritik değişiklikten sonra `docs/`'u aynı görevde güncelle** (Diátaxis:
  neden → `explanation/`, MCP şeması/env → `reference/`, adımlar → `how-to/`).

---

## 8. Dosya Haritası

```
Mcp_mimarisi/
├── PROJECT.md              # Bu dosya
├── CLAUDE.md               # AI ajanları için çalışma kuralları
└── docs/                   # Diátaxis: tutorials / how-to / reference / explanation
    └── CHANGELOG.md         # Her commit'e tek satır
```
