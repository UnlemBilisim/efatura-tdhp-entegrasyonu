# Yapılacaklar

Karara bağlanmamış ya da ertelenmiş işler. Bir madde tamamlanınca buradan
silinir, ilgili belgeye `✅ Uygulandı` notu düşülür.

## Açık soru — karar bekliyor

- [ ] **Dış ekibe sözleşme değişikliğini bildir** (2026-09-28): `404`
  (onboard edilmemiş VKN), `403` (anahtarın VKN yetkisi yok), `EFATURA_API_TOKEN`
  yerine şirkete bağlı API anahtarı. Belge:
  `entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`.

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

**Hâlâ eksik/kararsız:**
- **Jev:** `.env`'e `TYPESAFE_API_KEY` eklenmesi bekleniyor — henüz teyit
  gelmedi, test edilmedi. Veri kapsamı konuşuldu ama netleşmedi: sadece
  unvan + aday kart adları + para birimi gitmeli, tutar/VKN gitmemeli
  (bu bir dış bulut servisi — KVKK açısından netleşmesi gerek).
- Üçü de hazır olunca 144 zor vakayı üçüne de koşturup karşılaştırma HENÜZ
  yapılmadı.
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
