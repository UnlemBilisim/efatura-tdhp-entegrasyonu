# Yapılacaklar

Karara bağlanmamış ya da ertelenmiş işler. Bir madde tamamlanınca buradan
silinir, ilgili belgeye `✅ Uygulandı` notu düşülür.

## Doğrulama kuralı

- [x] **`PAYABLE_MISMATCH` kalıcı ölçüm script'i yazıldı, gerçek veriyle
  kategorize edildi** (2026-10-01). `model_eval/scripts/
  payable_mismatch_analiz.py` — `Archive2/jsons`'daki 1646 gerçek
  muhasebeci kaydının KENDİSİNİ (LLM tahmini değil) `validate_prediction`'a
  verip kuralın kendi reddetme oranını ölçer, reddi 4 kategoriye ayırır.
  **Sonuç (önceki, geçici/elle yapılan analizden farklı — bu kalıcı ve
  tekrarlanabilir):** 1646 kayıttan **153'ü (%9,3) reddediliyor**:
  - **85'i** ISTISNA (ihracat), oran %0–3 arası — kur farkı şüpheli,
    tutarlı bir dağılım gösteriyor (86 kayıttan 85'i bu aralıkta kümelenmiş).
  - **26'sı** borç, ödenecek tutarın ~2 katı — mükerrer kayıt şüpheli.
  - **8'i** ≤1 TL fark — gerçek yuvarlama, MONEY_TOLERANCE çok katı.
  - **34'ü gerçekten açıklanamıyor** — bunun 22'si elle incelenince **veri
    kalitesi sorunu** olduğu doğrulandı (örnek: `GIB2025000000011`'de TEK
    bir JSON dosyasında İKİ farklı cari hesabın — "Elis Özdaş" ve "Fevzi
    Kömür" — kaydı karışmış, `header.payable` sadece birine ait, borç
    toplamı ikisinin toplamını yansıtıyor; bu bizim kodumuzun değil
    kaynak verinin/dışa aktarımın bir hatası).
  Tam detay, dosya adları, oranlar: `model_eval/results/
  payable_mismatch_analiz.json` (script her koşuda üretir).

- [x] **Kullanıcı kararı (2026-10-01): toleransa/kurala DOKUNULMUYOR.**
  26 (mükerrer kayıt şüphesi) + 34 (gerçekten açıklanamayan, 22'si elle
  doğrulandı) = 60 kayıt için `PAYABLE_MISMATCH`'in reddetmesi aslında
  **doğru davranış** — bunlar kaynak verideki/dışa aktarımdaki gerçek
  sorunlar, kuralın bir eksikliği değil. Asıl ihtiyaç kuralı gevşetmek
  değil, **bu tür anomalileri bizim fark edip izleyebilmemizdi**
  ("bunun gibi veya daha farklı gelen dosyadan dolayı yapılan hataları
  bizim farkedebilmemiz gerek").
- [x] **Çözüm: audit log'a `approvable` + `red_kodlari` eklendi**
  (2026-10-01). Önceden hangi faturanın NEDEN (`PAYABLE_MISMATCH`,
  `UNBALANCED` vb.) reddedildiği audit log'dan çıkarılamıyordu — sadece
  `asama="tdhp_dogrulama_basarisiz"` görünüyordu. Artık her
  `/fatura/isle` audit satırında `approvable` (bool) ve `red_kodlari`
  (sadece KOD listesi, mesaj metni değil — hassas veri sızmasın diye)
  var; zamanla "kaç fatura hangi nedenle reddedildi" sorgulanabilir.
  Gerçek canlı istekle doğrulandı. 5 yeni test:
  `entegrasyon/tests/test_audit_log.py`. Detay: `CLAUDE.md` 2026-10-01 notu.
  `MONEY_TOLERANCE`/ISTISNA kur-farkı kuralı gelecekte gündeme gelirse,
  `model_eval/scripts/payable_mismatch_analiz.py` önce/sonra karşılaştırma
  için hazır duruyor.

## Alt kırılım seçimi — üç yöntem karşılaştırması (2026-09-29, yarım kaldı)

Bağlam: cari kart (alt kırılım) seçiminde bugünkü isim-benzerliği + LLM akışının
yerini/tamamlayıcısını değerlendirmek için TypeSafe Jev, Ollaya (yerel açık
model) ve bugünkü LLM'i aynı zor vakalarda karşılaştırma fikri konuşuldu.
Kur her zaman **orijinal** para biriminde tutulacak (kullanıcı kararı — TL'ye
çevirme yok).

**Ölçüldü (proje dışı, geçici script'lerle — kod değişikliği YAPILMADI):**
- Bugünkü isim eşlemesi + "aynı VKN'nin geçmişte en sık kullandığı kart"
  sinyali birleştirilince sessiz yanlış seçim 75'ten 28'e iniyor
  (1527 gerçek kayıt üzerinde). İkisi aynı kartı söylediğinde %99,4 doğru;
  çeliştiğinde yazı-tura (~%50) — asıl "zor vaka" kümesi burası, **144 kayıt**.
  Bu bulgu henüz koda işlenmedi, sadece ölçüldü.
- Sadece faturanın döviz/TL durumuna göre `.01`/`.02` kart seçimi TEK BAŞINA
  yeterli değil (54 kazanç, 19 kayıp) — reddedildi.

**Altyapı hazır:**
- **Ollaya** çalışıyor: `unlem-gx10-01` sunucusunda `ollaya-efatura` container'ı
  (port 127.0.0.1:11437, sadece localhost), `winnow` modeli indirilmiş ve
  gerçek soruyla test edilmiş (10,3s, CPU modunda — bu sunucuda ARM64 olduğu
  için CUDA image'ı yok, `linux/arm64` CPU image'ı kullanılıyor).
  Mac'teki ilk deneme (`ollaya-deneme`, port 11436) bellek yetersizliğinden
  (Docker Desktop'a ~1,93 GB ayrılmış) çalışmadı, terk edildi — hâlâ ayakta
  duruyor ama işlevsiz, kapatılabilir.
- **SSH erişimi** `unlem-gx10-01`'e kuruldu: `~/.ssh/unlem_gx10_ollaya`
  (anahtar çifti, sadece bu görev için üretildi). Bu vesileyle sunucuda
  21,2 GB'lık kullanılmayan disk (durmuş `vllm-edefter-core` container'ı +
  image'ı, başka bir projeye ait) kullanıcı onayıyla temizlendi.

**Jev/TypeSafe — gerçek API çağrısıyla test edildi (2026-10-01):**
- API sözleşmesi bulundu/doğrulandı: `POST https://api.typesafe.ai/v1/systemone`,
  `Authorization: Bearer <TYPESAFE_API_KEY>`, gövde
  `{"state", "model": "jev-latest", "questions": {"<ad>": {"type": "choice",
  "instructions", "criteria": {kod: açıklama, ...}}}}`, cevap
  `answers.<ad>.{choice, confidence, probabilities}` (başka bir projedeki
  — `aktarimli-chat/packages/intent-router/` — gerçek, çalışan entegrasyondan
  teyit edildi, uydurulmadı).
- Küçük ölçekte (3 seçenek, gerçek mizan verisiyle: "A.E.B. Kaynak Muh San
  Tic" unvanı) canlı test edildi — `200`, doğru kartı %99 güvenle seçti.
- **Kritik kısıt bulundu: TypeSafe Choice API en fazla 255 seçenek kabul
  ediyor** (`400 Too many choices. Must have at most 255 choices.`) — gerçek
  mizanımızdaki ana cari hesaplar bunun çok üzerinde (`120`: 390, `320`: 993
  alt kırılım). **Doğrudan tüm alt kırılım listesiyle kullanılamaz** —
  kullanılacaksa önce bir ön-eleme adımı (örn. isim benzerliğiyle en yakın
  N<255 adayı seçip sadece onları TypeSafe'e sormak) gerekir; bu, kullanıcı
  kararı gerektiren bir tasarım sorusu, henüz karar verilmedi.
- Veri kapsamı konuşuldu ama netleşmedi: sadece unvan + aday kart adları +
  para birimi gitmeli, tutar/VKN gitmemeli (bu bir dış bulut servisi — KVKK
  açısından netleşmesi gerek).
- Üçü de (Jev/Ollaya/mevcut LLM) hazır olunca 144 zor vakayı üçüne de
  koşturup karşılaştırma HENÜZ yapılmadı — Jev'in 255 kısıtı yüzünden bu
  karşılaştırma öncesi ön-eleme kararı verilmeli.

**3 haneli ANA KOD tahmini için iki-asamali (grup 1-7 → 3 haneli) pilot
ölçüm (2026-10-02, kullanıcı önerisi — "sadece 1den 7 ye kadar tahmin
sonra 3 haneli" — gerçek test edildi):**
- Fikir doğru yönde: TDHP'nin 271 ana kodu tek başına hem TypeSafe'in 255
  hem Ollaya'nın 64 sınırını aşıyor, ama ilk hane bazında 7 gruba
  ayrıldığında en büyük grup 56 kod (2xx) — her iki servis için de rahatça
  sığıyor. Tek bir fatura üzerinde (3 kalem: 120/600/391) İLK denemede
  %92-99 güvenle hepsi doğru çıkmıştı.
- **Ama n=10 gerçek faturada (36 hesap kodu kalemi, `Archive2/jsons`'dan
  rastgele seçildi) GERÇEK doğruluk ölçüldüğünde sonuç çok daha düşük
  çıktı: en iyi denemede %44,4 (16/36 doğru 3 haneli kod)** — mevcut
  sistemin (n=1646, exact_pair_match %81,4) çok altında. Script:
  `model_eval/scripts/typesafe_3haneli_pilot.py`, ham sonuç:
  `model_eval/results/typesafe_3haneli_pilot.json`.
- **Kök neden — her kalem için TypeSafe'e verilecek "bağlam metni" (state)
  üretmek kendi başına zor bir problem çıktı, en az 3 ayrı iterasyonda
  farklı sistematik hatalar bulundu:**
  1. İlk denemede (%16,7) tüm kalemlere neredeyse aynı jenerik metin
     verilmişti — ayırt edici bilgi olmayınca model her seferinde aynı
     (yanlış) cevabı verdi.
  2. İkinci denemede (%44,4, EN İYİ sonuç) kalem bazında ayırt edici
     açıklama (vergi adı, ürün adı, karşı taraf) + **yön düzeltmesi**
     eklendi — ground-truth JSON'daki `header.invoice_type` ("SATIS")
     KARŞI TARAFIN fatura türüdür, BİZİM yönümüzü (alıcı mı satıcı mı)
     göstermez; dosya adındaki `-inbox`/`-outbox` ekiyle yön açıkça
     belirtilince 320/329 (cari borç) kalemlerindeki sistematik "yanlışlıkla
     600 (satış geliri)" hatası büyük ölçüde düzeldi.
  3. Üçüncü denemede (vergi/gider ayrımını daha da netleştirmeye çalışınca)
     sonuç %30,6'ya GERİLEDİ — daha fazla açıklayıcı kelime eklemek bazı
     kalemlerde (191 KDV) yeni karışıklıklar yarattı. Bu, prompt
     mühendisliğinin DOĞRUSAL iyileşmediğini gösterdi — iyi niyetli bir
     netleştirme başka bir yeri bozabiliyor.
  - **Kalıcı sorun kalan kodlar:** 770/730 (faaliyet giderleri) ve 689
    (diğer olağandışı gider/vergi) kalemleri üç denemede de tutarlı
    şekilde yanlış koda (120, 180, 191 gibi) gitti — bu kalemler için
    doğru ayırt edici açıklama henüz bulunamadı.
- **KARAR (2026-10-02, kullanıcı kararı): TypeSafe/Jev KULLANILMAYACAK —
  araştırma kapatıldı.** Gerekçe: iki-aşamalı Choice yöntemi teorik olarak
  seçenek sınırını aşmanın bir yolu, ama PRATİKTE her kalem için doğru
  "bağlam metni" üretmek, mevcut sistemin (LLM'in tüm fatura bağlamını bir
  arada görmesi) yaptığı işin kendisi kadar karmaşık çıktı. %44,4 doğruluk,
  mevcut sistemin %81,4'ünün çok altında kaldı — bu farkı kapatmak
  belirsiz sayıda ek iterasyon gerektirirdi, kazanç (hız/maliyet/TypeSafe'in
  kendi güven skoru üretmesi) bunu haklı çıkarmadı. Test script'i ve
  `.env`'deki `TYPESAFE_API_KEY` kaldırıldı — ileride tekrar gündeme
  gelirse bu bölümdeki bulgular (API sözleşmesi, 255 seçenek sınırı, yön
  tespiti hatası, 3 deneme detayı) başlangıç noktası olarak kullanılabilir.

**Ollaya — aynı gün gerçek testle keşfedildi, Jev'den DAHA KISITLI çıktı:**
- Ollaya, TypeSafe ile **BİREBİR AYNI API sözleşmesini** konuşuyor —
  `POST http://<sunucu>:11437/v1/systemone` (tünel üzerinden), aynı
  `questions.<ad>.{type:"choice", instructions, criteria}` gövdesi, auth
  gerektirmiyor (TypeSafe Bearer token isterken Ollaya istemiyor). Model
  adı `"winnow"` — gerçek istekte `"model": "winnow:latest"` olarak
  yanıtlandı. Aynı 3 seçenekli test (önce TypeSafe'de denenen) burada da
  doğru sonucu verdi (%99,97 güven).
- **Kritik bulgu: Ollaya'nın seçenek sınırı TypeSafe'in 255'inden ÇOK DAHA
  DÜŞÜK — gerçek ikili aramayla tam olarak bulundu: 64 seçenek geçiyor,
  65 geçmiyor** (`422 TOO_MANY_OPTIONS`, hata mesajı "option budget"
  diyor — muhtemelen sabit bir SAYI değil, toplam prompt token bütçesi;
  64 bu özel test verisiyle (320 hesabının ilk N alt kırılımı, ortalama
  unvan uzunluğuyla) ölçülen sınır, farklı/daha uzun isimli bir kritere
  karşı bu sayı değişebilir). Bu, gerçek mizanımızdaki `320` (993 seçenek)
  için gereken ön-elemeyi Jev'dekinden (N<255) çok daha agresif (N<~64)
  yapmayı gerektirir — üç yöntem karşılaştırması tasarlanırken bu ikisinin
  AYRI ön-eleme eşikleri olması gerektiği unutulmamalı.
- Ollaya varsayılan portu (11435) bizim SSH tünelimizle çakışıyor — Mac'te
  11436, sunucuda 11437 kullanıldı, bu geçiciydi; kalıcı bir port kararı yok.
- (2026-09-29 sonu itibarıyla tünel ve Docker servisleri elden geçirildi,
  bkz. sohbet geçmişi — bu maddenin "kararsız" kısmı Jev ve nihai
  karşılaştırma, altyapı sorunları değil.)

## Yeni müşteri onboarding — canlıya çıkış (2026-09-29, kısmen tamamlandı)

2 gün içinde canlıya çıkış hazırlığı: 5-10 müşteri aynı anda gelecek, her
biri VKN + fatura geçmişi (XML) + mizan + yevmiye kaydı (son 6 ay) ile. Temel
altyapı (şema/mizan/RAG tek komutla, yanlış-VKN koruması, yevmiye eşleştirme,
teslim belgeleri) tamamlandı ve gerçek testle doğrulandı — bkz.
`model_eval/CLAUDE.md` 2026-09-29/09-30 notları, mock çok-müşavirli uçtan
uca test için kök `CLAUDE.md` ("Yeni müşteri onboarding'i tek komutla"
kuralının altındaki not).

- [x] **Detaylı test yazıldı** (2026-10-01). `model_eval/tests/
  test_yevmiye_fatura_esle.py` — 13 yeni test, istenen 4 senaryonun
  (mutlu yol, yanlış VKN, eksik sütun, eşleşmeyen fatura no) hepsi +
  2 ek güvenlik senaryosu (boş girdi, kısmi eşleşme). `musteri_onboard_
  toplu.py`'nin kendisi (Docker/PostgreSQL gerektiren tam orkestrasyon)
  bilinçli olarak kapsam dışı — zaten 2026-09-30'da canlı test edilmişti.
  Detay: `model_eval/CLAUDE.md` 2026-10-01 notu. Tüm paket (269 test) geçiyor.
- [ ] 5-10 müşterinin GERÇEK verisiyle uçtan uca hiç denenmedi — 2026-09-30'da
  İKİ MOCK şirketle denendi, gerçek dış ekip verisiyle henüz değil.

## Fatura işleme sözleşmesi — NACE artık onboarding'de (2026-09-29)

`satici_nace_kodlari` artık opsiyonel: onboarding'de `tenant_onboarding.py
--nace` ile kaydediliyor, `/fatura/kontrol-et` boş gelirse kayıtlıya düşüyor
(bkz. `Mcp_mimarisi/CLAUDE.md` 2026-09-29 notu). Teslim paketi ve istek boyutu
limiti (30 MB) güncellemesi tamamlandı — bkz. `teslim/README.md`,
`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`.

- [x] **`nace.txt` formatı `teslim/ONBOARDING-VERI-FORMATI.md`'ye eklendi**
  (2026-10-01) — yeni §5: opsiyonel olduğu, satır başına bir kod kuralı,
  `#` yorum/boş satır davranışı, virgülle ayrılmış kodun TEK geçersiz kod
  sayıldığı uyarısı. Gerçek `_nace_kodlarini_oku()` ile test edilip
  birebir tutarlı olduğu doğrulandı. Bu, önceki NACE-opsiyonel notunun
  ("her istekte göndermenize gerek yok") eksik kalan yarısıydı — dış ekip
  "o zaman NACE'yi nereye/nasıl veriyorum" sorusuna artık cevap bulabiliyor.

## Doğruluk ölçümü — reklam/sunum amaçlı (2026-10-01)

1646 gerçek Akyüzlü faturasıyla ölçüldü: `exact_pair_match_rate = %81,4`
(reklam için seçilen metrik), borç=alacak dengesi %98,96. Özet:
`model_eval/results/dogruluk-olcumu-2026-10-01-ozet.md`.

- [x] **`RESULTS.md`, `RAG_MODEL_COMPARISON.md`, `GLM52_vs_GEMMA4_n500.md`,
  `yeni_faturalar_tdhp.md` referansları temizlendi** (2026-10-01, kullanıcı
  kararı: "referansları kaldır/düzelt, dosya yazma"). Dördü de ne dosya
  sisteminde ne git geçmişinde vardı (`find`/`git log --all` ile
  doğrulandı). İlk taramada sadece `model_eval/CLAUDE.md`'de sanılmıştı,
  gerçekte **kod içinde de** (`core/single.py`, `core/prompting.py`,
  `core/cli.py`, `core/runner.py`, `core/parsing.py`, `core/constants.py`,
  `rag_common.py`, 3 test dosyası) ve 5 belge dosyasında (`project.md` x2,
  `entegrasyon/README.md`, `docs/reference/vector_db.md`,
  `docs/explanation/rag_retrieval.md`) toplam 25+ referans vardı — hepsi
  bulunup ya kaldırıldı ya da gerçek kaynağa (`CLAUDE.md` "Kritik
  gerçekler" bölümü, ilgili fonksiyon docstring'i) yönlendirildi, taşınan
  somut bulgular (rakamlar, eşik değerleri) hiçbiri kaybolmadı. Tek
  istisna: `Mcp_mimarisi/docs/CHANGELOG.md`'deki tarihsel kayıt — o bir
  commit günlüğü, geçmişi değiştirmemek için dokunulmadı.

## Diğer

- [x] **Alt kırılım hiç çözülemediğinde yeni kod önerisi eklendi**
  (2026-10-02, kullanıcı kararı — "mizan bilgisine göre mantıklı, mizanda
  zaten kullanılan bir kodla çakışmayan, YENİ bir alt kırılım kodu
  önersin"). `model_eval/core/single.py::_yeni_alt_kod_oner` — mizanda en
  yaygın kullanılan orta kısımdan (kategori) bir sonraki boş sıra
  numarasını önerir, tüm hesap türlerinde (cari+gider), KDV hesaplarında
  (191/391) oran mevzuata bağlı olduğu için önerilmez. Öneri sadece bir
  bilgidir, mizana yazılmaz; `entry["uyari"]` zaten `approvable=False`
  yaptığı için her zaman insan onayı gerektirir — canlı testte
  `/fatura/onayla`'nın bu kaydı `422` ile reddettiği doğrulandı. Dış ekip
  `records[]` şemasına da `onerilen_yeni_kod` alanı eklendi (geriye dönük
  uyumlu, 6→7 alan).
  **Canlı uçtan uca testte gerçek bir bug bulundu ve düzeltildi:** KDV
  tespiti önceden "alt kırılım isimlerinden biri `%N` içeriyor mu" (`any`)
  sezgisiyle yapılıyordu — tevkifatlı gider kalemleri de (örn. "%18 2/10
  Tevkifatlı Nakliye Gideri") isminde `%N` geçirdiği için gider hesapları
  (730 gibi, 52 alt kırılımdan sadece 2'si/%4'ü) yanlışlıkla KDV sayılıp
  öneri almıyordu. `KDV_HESAP_KODLARI = {"191","391"}` sabit kümesiyle
  düzeltildi. Test: `model_eval/tests/test_single.py::TestYeniAltKodOnerisi`
  (9 test) + `test_disa_aktarim.py` (2 test). Tam paket (280 test) + ruff
  regresyonsuz geçti.
  **Web arayüzü de güncellendi, bu sırada İKİNCİ bir bug bulundu:**
  `entegrasyon/static/index.html`'e "Önerilen Yeni Kod" sütunu eklendi,
  ama `entegrasyon/app.py::KalemTahmini` (Pydantic modeli) alanı hiç
  tanımlamadığı için sütun tarayıcıda hep BOŞ çıktı — Pydantic, modelde
  olmayan alanları coerce sırasında sessizce düşürüyordu; `curl` ile
  sadece `dis_sema.records[]` kontrol edilmişti (o tipsiz `dict` olduğu
  için sorunu yaşamıyordu), `entries[]` hiç kontrol edilmemişti.
  `KalemTahmini`'ye alan eklenip düzeltildi, `git stash` ile düzeltme
  olmadan testin gerçekten kırıldığı kanıtlandı. Test: `entegrasyon/
  tests/test_kalem_tahmini_semasi.py` (3 test). Tarayıcıda (Playwright)
  uçtan uca tekrar test edilip ekran görüntüsüyle kanıtlandı. Örnek test
  XML'i: `ornek-test-faturasi-alt-kirilim-onerisi.xml` (proje kökü).
  Detay: `model_eval/CLAUDE.md` 2026-10-02 notu.
- [x] **Linter (ruff) eklendi, CI'ya bağlandı** (2026-10-01). `ruff.toml`
  (proje kökü) — kasıtlı DAR kural seti (sadece `F`/pyflakes + `E9`): geniş
  kural setleriyle ilk denemede 198+ kozmetik uyarı (stil/import sıralama,
  Türkçe yorumlar yüzünden uzun satırlar) çıktı, gerçek hata değildi, CI'yı
  anlamsız kırardı. Bulunan 8 gerçek sorun (2 kullanılmayan import, 1
  kullanılmayan değişken, 5 gereksiz f-string) düzeltildi — sıfır-hata
  durumdan başlanıyor. `.github/workflows/testler.yml`'e `ruff check`
  adımı eklendi (testlerden önce, hızlı başarısız olsun diye).
  `model_eval/requirements-dev.txt`'e `ruff` eklendi. Tam CI komutu yerel
  olarak simüle edilip doğrulandı, 327 test regresyonsuz geçti.
- [x] **`es_zamanli_sinir.py` semaphore uyarısı belgelendi** (2026-10-01).
  Gerçek durum doğrulandı: `docker/supervisord.conf`'ta her iki servis de
  `--workers` BELİRTMEDEN (tek worker) çalışıyor — risk şu an GERÇEKLEŞMİYOR,
  bu yüzden kod değiştirmek yerine belgelemek seçildi (paylaşılan
  sınırlayıcıya geçmek şu an gereksiz karmaşıklık olurdu). Modülün kendi
  docstring'ine (hem `entegrasyon/es_zamanli_sinir.py` hem ikiz kopyası
  `Mcp_mimarisi/src/efatura_kdv/es_zamanli_sinir.py` — ikiz modül kuralına
  uyularak birebir senkron tutuldu, CI'daki `diff` kontrolü simüle edilip
  doğrulandı) ve `docker/supervisord.conf`'a (worker eklenirse önce o
  modüle bakılması gerektiği) uyarı eklendi. 327 test + linter regresyonsuz
  geçti.
