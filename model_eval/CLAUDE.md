# CLAUDE.md — TDHP Hesap Kodu Tahmin/Değerlendirme Pipeline'ı

Bu dosya, bu dizinde çalışan Claude Code (ve diğer AI ajanları) için proje
rehberidir. Genel çalışma disiplini (docs güncelleme, hafıza kullanımı,
varsayım yapmama, güvenlik onayı) proje kök dizinindeki
[`../../CLAUDE.md`](../../CLAUDE.md)'de tanımlıdır — bu dosya sadece bu projeye
özgü bilgiyi içerir. (Not: 2026-07-27'de çalışan sistem `System/` klasörüne
taşındığı için kök CLAUDE.MD artık iki üst dizinde.)

## Proje nedir?

Gerçek e-faturaları (UBL-TR XML veya ground-truth'lu JSON) alıp, birden fazla
LLM sağlayıcısının (Ollama/OpenAI/Anthropic/Google/OpenAI-uyumlu) Türkiye
**Tek Düzen Hesap Planı**'na (TDHP) göre doğru 3 haneli hesap kodu + Borç/
Alacak yönünü **kendi bilgisiyle** (hesap planı listesi verilmeden) üretip
üretemediğini ölçen bir değerlendirme/karşılaştırma çatısı. İkinci bir mod
(`--data-format xml`) ham, henüz muhasebeleşmemiş faturalar için ground-truth
olmadan **tahmin** üretir (bkz. `yeni_faturalar_tdhp.md`).

**Akış:** `fatura (XML/JSON)` → `core/parsing.py` (ayrıştırma) →
`core/prompting.py` (prompt inşası, opsiyonel RAG/hint blokları) → LLM
(`core/providers.py`) → `core/scoring.py` (ground-truth varsa skorlama) →
`core/reporting.py`/`core/db.py` (PostgreSQL'e kayıt) → özet tablo
(`core/reporting.print_summary_table`).

## Durum (2026-07-22 itibarıyla)

Değerlendirme pipeline'ı olgun ve genişletilmiş (RAG, self-correct,
tevkifat/iade hint'leri) — bkz. `RESULTS.md` §6, `RAG_MODEL_COMPARISON.md`
için tam bulgu geçmişi. **Aynı gün ayrıca bir mimari denetim geçirdi:**

> ✅ **Uygulandı (2026-07-22):** Sonuç deposu dosya bazlı `.jsonl`'den
> **PostgreSQL**'e taşındı (`core/db.py`, `core/reporting.py` —
> `model_eval_sonuclar` tablosu). ChromaDB client'ı (`rag_common.py`)
> process-ömrü singleton yapıldı. Gerekçe ve detay:
> `docs/mimari-denetim-2026-07-22.md`. Bu, çok kullanıcılı/çok-process
> (gelecekteki HTTP servisi) senaryosunda dosya kilidi/`PersistentClient`
> çakışması riskini gideriyordu.

> ⚠️ Bu bölüm en hızlı bayatlayan bölümdür. Kodla çelişen bir cümle görürsen
> düzelt, ayrı onay bekleme.

> ✅ **Uygulandı (2026-07-23):** İhraç kayıtlı satışlar (istisna kodu
> 701-704) için deterministik bir prompt ipucu eklendi
> (`core/prompting.py::compute_ihrac_kayitli_hint`,
> `build_user_prompt(..., ihrac_kayitli_hint=...)`). Kullanıcı tarafından
> doğrulanmış muhasebe kuralı: bu istisna koduyla kesilen satışlarda
> hesaplanan KDV önce 192 (Diğer KDV) hesabına Borç yazılır, ihracat
> gerçekleştiğinde/tecil-terkin ile aynı tutar 391 (Hesaplanan KDV)
> hesabına Alacak olarak aktarılıp netlenir (satıcı KDV ödemez) — SADECE
> 701-704 için geçerli, diğer istisna kodlarında (ör. doğrudan mal ihracatı,
> kod 301) bu aktarım uygulanmaz. `core/single.py::predict_single_invoice`'da
> varsayılan `True` (entegrasyon'un kullandığı yol). **Dikkat:**
> `tevkifat_hint`/`iade_hint`'in aksine bu kural henüz `RESULTS.md`'ye
> benzer n>1 bir deneyle ölçülmedi — kullanıcı onayına dayanan bir kural
> olarak eklendi, yanlış çıktığı gözlenirse gözden geçirilmeli.

> ✅ **Uygulandı (2026-07-23):** `compute_tevkifat_hint()` artık yöne göre
> (inbox/outbox) FARKLI hesap seti öneriyor — önceki sürüm yönden bağımsız
> TEK bir formül (191 Borç tam KDV / 360 Alacak tevkifat / 320 Alacak net)
> öneriyordu; bu SADECE alışta (inbox) doğruydu, satışta (outbox) yanlıştı
> (391/600/120 yerine 191/360/320 öneriyordu — kod hiç `invoice["direction"]`'a
> bakmıyordu). Kullanıcının sağladığı iki gerçek, muhasebeci tarafından
> onaylanmış kayıtla doğrulandı:
> - **inbox** (nakliye faturası, KDV 20.000/tevkifat 4.000, %20 2/10):
>   191 Borç TAM KDV (20.000), 360 Alacak SADECE tevkifat payı (4.000),
>   320 Alacak net (120.000−4.000=116.000).
> - **outbox** (Nuret Akalı/Demaş faturası, KDV 5.950/tevkifat 1.190, %20 2/10):
>   391 Alacak SADECE NET (tevkifat düşülmüş) KDV (5.950−1.190=4.760) —
>   tevkif edilen kısım satıcıya hiç ulaşmadığı için ayrı bir hesaba
>   YAZILMAZ; 120 Borç net alacağımız tutar (29.750+4.760=34.510).
> Eski, tek-formüllü sürüm bir başka gerçek kayıtla (`AKC2025000003775`)
> karşılaştırılırken tutarsız bulundu (191 iki kez aynı tam tutarla,
> 320'ye tevkifatsız brüt tutar yazılmış) — bu örnek muhtemelen farklı/eksik
> bir yöntemle girilmiş olduğu için kullanıcı kararıyla referans alınmadı,
> yalnızca yukarıdaki iki doğrulanmış kayıt esas alındı. **Alt/muavin hesap
> kırılımı (ör. 191'in net+tevkif payı için iki ayrı alt satıra bölünmesi,
> gerçek kayıtlarda görülüyor) BİLEREK yapılmıyor** — sistem sadece 3 haneli
> ana kod öneriyor (`SYSTEM_PROMPT` kuralıyla tutarlı); bu, ileride
> raporlama/detay ihtiyacı doğarsa ayrı bir görev olarak ele alınacak.
> Detay: `core/prompting.py::compute_tevkifat_hint` docstring'i. Henüz
> `RESULTS.md`'ye benzer n>1 bir deneyle ölçülmedi.

> ✅ **Uygulandı (2026-07-23):** `rag_common.py`'ye yeni
> `upsert_approved_invoice()` fonksiyonu eklendi — `entegrasyon/` katmanının
> kullanıcı onayıyla (`POST /fatura/onayla`) ChromaDB RAG koleksiyonuna
> yazabilmesi için. **Bu, `build_vector_db.py`'nin "sadece Archive2/jsons
> ground-truth'u indeksle" kuralını GENİŞLETİYOR** — kullanıcının arayüzde
> "bu doğru" diye onayladığı bir LLM tahmini de artık bir tür ground-truth
> sayılıp RAG'a ekleniyor (invoice_id ile upsert, idempotent).
> `build_vector_db.py`'nin kendisi DEĞİŞMEDİ, hâlâ sadece Archive2/jsons'u
> tarıyor — bu yeni yazma yolu aynı ChromaDB koleksiyonuna farklı bir
> giriş noktasından (kullanıcı onayı) ekleme yapıyor. Hesap adları
> (`entries_json` içinde) `TDHP_GLOSSARY`'den otomatik dolduruluyor çünkü
> LLM çıktısında (`predict_single_invoice`'in `entries`'i) sadece
> `{account_code, dc, amount}` var, hesap ADI yok — **bu geçici bir
> çözüm, TÜM muhasebecilerin aynı TDHP genel isimlerini kullandığı
> varsayımına dayanıyor. İleride her muhasebeci için ayrı bir kod→isim
> listesi eklenmesi planlanıyor** (kullanıcı notu, 2026-07-23) — o zaman
> `upsert_approved_invoice()` glossary yerine muhasebeciye özel sözlük
> kullanacak şekilde güncellenmeli. Detay:
> `rag_common.py::upsert_approved_invoice` docstring'i,
> `entegrasyon/README.md` "Fatura onaylama" bölümü.
>
> **2026-07-24 güncellemesi — bu ihtiyaç kısmen giderildi:** Yeni
> `core/mizan.py::get_alt_kirilimlar()` + `predict_single_invoice(alt_kirilim=True)`
> (aşağıya bakın) artık şirkete özel bir kod→isim kaynağı (`model_eval/exceller/
> mizan.xlsx`) kullanıyor — ama bu hâlâ TEK bir şirketin (Akyüzlü) mizanı,
> "her muhasebeci için ayrı liste" henüz YOK. İleride birden fazla
> muhasebeci/şirket desteklenirse hem bu mizan hem `upsert_approved_invoice`'daki
> `TDHP_GLOSSARY` kullanımı, şirkete göre parametrik hale getirilmeli.

> ✅ **Uygulandı (2026-07-24):** İki aşamalı hesap kodu tahmini eklendi —
> ana model (mevcut, değişmedi) 3 haneli TDHP kodunu bulur, ardından YENİ
> bir ikinci LLM çağrısı (`core/single.py::_alt_kirilim_uygula`,
> `predict_single_invoice(alt_kirilim=True)`, varsayılan AÇIK) bu kodun
> şirkete özel mizan'daki (`model_eval/exceller/mizan.xlsx`,
> `core/mizan.py::get_alt_kirilimlar()`) alt kırılımından (muavin hesap,
> ör. `191.05.00005`) hangisinin uygun olduğunu seçer. Kullanıcı kararı
> (2026-07-24): "alt kırılımlar her muhasebeci için farklı olabilir, sadece
> ana başlıklar (101, 102 gibi) sabit — model bütün alt kırılımları
> bilebilmeli" — bu yüzden eşik/sınırlama YOK, bir ana kodun TÜM alt
> kırılımları (120 için 102 tane, 320 için 280 tane dahil) LLM'e gösteriliyor,
> ama her ana kod için sadece KENDİ alt kırılımları (diğer kodlarınkiyle
> karışmadan) gösteriliyor — prompt boyutu kontrollü kalıyor.
>
> Güvenlik/doğruluk davranışları: (1) LLM mizanda OLMAYAN bir alt kod
> uydurursa bu seçim YOK SAYILIR, 3 haneli kodda kalınır (bkz.
> `core/prompting.py::ALT_KIRILIM_SYSTEM_PROMPT` — "listede olmayan bir alt
> kod UYDURMA"); (2) bir kod için LLM hiç seçim yapmazsa (yeni müşteri/
> tedarikçi gibi) o kod da 3 haneli kalır; (3) alt kırılım LLM çağrısı
> tamamen başarısız olursa (ağ hatası, parse hatası) ANA tahmin
> ETKİLENMEZ — sessizce 3 haneli koda geri döner, `result["error"]`
> `None` kalır. Test: `tests/test_single.py::TestPredictSingleInvoiceAltKirilim`
> (5 yeni test — başarılı seçim, eksik seçim, halüsinasyon reddi, çağrı
> hatası fallback'i, `alt_kirilim=False` ile devre dışı bırakma).
>
> **Doğrulama (2026-07-24, aynı gün tamamlandı):** Mekanizma hem unit
> testlerle hem iki farklı canlı modelle doğrulandı — küçük bir yerel model
> (`qwen2.5:0.5b`) istenen JSON şemasını üretemedi, kod bunu doğru şekilde
> yakalayıp güvenli şekilde 3 haneli koda döndü (beklenen fallback). Ardından
> gerçek üretim modeliyle (`gemma4:31b-cloud`, SSH tüneli üzerinden) gerçek
> bir tevkifatlı fatura (`AKL2025000000003`) test edildi: ana model `120`/
> `391`/`600` (3 haneli) üretti, alt kırılım adımı bunu `120.01.00303`
> (AVEON GLOBAL SIGORTA — 102 cari hesap seçeneği arasından karşı taraf
> unvanına göre doğru bulundu) ve `391.05.00006` (%20 5/10 Tevkifatlı KDV)
> olarak günceledi — **`391.05.00006` gerçek muhasebe kaydındaki alt
> kırılımla karakter karakter birebir eşleşti**. Toplam süre (2 LLM çağrısı
> dahil): 5.2 saniye. Bu, `RESULTS.md` tarzı bir n>1 deneyle henüz
> ölçülmedi (tek örnek doğrulaması) — daha geniş bir örneklemle
> doğruluk oranı ölçülmesi ileride yapılabilir.

> ✅ **Uygulandı (2026-07-24) — alt kırılım için iki iyileştirme:** 50 gerçek
> faturayla yapılan bir test, faturaların ~%56'sında en az bir kalemin 3
> haneli kaldığını gösterdi. Kök neden analizi İKİ ayrı sebep ortaya koydu
> ve ikisi ayrı ele alındı:
>
> **1. Geçici çağrı hatası → 1 kez otomatik yeniden deneme.** Aynı fatura/
> prompt tekrar çalıştırıldığında başarılı olan çağrıların ilk denemede
> geçici bir nedenle (ağ/API hatası ya da boş/geçersiz `secimler`)
> başarısız olduğu görüldü (LLM'in kendisi `temperature=0` ile tutarlı —
> aynı girdide 4/4 aynı doğru cevap). `_alt_kirilim_uygula` artık ilk deneme
> başarısızsa (err VEYA hiç geçerli seçim yoksa) TEK bir kez daha dener;
> ikincisi de başarısızsa sessizce 3 haneliye döner (sonsuz retry YOK).
> Test: `tests/test_single.py::...test_alt_kirilim_retries_once_and_recovers`.
>
> **2. Cari hesapta karşı taraf mizanda yok → "yeni karşı taraf" uyarısı.**
> 3 haneli kalmanın diğer büyük sebebi: karşı tarafın (müşteri/tedarikçi)
> mizanda gerçekten kayıtlı OLMAMASI (ör. Gümrük Bakanlığı, yeni bir firma).
> Bu durumda model doğru davranıp uydurma yapmıyor (3 haneli bırakıyor), ama
> kullanıcı bunu "model başarısız" sanmasın diye artık bir CARI hesap kodu
> (`CARI_HESAP_KODLARI = {120,320,340,440,159,420}`, `core/single.py`) 3
> haneli kalırsa o entry'ye `uyari` alanı eklenir ("karşı taraf mizanda
> bulunamadı, cari kart açılmamış olabilir"). Gider/stok hesapları (150/730/
> 770) bu uyarıyı ALMAZ — onların 3 haneli kalması farklı bir sebep
> (mizandaki alt kırılımların semantik örtüşmesi, henüz çözülmedi). Mizan
> VKN içermediği için "karşı taraf var mı" kontrolü VKN ile kesin
> yapılamıyor; onun yerine "LLM alt kırılım listesini gördü ve eşleşme
> bulamadı" sinyali kullanılıyor (kullanıcı kararı, 2026-07-24). `uyari`
> alanı `entegrasyon/app.py::KalemTahmini`'ye ve arayüze (`static/index.html`
> TDHP tablosuna "Uyarı" sütunu) kadar taşınıyor. Test:
> `tests/test_single.py::...test_cari_hesap_cozulemezse_uyari_eklenir`.
>
> Bu iki düzeltme sonrası aynı 7 fatura (önceki testte 3 haneli kalanlar)
> tekrar test edildi: retry sayesinde birkaç fatura tamamen çözüldü
> (`AKL2025000000131`, `INM2025000004165`), kalan gerçek "mizanda yok"
> karşı tarafları (Gümrük Bakanlığı, ZTK Makina) doğru şekilde `uyari` ile
> işaretlendi. **Açık kalan sorun:** gider/stok hesaplarının (150/730/770)
> belirsiz semantik eşleşmesi — bu ayrı bir görev olarak bırakıldı.

> ✅ **Uygulandı (2026-07-27) — cari hesap alt kırılımı için deterministik
> fuzzy (isim benzerliği) eşleme:** Cari hesaplarda (`CARI_HESAP_KODLARI` =
> 120/320/340/440/159/420) alt kırılım seçimi artık **LLM'den ÖNCE**
> deterministik bir isim-benzerliği eşleşmesiyle yapılıyor
> (`core/single.py::_cari_fuzzy_esles`, `_unvan_normalize`, eşik
> `CARI_FUZZY_ESIK=0.85`). Faturadaki karşı taraf unvanı
> (`invoice["header"]["account_title"]`) mizandaki alt kırılım isimleriyle
> `difflib.SequenceMatcher` ile karşılaştırılır; benzerlik %85+ ise o alt kod
> LLM'e HİÇ SORULMADAN seçilir. Kök neden (kullanıcı, 2026-07-27): mizandaki
> unvanlar kısaltmalı/farklı yazımlı olabiliyor ("İnş.Turizm San.Ve
> Tic.Ltd.Şti" vs faturadaki açık "İnşaat Turizm Sanayi Ve Ticaret Limited
> Şirketi") — LLM tam-metin eşleşme arayınca bunları kaçırıp 120/320'yi 3
> haneli bırakıyordu. `_unvan_normalize` büyük harfe çevirir, Türkçe
> karakterleri ASCII'ye indirir ve yaygın şirket-eki kısaltmalarını
> (SAN→SANAYI, TIC→TICARET, LTD→LIMITED, STI→SIRKETI, AS→ANONIM …) açar,
> böylece kısaltma farkı benzerliği düşürmez.
>
> Güvenlik/doğruluk (kullanıcı kararı — yüksek eşikli otomatik): (1) eşik
> altında kalan cari kodlar LLM alt kırılım adımına bırakılır; (2) hiçbir
> isim eşiğe ulaşmazsa (karşı taraf mizanda gerçekten yoksa — ör. "Gümrük ve
> Ticaret Bakanlığı", en yüksek benzerlik %55) 3 haneli kalır + mevcut
> "yeni karşı taraf" uyarısı verilir (yanlış eşleme yapılmaz); (3) cari
> OLMAYAN kodlar (191/391/gider) fuzzy'ye HİÇ girmez, doğrudan LLM'e gider
> (onlarda eşleşme oran değil oran/tevkifat bilgisiyle yapılır). Fuzzy'nin
> çözdüğü kodlar LLM prompt'undan çıkarılır (prompt küçülür, gereksiz LLM
> çağrısı azalır). `difflib` standart kütüphanede — ek bağımlılık yok. Ortak
> uygulama `_entry_dicts_uygula`'ya çıkarıldı (hem fuzzy-only hem LLM sonrası
> yol kullanır). Test: `tests/test_single.py::TestCariFuzzyEsleme` (4 yeni —
> birebir, kısaltma farkı, mizanda-yok eşik-altı, boş-girdi güvenliği); ayrıca
> mevcut `TestPredictSingleInvoiceAltKirilim` fixture'ında 320'nin adı, fuzzy'yi
> yanlışlıkla tetiklememesi için bilerek karşı tarafla eşleşmeyen bir isme
> çevrildi. **Henüz `RESULTS.md` tarzı n>1 bir deneyle ölçülmedi** — mantık
> unit testlerle ve gerçek mizanla (birebir/kısaltma/yok senaryoları) doğrulandı,
> geniş örneklemli doğruluk ölçümü ileride yapılabilir. **Not:** Mizan VKN
> içermediği için eşleme İSİMle yapılıyor, VKN'yle değil (bkz. `core/mizan.py`).

> ✅ **Uygulandı (2026-07-27) — KDV alt kırılımında deterministik ORAN
> düzeltmesi (`core/single.py::_kdv_oranini_duzelt`):** LLM'in seçtiği bir KDV
> alt kırılımının (191/391 gibi) ORANI faturadaki gerçek KDV oranıyla
> çelişiyorsa, AYNI TÜR grubu içinde (kodun ilk iki seviyesi, ör. `391.02`)
> faturadaki orana uyan koda çevrilir. Kök neden (kullanıcı, 2026-07-27): bir
> alıştan-iade faturasında (`AKL2026000000190`, KDV %10) LLM `391.02.00020`
> ("%20 Alıştan İade KDV") seçti — tür (Alıştan İade) doğru ama oran YANLIŞ
> (%20, oysa 1.570,88/15.708,75=%10). Kullanıcı kararı: **"sadece oranı düzelt,
> türü LLM seçsin"** — tür (İndirilecek/Alıştan İade/Hesaplanan/Tevkifatlı/
> İthal/İhraç…) LLM'in seçimi olarak KORUNUR, yalnızca aynı tür içinde yanlış
> oran deterministik olarak faturadan gelen oranla değiştirilir. Bu, **Değişmez
> Kural 1** ile tutarlı (oran LLM'in serbest tahmininden değil faturadan gelir).
> Oran faturadan `_fatura_kdv_oranlari()` ile (taxes[].percent), alt kod
> adından `_kdv_orani_isimden()` regex'iyle (`%N`) alınır. Güvenlik: (1) seçilen
> kod KDV oran kodu değilse (isimde %N yoksa — gider/cari) dokunulmaz; (2) oran
> zaten faturayla uyumluysa dokunulmaz; (3) aynı grupta faturanın oranına uyan
> kod yoksa seçim OLDUĞU GİBİ bırakılır (yanlış düzeltme yapılmaz). Fuzzy gibi
> ek bağımlılık yok. Test: `tests/test_single.py::TestKdvOraniDuzelt` (6 yeni —
> bug senaryosu, doğru-oran-değişmez, tür-korunur, grupta-oran-yok, KDV-dışı-kod,
> oran-bilinmiyor). **Henüz n>1 geniş örneklemle ölçülmedi** (tek gerçek fatura +
> unit testlerle doğrulandı).

> ✅ **Uygulandı (2026-07-27) — ihracat faturalarında karşı taraf unvanı
> düzeltmesi (`core/parsing.py`):** İhracat faturalarında
> `cac:AccountingCustomerParty` gerçek müşteriyi DEĞİL gümrük/aracı tarafını
> ("Gümrük ve Ticaret Bakanlığı") taşır; gerçek yurt dışı alıcı
> `cac:BuyerCustomerParty`'de bulunur. Parser eskiden yalnızca
> `AccountingCustomerParty`'yi okuduğu için **eldeki 1933 faturanın 112'sinde
> (hepsi ihracat)** karşı tarafı yanlış ("Gümrük Bakanlığı") sanıyordu —
> böylece mizanda KAYITLI olan gerçek müşteriyi (ör. `R.C.JONES (LIFTING)
> LTD.`=120.03.00043, `FORJAS IRIZAR S.L.`=120.03.00010, HEUER HEBETECHNIK…)
> alt kırılım adımı hiçbir zaman bulamıyordu (kullanıcı bunu "sistem alt
> kırılımı bulamıyor" olarak fark etti). Düzeltme (`_party_unvani` yardımcısı):
> outbox faturada `BuyerCustomerParty` varsa unvan ÖNCE oradan alınır, yoksa
> yöne göre `counterparty_path`'ten (mevcut davranış). Her blokta önce
> `cac:PartyLegalEntity/cbc:RegistrationName` (resmi unvan), o yoksa
> `cac:PartyName/cbc:Name` denenir. **Regresyon:** BuyerCustomerParty'si
> olmayan yurt içi faturalarda (200 örnek test edildi) davranış DEĞİŞMEDİ;
> tüm paket 178 test geçti. Bu düzeltmeyle birlikte alt kırılım fuzzy
> eşlemesi (yukarıdaki not) ihracat müşterilerini de yakalıyor — R.C.JONES
> canlı testte doğru okunup 120.03.00043'e %98 oranla eşleşti.

> ✅ **Uygulandı (2026-07-27) — mizan güncellendi (mizan_5):** Alt kırılım
> tahmininin kaynağı olan şirket mizanı (`model_eval/exceller/mizan.xlsx`,
> `core/mizan.py::DEFAULT_MIZAN_PATH` üzerinden `get_alt_kirilimlar()`'ın
> okuduğu dosya) güncellendi — kullanıcının sağladığı en güncel sürüm
> (`Archive2/mizan_5.xlsx`) üzerine kopyalandı (kullanıcı kararı: yedeksiz;
> eski hâli zaten `Archive2/mizan.xlsx` = aynı MD5 olarak duruyor). Aynı
> şirket (Akyüzlü), aynı dosya yapısı (sheet `MİZAN`, başlık satır 6, veri
> satır 7'den, A=HESAP KODU / B=HESAP ADI) — yani `mizan.py` parse mantığı
> değişmeden çalışıyor, `get_alt_kirilimlar()` ile doğrulandı. Etki: alt
> kırılım havuzu 81→96 ana kod, 1207→2769 alt kod büyüdü (ör. cari 120:
> 102→390, 320: 280→993; tevkifatlı KDV 391: 6→22). Bu, yukarıdaki
> "karşı taraf mizanda yok → 3 haneli kalıyor + `uyari`" sorununu doğrudan
> AZALTIR (artık daha çok cari kart tanınıyor); tam etki `RESULTS.md` tarzı
> n>1 bir deneyle henüz ölçülmedi. **Not:** Hâlâ TEK şirketin mizanı,
> "her muhasebeci için ayrı liste" ihtiyacı (yukarıda) açık kalmaya devam
> ediyor.

> ✅ **Uygulandı (2026-07-27) — dış ekip kayıt şeması (`records[]`):** Diğer
> ekibin beklediği JSON şeması için yeni bir dışa aktarım katmanı eklendi
> (`core/disa_aktarim.py::kayitlari_disa_aktar`). İç şema (`entries[]`,
> `dc="Borc"/"Alacak"`) **DEĞİŞMEDİ** — 198 test, ChromaDB RAG kayıtları ve
> `model_eval_sonuclar` tablosu ona bağlı; dönüşüm tek yönlü ve yalnızca
> dışa aktarımda yapılıyor (kullanıcı kararı: "sadece dış şemada
> BORÇ/ALACAK"). Dış şema 6 alan taşır: `account_code`, `account_code_type`
> (`C`=cari/`G`=diğer, mevcut `CARI_HESAP_KODLARI`'ndan türetilir — paralel
> liste tutulmaz), `account_description` (mizandaki HESAP ADI),
> `account_code_reason`, `amount`, `debit_credit`.
>
> **Gerekçe (`account_code_reason`) DETERMİNİSTİK üretilir, LLM'e SORULMAZ**
> (kullanıcı kararı, 2026-07-27): kodun nereden geldiğini zaten biliyoruz.
> Bunu taşımak için `_alt_kirilim_uygula` artık her çözülen kod için bir iz
> tutuyor (`kod_kaynagi`: `fuzzy` + benzerlik oranı / `llm` + oran düzeltildi
> mi) ve `_entry_dicts_uygula` bunu entry'ye `secim_kaynagi` olarak, mizandaki
> hesap adını da `account_description` olarak ekliyor. LLM'e "neden bu kodu
> seçtin" diye sormak *post-hoc rasyonalizasyon* riski taşır — model kodu bir
> sebeple seçip başka bir sebep yazabilir; deterministik gerekçe gerçekten
> olan işlemi anlatır ve ek LLM çağrısı maliyeti yoktur.
>
> `_entry_dicts_uygula` imzası genişledi (`alt_kirilimlar_tumu`, `kod_kaynagi`
> — ikisi de opsiyonel, verilmezse eski davranış). Test:
> `tests/test_disa_aktarim.py` (14 yeni test — tür türetme, dc çevrimi, her
> gerekçe dalı, şema uyumu). Tam sözleşme (2026-08-05'te dış ekip API
> belgesiyle birleştirildi):
> [`../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md) §3.1.
>
> **Açık sınır:** `emsal_sayisi` köprüden geçirilmiyor (varsayılan 0), çünkü
> RAG'ın kaç emsal kullandığı `predict_single_invoice` çıktısında dönmüyor —
> "N geçmiş benzer faturada…" gerekçesi bu yüzden henüz üretilmiyor.

> ✅ **Uygulandı (2026-07-29) — tek fatura akışında tekrarlı XML parse
> temizliği:** `predict_single_invoice()`'a opsiyonel `parsed_invoice`
> parametresi eklendi (`core/single.py:180-201, 254-256`). Kök neden: bir
> `/fatura/isle` isteğinde aynı `fatura_xml`/`own_vkn` **üç kez** ayrı ayrı
> `parse_invoice_xml_string()` ile parse ediliyordu — `entegrasyon/
> yon_tespiti.py` (yön tespiti için), `predict_single_invoice` (LLM prompt'u
> için), ve `entegrasyon/model_eval_koprusu.py::tdhp_tahmini_yap` (dış şema/
> `dis_sema` üretimi için). Parse ucuz olduğu için performans etkisi küçüktü
> ama üç ayrı parse noktası kod tekrarıydı.
>
> `parsed_invoice=None` (varsayılan) verilirse davranış **DEĞİŞMEDİ** —
> fonksiyon eskisi gibi kendi parse eder; `tests/test_single.py`'deki 29
> çağrı hiçbiri güncellenmedi, hepsi eski imzayla geçmeye devam ediyor
> (doğrulandı: `pytest tests/test_single.py` 29/29 yeşil). `entegrasyon/`
> tarafında `app.py::fatura_isle()` artık XML'i `yon_tespiti.py::
> faturayi_parse_et_ve_yonu_dogrula()` ile **bir kez** parse edip sonucu
> hem `tdhp_tahmini_yap(parsed_invoice=...)`'a geçiriyor. `fatura_yonunu_
> tespit_et()` (eski fonksiyon adı) imzası/davranışı değişmeden bu yeni
> fonksiyonun üzerine kuruldu — geriye dönük uyumlu.
>
> `convert_to_try=True` durumunda `parsed_invoice` HAM (henüz TL'ye
> çevrilmemiş) hâliyle geçirilir — hem `predict_single_invoice` hem dış şema
> üretimi kendi içinde ayrı ayrı `convert_invoice_to_try()` çağırır
> (fonksiyon girdiyi değiştirmeden yeni bir sözlük döndürüyor, bkz.
> `core/parsing.py:294-298` docstring'i), bu yüzden iki taraf da doğru
> (TL'ye çevrilmiş) invoice'ı kullanır, orijinal `parsed_invoice` bozulmaz.

> ✅ **Uygulandı (2026-07-29) — OpenAI/Anthropic/Google/openai-compat
> desteği kaldırıldı:** Kullanıcı kararı: "biz sadece Ollama kullanacağız".
> `core/providers.py` yeniden yazıldı — `call_openai`, `call_openai_style`,
> `call_openai_compat`, `call_anthropic`, `call_google` fonksiyonları ve
> `parse_model_spec()`'in bulut-sağlayıcı/openai-compat ayrıştırma mantığı
> tamamen kaldırıldı, `call_model()` artık sadece `provider == "ollama"`
> dalını içeriyor (başka bir provider gelirse `ValueError`). `KNOWN_PROVIDERS`
> artık `{"ollama"}`. Bu, gerçek üretim davranışını **değiştirmedi** —
> `entegrasyon/model_eval_koprusu.py::tdhp_tahmini_yap()` zaten `model`
> parametresini hiç override etmiyordu, varsayılan (`DEFAULT_MODEL_SPEC_STR
> = "ollama:gemma4:31b-cloud"`) hep Ollama'ydı. Çoklu-sağlayıcı desteği
> sadece `model_eval`'in kendi karşılaştırma/değerlendirme aracı
> (`evaluate_models.py --models openai:...`) için vardı, o kullanım kalktı.
>
> `cli.py`'deki `--models` yardım metni ve `evaluate_models.py`'nin docstring
> örnekleri güncellendi — artık sadece Ollama sözdizimini gösteriyor.
> `tests/test_providers.py`'den 10 test (OpenAI/Anthropic/Google'a özel)
> ve `tests/test_single.py`'den `test_self_correct_skipped_for_non_ollama_provider`
> kaldırıldı — bunlar artık hiç gerçekleşemeyecek bir senaryoyu (`provider !=
> "ollama"`) test ediyordu. `tests/test_reporting.py`'deki `"openai:gpt-4.1"`
> gibi string'lere DOKUNULMADI — onlar `result_label()`'ın herhangi bir
> metni etiket olarak kabul ettiğini test ediyor, gerçek provider çağrısı
> yapmıyorlar. Doğrulandı: `pytest tests/` tüm suite yeşil (191 passed).

## Mimari (özet)

- **`core/parsing.py`** — `parse_invoice()` (JSON+ground-truth),
  `parse_invoice_xml()` (ham UBL XML, ground-truth YOK, inbox/outbox yön
  tespiti `--own-vkn` ile), sayısal alan normalizasyonu.
- **`core/prompting.py`** — `build_user_prompt()`, opsiyonel
  `build_glossary_system_prompt()` (TDHP kod açıklamaları — varsayılan
  KAPALI, bkz. "Değişmez kurallar"), `compute_tevkifat_hint()`,
  `compute_iade_hint()`.
- **`core/providers.py`** — `parse_model_spec()` + `call_model()` dispatch
  (ollama/openai/anthropic/google/openai-compat), self-correct mesaj inşası.
- **`core/runner.py`** — `run_model()`: tek model spec'i için fatura kümesini
  eş zamanlı işler (`--concurrency`), resume (`load_done_ids`), RAG
  entegrasyonu, self-correct tetikleyicileri (`balance` / `precedent_mismatch`
  nedenleri).
- **`core/reporting.py` + `core/db.py`** — sonuç kaydı/okuma/özet, PostgreSQL
  üzerinden (`DATABASE_URL` env var, `model_eval_sonuclar` tablosu).
- **`core/scoring.py`** — `parse_model_output()`, `score_entries()` (F1,
  exact-match, borç=alacak dengesi).
- **`core/single.py`** — `predict_single_invoice()`: dış katmanların
  (`entegrasyon/` klasörü, ayrı bir proje) import edeceği, TEK fatura için
  senkron, DB'ye dokunmayan tahmin fonksiyonu. `run_model()`'in aksine
  toplu/es zamanlı değildir, ham XML string alır (dosya değil). Detay:
  `PROJECT.md` §4.1.
- **`rag_common.py`** — ChromaDB tabanlı few-shot retrieval (`get_collection()`
  process-ömrü singleton, `retrieve_similar()`, `strongest_precedent()`).
- **`core/cli.py`** / **`evaluate_models.py`** — argparse + `main()`;
  `evaluate_models.py` sadece geriye dönük uyumluluk için ince bir giriş
  noktası.
- **`build_vector_db.py`** — Archive2/jsons'u ChromaDB'ye indeksler (RAG
  için önkoşul, idempotent upsert).
- **`generate_report.py`** — sonuç kayıtlarından okunaklı `.md` raporu üretir
  (`yeni_faturalar_tdhp*.md` bu şekilde üretildi).

## Kritik gerçekler (deney bulgularına dayalı — varsayım yapma)

- **Referanssız en iyi model `gemma4:31b-cloud`** (pair_F1≈0.835). TDHP kod
  glossary'sini system prompt'a eklemek (`--with-glossary`) 4/6 modelde
  işe yaramadı/kötüleşti — sorun modelin bilgi eksikliği değil, doğru kodu
  **seçme** ayrımıdır. Bkz. `RESULTS.md`.
- **En büyük tekil iyileştirme: RAG** (şirketin kendi geçmiş faturalarından
  few-shot örnek) — 0.835→0.935; `--rag --self-correct` (precedent-mismatch
  düzeltmesi) ile 0.961 (n=100). n=500 doğrulamada tüm iyileştirmeler
  birlikte (`--rag --self-correct --iade-hint --tevkifat-hint`)
  0.817→0.956'ya çıktı.
- **`--tevkifat-hint` tek başına** tevkifatlı faturalarda balanced oranını
  9.5%→95.1%'e çıkardı — modelin zayıflığı aritmetik, kavramsal değil.
- **`--iade-hint`** + direction_text düzeltmesiyle IADE doğruluğu
  %0→%70 (n=20) — IADE faturalarında "biz satıcıyız/alıcıyız" çerçevesi
  ters kayıt yönüyle çelişiyordu, kök neden düzeltildi.
- **Model bazında context duyarlılığı zıt yönlü:** `gemma4` context
  arttıkça kötüleşiyor, `glm-5.2` context arttıkça iyileşiyor
  (0.624→0.814) — "daha fazla bağlam her zaman daha iyi" varsayımı yanlış.
- **Alış faturaları (inbox), satıştan (outbox) 2 kattan fazla hatalı**
  (%16.2 vs %7.8) — hangi gider/stok hesabının kullanılacağı belirsizliği.

## Değişmez kurallar

1. **Modele hesap planı listesi verilmez (varsayılan mod).** Amaç modelin
   TDHP'yi ne kadar "bildiğini" ölçmek — `--with-glossary` bu ilkenin
   BİLİNÇLİ istisnasıdır, ayrı bir deney kolu olarak var olur, varsayılan
   akışı asla ezmez/değiştirmez.
2. **Ground-truth olmayan veri (`--data-format xml`) asla "doğru/yanlış"
   olarak sunulmaz.** Bu mod TAHMİN üretir; `fp_pairs`/`exact_pair_match`
   gibi karşılaştırma alanları XML modunda hesaplanmaz/yazılmaz (yanıltıcı
   olur) — bkz. `core/runner.py` `has_ground_truth` dallanması.
3. **Deney kolları birbirini asla ezmez.** Her bayrak kombinasyonu
   (`result_label()`) ayrı bir `file_label` altında saklanır — yeni bir
   bayrak eklerken mevcut sonuçların üzerine yazılmadığından emin ol.
4. **Sonuç deposu PostgreSQL'dedir, dosya değil (2026-07-22'den itibaren).**
   Yeni kod jsonl dosyasına doğrudan yazmaya/okumaya dönmemeli —
   `core/reporting.py`'deki `append_result`/`load_done_ids`/
   `summarize_model` üzerinden gidilmeli.

## Proje kapsamı ve çalışma düzeni

- **Ne inşa ediyoruz** (mimari kararlar, deney sonuçları, faz durumu):
  [`project.md`](project.md)
- **Mcp_mimarisi ile entegrasyon sözleşmesi** (ayrı proje, HTTP üzerinden,
  henüz kod yazılmadı): [`entegrasyon.md`](entegrasyon.md)
- **Son mimari denetim/PostgreSQL geçişi gerekçesi:**
  [`docs/mimari-denetim-2026-07-22.md`](docs/mimari-denetim-2026-07-22.md)

## Çalışma tarzı

- **Türkçe yaz:** commit mesajı, dokümantasyon, kod içi yorum — hepsi Türkçe
  (üst dizin CLAUDE.md ile tutarlı).
- **Kritik bir değişiklik yaptıktan sonra ilgili belgeyi güncelle** — aynı
  görevin parçası, ayrı bir adım değil. Hangi belge güncellenir Diátaxis
  türüne göre değişir (bkz. aşağı).
- **Testler PostgreSQL gerektirir** (`test_reporting.py`, `test_runner.py`).
  `TEST_DATABASE_URL` env var'ına bağlanılamıyorsa bu testler otomatik
  `skip` edilir (`tests/conftest.py`, `requires_postgres` marker'ı) — CI/
  geliştirici ortamında Postgres yoksa suite yine de çalışır, sadece bu
  testler atlanır. Prod DB'sine (`DATABASE_URL`) asla test verisi yazma;
  ayrı bir test veritabanı kullan.

## Dökümantasyon (Diátaxis)

- 📖 `docs/` — `explanation` (mimari denetim notu) türünde belgeler var.
  Dış ekip `records[]` sözleşmesi artık burada değil, 2026-08-05'te
  `../entegrasyon/docs/reference/dis-ekip-api-kullanimi.md` (§3.1) ile
  birleştirildi — dış ekibe teslim edilen tek dosya orası. Yeni bir
  "nasıl yapılır" ihtiyacı doğarsa `docs/how-to/` oluşturulabilir.
- `RESULTS.md`, `RAG_MODEL_COMPARISON.md`, `GLM52_vs_GEMMA4_n500.md` —
  deney bulguları (bunlar Diátaxis'in dışında, projenin kendi bulgu
  günlüğü formatı).
