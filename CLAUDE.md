# CLAUDE.md — Çalışan Sistem (e-Fatura KDV Doğrulama + TDHP Tahmini)

Bu dosya, `System/` altında çalışan Claude Code (ve diğer AI ajanları) için
rehberdir. Genel çalışma disiplini (docs güncelleme, hafıza kullanımı,
varsayım yapmama, güvenlik onayı) proje kök dizinindeki
[`../CLAUDE.MD`](../CLAUDE.MD)'de tanımlıdır — **bu dosya onu tekrar etmez**,
yalnızca bu üç bileşenin BİRLİKTE çalışmasına özgü bilgiyi içerir.

Tek bir bileşenin içinde çalışıyorsan onun kendi rehberi daha ayrıntılıdır:
- [`Mcp_mimarisi/CLAUDE.md`](Mcp_mimarisi/CLAUDE.md) — KDV/NACE ön filtreleme
- [`model_eval/CLAUDE.md`](model_eval/CLAUDE.md) — TDHP tahmini + RAG
- `entegrasyon/` — kendi CLAUDE.md'si yok; [`entegrasyon/README.md`](entegrasyon/README.md)

## Sistem nedir?

Üç bileşen + bir orkestrasyon katmanı. Fatura önce KDV mevzuatı açısından
denetlenir, sonra muhasebe kaydı (TDHP kodu + Borç/Alacak + tutar) üretilir.

| Bileşen | Port | Rol |
|---|---|---|
| `Mcp_mimarisi/` | 8000 | KDV/NACE ön filtreleme (kural tabanlı, PostgreSQL) |
| `model_eval/` | — | TDHP tahmini (LLM + RAG), **import ile** çağrılır |
| `entegrasyon/` | 8100 | Orkestrasyon + web arayüzü |

Mimarinin **neden** böyle kurulduğu: [`../mimari.md`](../mimari.md).
Çalıştırma adımları: [`proje-calistirma.md`](proje-calistirma.md).

## Dokümantasyon (Diátaxis)

Üç bileşenin **birlikte** çalışmasına ait belgeler [`docs/`](docs/) altında
(bileşene özel olanlar o bileşenin kendi `docs/`'unda):

| Belge | Tür | İçerik |
|---|---|---|
| [`docs/reference/servisler-ve-portlar.md`](docs/reference/servisler-ve-portlar.md) | reference | Portlar, env değişkenleri, tablolar, endpoint envanteri |
| [`docs/how-to/sistemi-test-etme.md`](docs/how-to/sistemi-test-etme.md) | how-to | Testler, manuel test, uçtan uca doğrulama |
| [`docs/explanation/guvenlik-durumu-2026-07-27.md`](docs/explanation/guvenlik-durumu-2026-07-27.md) | explanation | Güvenlik taraması bulguları + bilinçli kararlar |

Yeni bir belge eklerken türüne göre doğru klasöre koy; `docs/README.md`
indeksini de güncelle.

## Değişmez kurallar

1. **`entegrasyon/` ve `model_eval/` aynı üst dizinde KARDEŞ kalmalı.**
   `entegrasyon/model_eval_yolu.py` bunu varsayarak `sys.path`'e ekleme yapar.
   Klasörleri ayırmak sistemi bozar.
2. **`Mcp_mimarisi` HTTP ile, `model_eval` import ile çağrılır.** Bu asimetri
   kasıtlıdır (gerekçe: mimari.md §2.1). `entegrasyon/` bu ikisinin koduna
   dokunmaz — onlara dışarıdan bağlanan üçüncü bir bileşendir.
   > ⚠️ **2026-08-05 kullanıcı kararıyla gevşetildi:** "İki bileşen birbirinin
   > koduna dokunmaz" ilkesi genel olarak KALKTI — `Mcp_mimarisi` artık
   > `model_eval`'ı doğrudan import edebilir (bkz.
   > `Mcp_mimarisi/scripts/tenant_onboarding.py`, `model_eval_yolu.py`
   > deseniyle `model_eval/core/db.py::_SCHEMA`'yı import ediyor — elle
   > kopyalanan bir SQL şemasının iki projede senkronsuz kalma riskini
   > gidermek için). Yukarıdaki HTTP/import asimetrisi hâlâ **entegrasyon/**
   > katmanı için geçerlidir (o hâlâ ikisine dışarıdan bağlanır) — değişen,
   > `Mcp_mimarisi`↔`model_eval` arasındaki "birbirine dokunmaz" sınırıdır.
3. **Ön filtreleme yalnızca outbox faturalara uygulanır.** inbox'ta
   `Mcp_mimarisi` HİÇ çağrılmaz (gerekçe: başkasının kestiği faturanın mevzuat
   sorumluluğu bizde değil). Yön, XML'den tespit edilir — kullanıcıya sorulmaz.
4. **İki bileşen aynı PostgreSQL'i paylaşır, farklı tabloları kullanır.**
   `nace_oranlari`/`gecmis_fatura_kalemleri` (Mcp_mimarisi) ve
   `model_eval_sonuclar` (model_eval) — birbirinin tablosuna dokunmazlar.
5. **KDV uygunluğu LLM'e sorulmaz.** Mevzuat kontrolü deterministik kalır;
   LLM yalnızca muhasebe kaydı için kullanılır.
6. **`records[]`/`dis_sema` dış sözleşmesi, iç şemadan TÜRETİLİR.** İç tarafta
   `entries[]` + `dc="Borc"/"Alacak"` kalır (model_eval testleri + DB + RAG buna bağlı);
   dönüşüm yalnızca `model_eval/core/disa_aktarim.py`'de yapılır. Dış ekibin
   tek kaynağı (API sözleşmesi + `records[]` şema detayı, 2026-08-05'te
   birleştirildi):
   [`entegrasyon/docs/reference/dis-ekip-api-kullanimi.md`](entegrasyon/docs/reference/dis-ekip-api-kullanimi.md).
   Bu belge dış sözleşmedir — değiştirirsen karşı taraf kırılır, önce sor.
7. **Yeni müşteri (şirket) onboarding'i tek komutla:**
   `scripts/musteri_onboard_toplu.py --onboarding-kok <klasor>` — `Mcp_mimarisi`
   (şema/migration) ve `model_eval` (mizan/RAG) script'lerini sırayla çağırır,
   bu yüzden kök `scripts/`'te durur (tek bir bileşene ait değil). Detay ve
   klasör formatı: `model_eval/CLAUDE.md` (2026-09-29 notu).

   > ✅ **Doğrulandı (2026-09-30) — mock çok-müşavirli uçtan uca test:**
   > "sanki yeni bir müşavir gelmiş gibi" senaryosu gerçek HTTP istekleriyle
   > koşturuldu. İkinci mock şirket (`onboarding_test/6677889900/`,
   > fırın/pastane, NACE `107101`) sıfırdan onboard edildi (mevcut mock
   > `1122334455` — Meşe Kontrakt Mobilya — ilk mükellef olarak kullanıldı).
   > Bir müşavir anahtarı (her iki VKN'ye yetkili) üretilip şunlar doğrulandı,
   > sonra anahtar iptal edildi: `/kayitli-sirketler` sadece yetkili 2 VKN'yi
   > listeledi; auth'suz/geçersiz/iptal anahtar `401`, yetkisiz 3. VKN `403`
   > (kuyruğa girmeden); iki gerçek fatura (`/fatura/isle`, biri inbox biri
   > outbox) uçtan uca işlenip `/fatura/onayla` ile PostgreSQL+RAG'a yazıldı;
   > mizan (27 vs 21 satır), `model_eval_sonuclar` (0 vs 2) ve RAG
   > koleksiyonları (`tdhp_invoices_1122334455` vs `tdhp_invoices_6677889900`)
   > arasında sıfır çapraz kirlenme; audit log'a ham XML/token sızmadı;
   > `dis_sema`/`records[]` çıktısı dış ekip sözleşmesiyle birebir eşleşti.
   > Bu test sırasında bulunan 3 bug zaten kendi bileşenlerinde belgeli:
   > `public.sirket_bilgileri` tablosu eksikliği (`Mcp_mimarisi/CLAUDE.md`
   > 2026-09-29 notu), `docker compose build app` rebuild tuzağı
   > (`docs/how-to/docker-ile-calistirma.md` §2) ve `mizan_excel_yukle.py`
   > sessiz 0-satır okuma bug'ı (`model_eval/CLAUDE.md` 2026-09-30 notu).

> ✅ **Uygulandı** (2026-10-06, kullanıcı kararı): **Çok şirketli zip ile onboarding uç
> noktası** — dış ekip yeni şirketleri artık `POST /musteri/onboard` ile tek zip olarak
> yükler (`entegrasyon/musteri_onboard_api.py`; sözleşme:
> `entegrasyon/docs/reference/dis-ekip-api-kullanimi.md` §9). Asıl kurulum mantığı
> DEĞİŞMEDİ — her şirket için `scripts/musteri_onboard_toplu.py::musteriyi_onboard_et`
> aynen çağrılır. Kullanıcının onayladığı güvenlik kararları: (1) **mevcut şirket
> atlanır, üzerine yazılmaz** (onboarding mizanı `TRUNCATE`'leyip yeniden yazdığı için);
> tek istisna AYNI anahtarın yarım bıraktığı kurulum — **2026-10-16'da bu karar kullanıcı isteğiyle DEĞİŞTİ, aşağıdaki "Kayıtlı şirket güncelleme" notuna bakın**, (2) yalnızca **`onboard_yetkisi`**
> verilmiş anahtarlar kullanabilir (`api_anahtarlari.py`, `auth.py::require_onboard_yetkisi`;
> verme: `api_anahtari_yonet.py onboard-yetkisi`; VKN'siz, yalnızca `olustur --onboard-yetkisi`
> ile "kapsamsız onboard anahtarı" da üretilebilir, 2026-10-06) ve başarılı kurulumda yeni VKN o
> anahtarın kapsamına otomatik eklenir (atlanan/mevcut şirkete kapsam VERİLMEZ), (3) zip güvenli açılır (zip-slip, zip bomb, dosya
> sayısı/boyut, izinli dosya adları) ve **200 MB** sınırı yalnızca bu yol için geçerlidir
> (`security.py`, gövde belleğe alınmaz). İlerleme yüzdesi (2026-10-06): iş ve şirket bazında `yuzde` + şirketin `adim`ı
> (`scripts/musteri_onboard_toplu.py::_musteriyi_onboard_et` her adımda `ilerleme(adim, yuzde)` geri çağrısını çağırır;
> basamaklı: şema 25, mizan 50, eşleştirme 75, RAG 100). İş durumu diskte (`ONBOARD_DATA_DIR`,
> `efatura-onboarding` volume'ü), müşteri ham verisi iş bitince silinir (2026-10-19'dan beri operatör incelemesi için zip'in bir KOPYASI `GELEN_ARSIV_GUN` gün ayrıca arşivlenir, bkz. aşağıdaki "Gelen-istek arşivi" notu). Kod değişikliği
> sonrası `docker compose build app` gerekir; `docker/Dockerfile` artık
> `scripts/musteri_onboard_toplu.py`'yi imaja kopyalıyor. Canlı doğrulama: Docker içinde,
> geçici veritabanıyla (`model_eval_test`) uçtan uca — mock şirket 6 sn'de kuruldu, aynı
> zip ikinci kez `atlandi`; deneme verileri (şema, anahtarlar, ChromaDB koleksiyonu)
> temizlendi, gerçek veritabanına yazılmadı.
>
> ⚠️ **Bu denemede bulunan gerçek bir bug (Docker'da onboarding hiç çalışmıyordu):**
> imaj, alembic'in transitive bağımlılığı olarak SQLAlchemy 2.1.1 kuruyor ve 2.1'de
> öneksiz `postgresql://` adresinin varsayılan sürücüsü psycopg2 değil psycopg (v3) oldu →
> `alembic upgrade head` "No module named 'psycopg'" ile çöküyordu (host venv'inde 2.0.x
> olduğu için 2026-09-30'daki host testlerinde görülmemişti). Düzeltme:
> `Mcp_mimarisi/alembic/env.py` sürücüyü açıkça `postgresql+psycopg2://` yapıyor.

> ✅ **Uygulandı** (2026-10-16, kullanıcı isteği — dış ekip birden fazla faturayı dosya olarak ve paralel göndermek istedi): **toplu fatura işleme** —
> `POST /fatura/toplu-isle` (zip, `satici_vkn` ya da `<vkn>/` klasörleri), `GET /fatura/toplu/{id}` ve `.../sonuclar`
> (`entegrasyon/toplu_fatura_api.py`; sözleşme `entegrasyon/docs/reference/dis-ekip-api-kullanimi.md` §10, dış ekip kılavuzu
> `teslim/FATURA-ISLEME-KILAVUZU.md`). Her fatura **tek-fatura ile aynı iç fonksiyondan ve aynı eşzamanlılık sınırından** geçer
> (`app.py::_toplu_islem`); iş mantığı çoğaltılmadı. Kararlar: yetki kuyruğa girmeden doğrulanır (zip'teki her VKN yetkili+kayıtlı olmalı, aksi halde hiçbir
> şey işlenmez); `onay`/`kur_secimi` tüm faturalara uygulanır (verilmezse ilgili faturalar `onay_bekliyor`/`kur_bekliyor` ile biter); **onaylama otomatik değil**
> (insan kararı) ama toplu tahminler 24 saat (tek istekte 30 dk) onaylanabilir; iş sürerken yeniden başlama kaldığı yerden devam eder; ham XML iş bitince
> silinir (arşiv kopyası hariç — bkz. 2026-10-19 notu), sonuçlar 14 gün saklanır. Paralel tek istekler zaten desteklenir (en çok 2 aynı anda, fazlası **sırada bekler**, reddedilmez). Her HTTP isteği ayrıca
> hata mesajıyla tek JSON satırı loglanır (`entegrasyon/istek_gunlugu.py`) ve Mac'te `izleme/panel.py` ile izlenir. **Gerçek LLM ile uçtan uca denenmedi.**

> ✅ **Uygulandı** (2026-10-16, kullanıcı kararı — "kayıtlı VKN tekrar gelirse işleme al, mevcutla karşılaştır; aynıysa işleme alma, değişen varsa güncelle ve
> eski bilgiyi güncellenme tarihiyle veritabanında logla"): **Kayıtlı şirket güncelleme** — zip'te kayıtlı bir VKN gelirse (artık `atlandi` değil) gelen veri mevcutla
> karşılaştırılır, yalnızca FARK uygulanır (fark yoksa hiçbir şey yazılmaz → `degismedi`; uygulandıysa `guncellendi`). Mantık: `model_eval/core/onboarding_guncelleme.py`
> (NACE / mizan / RAG emsalleri için ayrı fark+uygulama), orkestrasyon `scripts/musteri_onboard_toplu.py::musteriyi_guncelle`, worker `entegrasyon/musteri_onboard_api.py`
> (`Calisan._guncelle`). Eski değer + yeni değer + zaman + iş/anahtar: şirketin kendi şemasındaki `onboarding_guncelleme_gecmisi` tablosu (varsayılan şirkette public);
> mizan satırlarında `updated_at` yenilenir. **Güvenlik güvencesi (eski "atlanır" kararı şu şekilde gevşetildi):** güncelleme YALNIZCA anahtar o VKN adına yetkiliyse yapılır
> (`vkn_izinli_mi`, yükleme anında belirlenip iş kaydındaki `guncelleme_yetkisiz` listesine yazılır); yetkisiz anahtar `atlandi` alır, böylece onboard yetkisi olan BAŞKA bir
> müşavir kapsamında olmayan şirketin verisini değiştiremez. Kurallar: kısmi zip mümkün (yalnız mizan/nace/faturalar+yevmiye; fatura ve yevmiye birlikte); mizan TAM hesap
> planı sayılır (dosyada olmayan hesap silinir, eski değeri geçmişte) AMA dosya boşsa ya da hesapların >%50'si silinecekse mizan UYGULANMAZ (`uyari`); RAG emsalleri yalnızca
> eklenir/güncellenir, ASLA silinmez (`/fatura/onayla` ile gelenler korunur) ve yalnızca (3 haneli kod, yön, ad, karşı taraf) değişince güncellenir (yevmiyede sadece TUTAR
> değişimi emsali değiştirmez); NACE dosyası yoksa dokunulmaz. Parçalar sırayla ve ayrı işlemlerle uygulanır; sonraki parça hata verirse öncekiler (loglanmış olarak) kalır,
> tekrar çalıştırmak güvenlidir. Gerçek PostgreSQL ile test edildi (`model_eval/tests/test_onboarding_guncelleme.py`, `test_musteri_guncelle_orkestrasyon.py`,
> `entegrasyon/tests/test_musteri_onboard.py`). **Gerçek (canlı) LLM/embedding ile uçtan uca henüz denenmedi** — RAG adımı testlerde sahte koleksiyonla çalıştı.

> ✅ **Uygulandı** (2026-10-19, kullanıcı isteği — "bize gelen dosyaları izleme arayüzünden indirip inceleyebileyim, bizim verdiğimiz cevabı da görebileyim"):
> **Gelen-istek arşivi + izleme panelinde "Gelen dosyalar" sekmesi.** Dış ekip "gönderdik" derken elimizde dosya olmadığı için (zip iş bitince siliniyordu, eksik mizan
> olayında orijinali inceleyemedik) `entegrasyon/istek_arsivi.py` yetkili isteklerin kopyasını `ONBOARD_DATA_DIR/arsiv/<request_id>/` altında **sınırlı süre** tutar:
> `gelen.zip` (`/musteri/onboard`, `/fatura/toplu-isle`; geçersiz zip'ler ve reddedilen istekler dahil — hata ayıklamak için), `istek.xml` + `cevap.json`
> (`/fatura/isle`; hata da yazılır), `cevap.json` (zip uçlarında bizim döndüğümüz 202/hata gövdesi) ve `meta.json` (istemci, IP, VKN, durum, hata nedeni, zip içindeki dosya
> adları/boyutları, `is_id`). `GELEN_ARSIV_GUN` (varsayılan **7**, `0` = kapalı), `GELEN_ARSIV_MAX_MB` (varsayılan 2048; aşılınca en eskiler silinir). Bağlama: kayıtlar
> `request_id` ile (log satırlarıyla aynı kimlik), onboarding/toplu iş kayıtlarında `request_id` alanı var. **Arşive API'den erişilemez** — yeni uç nokta eklenmedi; yalnızca
> `izleme/panel.py` SSH üzerinden okur (`/api/arsiv`, `/api/arsiv/detay`, `/api/arsiv/indir`; kimlik hex deseni + sabit dosya adı beyaz listesi, bkz. `izleme/arsiv.py`).
> Panelde istek detayı: dosyayı indir, zip içeriği, bizim cevabımız, başlatılan iş (+ toplu işte fatura başına cevaplar, `sonuclar.jsonl` indirilebilir), o isteğe ait loglar.
> Kararlar/tuzaklar: (1) arşiv hatası isteği ASLA bozmaz (yalnızca uyarı loglanır); (2) yalnızca KİMLİĞİ DOĞRULANMIŞ ve yetkili istekler arşivlenir (anonim/yetkisiz istek diske
> yazdıramaz); (3) `X-Request-ID`'yi istemci verebildiği için var olan bir kaydın üzerine yazılmaz; (4) kimlik/`is_id` doğrulaması `fullmatch` ile — Python'da `re.match("^x$")`
> sondaki `\n`'i de kabul eder ve satır sonu uzak SSH komutuna sızabilirdi (testte yakalandı). **Gizlilik etkisi:** arşiv müşteri verisi (fatura içeriği, karşı taraf adları, mizan) içerir;
> "ham dosyalar iş bitince silinir" ifadesi **dış ekibe verilmiş bir söz** olduğundan, sunucuya dağıtılmadan önce `teslim/*`, `dis-ekip-api-kullanimi.md` §9/§10 ve Orhan'a giden
> rehberlerdeki ifadeler güncellenmeli (kullanıcıya soruldu; dağıtım ve dış belge güncellemesi onay bekliyor). Testler: `entegrasyon/tests/test_istek_arsivi.py` (28),
> `izleme/tests/test_arsiv.py` (51), `entegrasyon/tests/conftest.py` (testler gerçek `/tmp`'yi kirletmesin diye `ONBOARD_DATA_DIR` izole). Nasıl kullanılır:
> [`docs/how-to/gelen-dosyalari-inceleme.md`](docs/how-to/gelen-dosyalari-inceleme.md). **Henüz sunucuya dağıtılmadı; gerçek Docker/SSH ile uçtan uca denenmedi** (panel arayüzü sahte kaynakla
> tarayıcıda görüldü).

> ✅ **Uygulandı** (2026-10-19, kullanıcı kararı — gerçek müşteri 7610928437'nin mizanında yalnızca `150.01.*` (17 satır) kalmıştı, oysa yevmiyesinde 120/320/153/600/191/391/730/760/770
> altında yüzlerce alt hesap adı geçiyordu): **mizan okuyucusu her derinlikteki YAPRAK hesabı alır + atılan satırları sayar.** Kök neden (kod okuyarak + sunucu loglarıyla doğrulandı):
> `model_eval/mizan_excel_yukle.py` yalnızca TAM 3 parçalı kodları (`XXX.YY.ZZZ`) alıyor, `600.01` / `191.01` gibi 2 parçalı hesapları ve ilk sayfadan sonraki sayfaları
> **uyarısız** atıyordu; kurulum özeti yalnızca alınan sayıyı ("17 satır") verdiği için eksik mizan görünmüyordu. Asıl dosya silindiği için "dış ekip yalnızca 150 mi yolladı, biz mi attık"
> **kesin bilinemiyor** (bkz. 2026-10-19 arşiv notu — sonraki gönderimler arşivde görünecek). Yeni kural (`mizan_oku`): ilk parçası 3 haneli ana kod, ≥2 parçalı ve dosyada altında başka hesap
> OLMAYAN her kod alınır (`600.01` alınır; `120.01` altında `120.01.001` varsa üst grup olarak atılır, `320` ana kod satırı atılır). Atılanlar sebebiyle sayılır (`ana_kod`, `ust_grup`,
> `sayi_bicimli`, `gecersiz_kod`, `tekrar`) + okunmayan ek sayfalar + `uyari` listesi → kurulum özetinde `ozet.mizan_okuma`, güncellemede `ozet.mizan.okuma`; panelin "Onboarding işleri"
> sekmesinde görünür (`izleme/static/panel.js::mizanRaporu`). **Davranış HÂLÂ yalnızca İLK sayfayı okur** (ek sayfalar artık uyarıda adıyla görünür). Okuyucuyla birlikte 3 yerdeki
> "3 parçalı" varsayımı da düzeltildi: (1) `core/validation.py::ACCOUNT_CODE_RE` yalnızca `XXX.YY.ZZZZZ` (ortası 2, sonu 5 hane) kabul ediyordu — başka şirketin geçerli `150.01.001` /
> `600.01` kodları `INVALID_ACCOUNT_FORMAT` ile reddedilip fatura onaylanamaz oluyordu (alt hesabın varlığı zaten `SUBACCOUNT_NOT_IN_LEDGER` mizan üyeliğiyle denetlenir); (2)
> `core/single.py::_kdv_oranini_duzelt` düz (2 parçalı) planda aynı TÜR içinde oranı düzeltir (`191.01 %20 İnd.` → `191.02 %10 İnd.`, `%10 İade`'ye atlamaz); (3) `_yeni_alt_kod_oner`
> düz planda `600.10`, sıra genişliğini mevcut kodlardan alır (önceden her zaman 5 hane: `150.01.00016` yerine `150.01.016`). **Mevcut şirketler:** kayıtlı 7610928437'nin düzelmesi için
> dış ekip mizanı yeniden gönderebilir (kısmi zip, yalnız `mizan.xlsx`) — güncelleme akışı eksik hesapları ekler ve geçmişe yazar. Gerçek PostgreSQL ile test edildi
> (`model_eval/tests/test_mizan_excel_yukle.py::TestMizanOku`, `test_musteri_guncelle_orkestrasyon.py::...iki_parcali...`, `test_validation.py`, `test_single.py::TestDuzHesapPlani`; model_eval 329, hiçbiri atlanmadan).
> **Henüz sunucuya dağıtılmadı.** Ek `ozet` alanları (`mizan_okuma`) dış ekibin `GET /musteri/isler/{id}` cevabında görünür (yalnızca ekleme — sözleşmeyi bozmaz); `teslim/*` ve
> `dis-ekip-api-kullanimi.md` güncellenmedi (dış sözleşme, kullanıcıya soruldu).

> ✅ **Düzeltildi** (2026-10-19, canlı test bulgusu — dış ekibin ilk `/fatura/isle` denemeleri): **cari hesapta alt kod artık LLM'e SEÇTİRİLMEZ.** Mizan 17 satırken görünmeyen bir hata, 2090
> müşteri kartı gelince çıktı: karşı taraf mizanda YOKKEN LLM "en yakın isimli BAŞKA müşteriyi" seçti — POÇAN LOJİSTİK → `120.075 Cansarp Nakliye`, FARUK KARAGÖZ → `120.126 FARUK KARAMAN` —
> ve doğrulama bunu yakalayamadı (seçilen kod mizanda VAR), `approvable: true` döndü. Aynı çağrı tekrarlandığında seçim değişiyordu (`120.1241 FEHMİ KARAGÖZ`). Çözüm (`core/single.py`,
> `CARI_HESAPTA_LLM_SECIMI = False`): `CARI_HESAP_KODLARI` yalnızca deterministik ad eşleşmesiyle (`_cari_fuzzy_esles`, %85) bağlanır; eşleşme yoksa kod 3 haneli kalır +
> "karşı taraf mizanda bulunamadı" uyarısı + `onerilen_yeni_kod` + `UNRESOLVED_COUNTERPARTY` (`approvable=False`, insan kontrolü). Cari seçenekleri LLM istemine de gönderilmez (2090 satırlık liste
> istemi şişiriyordu). **2026-07-27 notundaki "eşik altında kalan cari kodlar LLM alt kırılım adımına bırakılır" artık GEÇERLİ DEĞİL.** Bedeli: ağır kısaltılmış bir ad (benzerlik < %85, örn.
> `POÇAN LOJ.HİZ.A.Ş.` 0,82) mizanda olsa da "bulunamadı" sayılır ve insan kontrolüne düşer. Bayrak `True` yapılırsa eski davranış döner — ancak seçilen adın faturadaki ünvanla doğrulanması
> gibi bir koruma eklendikten sonra. **İkinci düzeltme:** LLM bazen alt kodu adıyla yazıyordu (`"391.20: %20 Hessaplanan KDV"`); kod yalnızca saf kodu kabul ettiği için KDV çözülemiyordu.
> `_alt_kod_temizle` baştaki kodu alır (KDV/gider/gelir için; seçim yine mizan listesine karşı doğrulanır, uydurma kod reddedilir; cari'de YAPILMAZ — `": ad"` kabulü yanlış müşteri seçimini de
> kabul etmek olurdu). Testler: `tests/test_single.py::TestCariLlmSecimiKapali` (düzeltme olmadan 6 test düşüyor, doğrulandı).

> ✅ **Uygulandı** (2026-10-19, kullanıcı kararı — "ayırt edici kelime kontrolü" + "belirsizlikte insana bırak"): **cari eşleştirme kuralları gerçek veriyle ölçülerek yeniden yazıldı**
> (`core/single.py::_cari_esle_ayrintili` + `_unvan_*` yardımcıları). Önceki kural yalnızca `SequenceMatcher >= %85` idi; iki sorun ölçüldü: (1) ortak uzun hukuki ek ("ANONİM ŞİRKETİ")
> benzerliği şişirip FARKLI firmaları eşleştiriyordu (`ANADOLU FIRIN A.Ş.` ~ `ANADOLU UN A.Ş.` 0,906; gerçek mizanda `Özdisan Elektronik…` ~ `Demsay Elektronik…` 0,93; mizandaki
> kartların %18'inin (120) / %10'unun (320) başka bir kartla ≥%85 benzeyen komşusu var), (2) mizandaki kart adları çoğunlukla unvanın NOKTALI KISALTILMIŞ/KESİLMİŞ hali
> (`TAHA KALIP MAKİNA OTOM.LTD.ŞTİ.`) ve yalnızca benzerlik bunları kaçırıyordu. Yeni kural: (1) **ayırt edici kelime çifti** — genel/hukuki kelimeler (`UNVAN_GENEL_KELIMELER`) sayılmadan
> kalan kelimelerin iki unvanda da karşılığı olmalı; **noktayla biten** kısaltma önek sayılır (`TAR.`~`TARIM`), noktasız önek sayılmaz (`KOÇ`≠`KOÇAK`); hukuki form ikisinde de varsa aynı
> olmalı (`Ltd.Şti.`≠`A.Ş.`); (2) **kesilmiş kart** — kart adı unvanın başındaki ayırt edici kelimelerin sırayla kesilmiş hali, kartta ≥3 ayırt edici kelime ya da noktalı kısaltma
> (`MEHMET ALİ` kartı `MEHMET ALİ YILMAZ` faturasına bağlanmasın); (3) **ilk parça** — unvan `KİŞİ - TİCARİ AD` gibi devam ediyorsa kart ayıraçtan önceki kısımla birebir uyuşmalı;
> (4) **belirsizlik** — iki farklı kart aynı skoru alırsa (mükerrer kart) kart SEÇİLMEZ: `secim_kaynagi.kaynak="cari_belirsiz"`, uyarı adayları sayar, yeni kart ÖNERİLMEZ (müşteri mizanda var),
> `UNRESOLVED_COUNTERPARTY` → `approvable=False`. **Ölçüm (7610928437, Orhan Bey'in zip'indeki 990 GERÇEK cari satır, yevmiyedeki kart etiket):** doğru bağlanan yalnız-benzerlikte 476 (%48) →
> **826 (%83)**; yanlış bağlanma 17 (%1,7) → 2 (%0,2) ve kalan 2'si gerçek hata değil (biri muhasebecinin kendi kayıt hatası `Murat Güçlü`/`Murat Üçücü`, biri aynı firmanın iki kartı);
> bulunamadı/belirsiz 497 → 162. "Kart yokmuş gibi" (her kart havuzdan çıkarılıp adı kalanlara karşı eşleştirilir): yanlış bağlanma 120'de %14,0 → %0,3, 320'de %9,5 → %0,8 (kalanlar aynı
> firmanın iki kartı). Kendi adıyla eşleşme %97-99, kayıp yok (kalanı mükerrer → belirsiz). Testler: `tests/test_single.py::TestCariEslemeKurallari` (gerçek ad çiftleriyle). **Sınırlar:**
> tek şirketin verisiyle ölçüldü; hâlâ ~%15 müşteri insana kalır (ağır farklı yazım); mizanda 25 çift aynı adlı mükerrer kart var (120) — o müşteriler her zaman belirsiz çıkar, mizan
> temizlenirse düzelir.

## Çalıştırmak için gerekenler (sık atlanan)

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı): `baslat.sh` kaldırıldı,
> tek çalıştırma yolu `docker compose up` (bkz.
> [`docs/how-to/docker-ile-calistirma.md`](docs/how-to/docker-ile-calistirma.md)).

`docker compose up` üç dış bağımlılık ister; biri eksikse ilgili servis
sessizce çalışmaz, hata mesajı ilk bakışta yanıltıcı olabilir:

| Gereksinim | Eksikse ne olur |
|---|---|
| **Docker Desktop açık** | Hiçbir container ayağa kalkmaz |
| **SSH tüneli (11435)** | LLM'e erişilemez → TDHP tahmini boş `entries` döner |
| **Ollama container'ı (11434) + `embeddinggemma` modeli çekilmiş** | RAG embedding çalışmaz |

SSH tünel komutu [`çalıştırma.txt`](çalıştırma.txt) içinde. Tünel parola
istiyor — ajan açamaz, kullanıcı açmalı.

> ⚠️ **Tuzak:** LLM erişimi yoksa `predict_single_invoice` hata fırlatmaz;
> `error` alanı dolu, `entries` boş döner. `records: []` görünce "kodum
> bozuldu" sanmak yerine önce tüneli kontrol et (bu oturumda bir kez yaşandı).

## Test etme

```bash
python3 -m pytest Mcp_mimarisi/test -q          # PostgreSQL varsa 32, yoksa 28 geçer
python3 -m pytest entegrasyon/tests -q          # 138 test (2026-10-19; PostgreSQL yoksa 13'ü skip)
python3 -m pytest izleme/tests -q               # 60 test (izleme paneli; SSH/Docker gerekmez)
(cd model_eval && python3 -m pytest tests -q)   # 329 test (2026-10-19; PostgreSQL yoksa 39'u skip)
```

Üç paket ayrı ayrı çalıştırılır (her biri kendi `sys.path` düzenini kurar).
Ayrıntı ve skip'lerin anlamı: [`docs/how-to/sistemi-test-etme.md`](docs/how-to/sistemi-test-etme.md) §1.

- **CI** (`.github/workflows/testler.yml`, 2026-09-28): `main`'e her push'ta
  ve PR'da üç paketi Python 3.11 + gerçek PostgreSQL ile çalıştırır ve ikiz
  modüllerin (`log_ortak.py`, `es_zamanli_sinir.py`) birebir aynı olduğunu
  denetler. İkiz modüllerden birini değiştirip diğerini unutursan CI kırılır.
- **PostgreSQL kapalıysa** model_eval'de 31, entegrasyon'da 9, Mcp_mimarisi'de
  5 test otomatik `skip` edilir — bu bir hata değildir, CI'da koşarlar.
  (entegrasyon'daki 4'ü 2026-10-01'de `vkn-ekle` için, Mcp_mimarisi'ndeki
  4'ü aynı gün tenant izolasyonu düzeltmesi için eklendi — bkz. yukarıdaki
  API anahtarı ve aşağıdaki şirket izolasyonu notları.)
- Sistem `.venv` kullanıyorsa `pytest` bulunamayabilir; `/usr/bin/python3 -m
  pytest` ile sistem python'unu kullan.
- **Prod DB'sine (`DATABASE_URL`) test verisi yazma** — ayrı bir test
  veritabanı kullan.

**Linter** (`ruff.toml`, 2026-10-01 eklendi, CI'nın bir parçası):

```bash
ruff check Mcp_mimarisi entegrasyon model_eval
```

Kasıtlı DAR kural seti (sadece `F`/pyflakes + `E9`/sözdizimi hatası) —
gerekçe `ruff.toml`'da. Geniş/popüler kural setleriyle (stil, import
sıralaması vb.) ilk denemede 198+ kozmetik uyarı çıktığı için bilerek
genişletilmedi; CI'nın "kırmızı" demesi gerçekten bir mantık hatasına
işaret etmeli. `model_eval/requirements-dev.txt`'te kurulu.

Bir özelliği "tamamlandı" saymadan önce gerçekten çalıştır: `docker compose up`
+ `POST /fatura/isle` ile gerçek bir fatura işle. Kodu okuyup "böyle çalışması
lazım" demek yeterli değildir (kök CLAUDE.MD §3).

## Bilinen güvenlik durumu (2026-07-27 taraması)

Statik güvenlik taraması yapıldı; **düzeltmeler henüz uygulanmadı.** Yeni kod
yazarken bunları kötüleştirmemeye dikkat et:

> **Kapsam notu (2026-07-27, kullanıcı kararı):** Arayüzü **dış ekip yazacak**;
> biz yalnızca backend teslim ediyoruz. Çağrı **sunucu-sunucu** olacağı için
> CORS bilinçli olarak yapılandırılmamıştır (tarayıcıdan çağrı denenirse
> preflight 405 döner). `entegrasyon/static/index.html` bizim kendi manuel
> test aracımızdır — teslim kapsamında değil, ama bizde kalıyor.

**Güvenlik durumu (2026-09-11):** Dış/dahili Bearer token, loopback bind,
DTD/entity ve istek boyutu reddi, TDHP/mizan/tutar doğrulaması, sunucu
tarafı `prediction_id` onayı ve arayüz escape'i uygulanmıştır. Yeni iş
endpoint'leri auth bağımlılığı olmadan eklenmemeli; doğrulamadan geçmeyen
tahmin RAG'a yazılmamalıdır. Tarihsel tarama:
`docs/explanation/guvenlik-durumu-2026-07-27.md`.

> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı — "kur ve şimdi aç") —
> **şirkete bağlı API anahtarları:** 2026-09-11'den beri geçici olarak
> kapalı olan dış auth, tek paylaşılan `EFATURA_API_TOKEN` yerine şirkete
> bağlı anahtarlarla yeniden açıldı. `/fatura/isle`, `/fatura/onayla`,
> `/kayitli-sirketler` `Depends(require_api_key)` ister
> (`entegrasyon/auth.py`). Anahtarlar `public.api_anahtarlari`'da yalnızca
> sha256 özetiyle tutulur (`entegrasyon/api_anahtarlari.py`); her anahtar
> ya tüm şirketler ya da belirli VKN'ler adına yetkilidir. Kurallar:
> yetkisiz `satici_vkn` → `403` (kuyruğa girmeden); başka şirketin
> `prediction_id`'si → `404` (varlığı sızdırılmaz); `/kayitli-sirketler`
> anahtara göre filtrelenir; anahtar deposuna erişilemezse `503`. Audit
> log'a anahtarın etiketi (`istemci`) yazılır. Üretme/iptal:
> `entegrasyon/api_anahtari_yonet.py`. Yerel demo için
> `--tum-sirketler` bir anahtar üretilip test arayüzündeki "API anahtarı"
> alanına girilir. `MCP_INTERNAL_API_TOKEN` (entegrasyon→Mcp iç çağrısı)
> değişmedi. Canlı uçtan uca doğrulandı (gerçek uvicorn + geçici
> PostgreSQL: 401/403/404/iptal/filtreleme). Yeni bir iş endpoint'i
> eklenirse `require_api_key` + (VKN alıyorsa) `vkn_yetkisini_dogrula`
> kullanılmalı.
>
> ✅ **Uygulandı** (2026-10-01, kullanıcı kararı — TODO.md'deki açık soru
> netleşti): Anahtarı **biz üretiriz** (dış ekip değil). Kapsam birimi
> **mali müşavir**dir, tek bir şirket değil: her müşaviri temsil eden
> istemciye bir anahtar üretilir, o müşavirin yönettiği tüm VKN'ler aynı
> anahtara yetkili olur. Müşavirin yeni bir müşterisi onboard edildiğinde
> anahtar iptal/yeniden üretilmez — `api_anahtari_yonet.py vkn-ekle
> --etiket <müşavir> --vkn <yeni-vkn>` (`api_anahtarlari.py::
> anahtar_vkn_ekle`) ile kapsam genişletilir, anahtarın kendi değeri
> DEĞİŞMEZ. Her yeni kurulumda (yeni müşavir ya da müşavirin yeni
> müşterisi) ilgili anahtar dış ekibe ayrı/güvenli bir kanaldan
> iletilir/teyit edilir. Dış sözleşme tarafı:
> `entegrasyon/docs/reference/dis-ekip-api-kullanimi.md` §1. Gerçek
> PostgreSQL ile doğrulandı: `entegrasyon/tests/test_api_anahtarlari_db.py
> ::test_vkn_ekle_*` (4 yeni test, 21/21 entegrasyon paketi geçti).

> ✅ **Uygulandı** (2026-09-11, kullanıcı isteği — canlıya çıkış hazırlığı,
> "önemli yerleri loglamak istiyorum"): Profesyonel/structured loglama
> eklendi. Yeni ortak modül `entegrasyon/log_ortak.py` (birebir kopyası
> `Mcp_mimarisi/src/efatura_kdv/log_ortak.py` — iki proje kod olarak
> birleştirilmediği için, bkz. üstteki değişmez kural #2, mantık ayrı ayrı
> tutulur ama birebir aynı kalmalı):
> - **JSON structured log** (varsayılan, `LOG_FORMAT=text` ile serbest metne
>   dönülebilir) — her satırda `zaman` (tarih dahil, önceden sadece saat
>   vardı), `seviye`, `logger`, `mesaj`, `request_id`.
> - **Request-ID korelasyonu** (`RequestIdMiddleware`, `contextvars` ile) —
>   her HTTP isteğine bir kimlik atanır, o istek boyunca çağrılan TÜM
>   logger'lara (httpx, core.mizan, vb.) otomatik taşınır, cevaba
>   `X-Request-ID` header'ı olarak eklenir. `entegrasyon` → `Mcp_mimarisi`
>   isteklerinde de aynı kimlik `X-Request-ID` header'ıyla taşınır
>   (`mcp_mimarisi_istemcisi.py::_auth_headers`) — iki servisin logları TEK
>   bir request_id ile birlikte aranabilir, gerçek testte doğrulandı.
> - **Log rotasyonu** — `LOG_DIR` verildiğinde `log_ortak.py::loglamayi_kur`
>   `RotatingFileHandler` (10MB x 5 dosya) ekler.
>   > ✅ **Düzeltildi** (2026-09-28, bu notun kendisi bayatlamıştı —
>   > kullanıcı kararıyla `baslat.sh` artık kullanılmıyor, sadece Docker):
>   > önceki metin "host modunda `baslat.sh` `.calistirma`'yı kullanır"
>   > diyordu ama bu YANLIŞTI — `baslat.sh` `LOG_DIR`'ı hiçbir zaman set
>   > ETMEMİŞTİ, bu yüzden `RotatingFileHandler` host modunda hiç
>   > kurulmuyordu; `.calistirma/*.log` dosyaları uygulamanın kendi
>   > rotasyonundan değil, `baslat.sh`'ın shell yönlendirmesinden
>   > (`>> .calistirma/....log`) geliyordu ve gerçekten sınırsız büyüyordu
>   > (bu, "önceden düzeltildi" denilen sorunun ta kendisiydi). Docker
>   > tarafında (`docker/supervisord.conf`) `LOG_DIR` de hiç set edilmez —
>   > bilinçli, uygulama sadece stdout'a JSON basar, container'da rotasyon
>   > sorumluluğu Docker'ın kendi log sürücüsündedir. Ama
>   > `docker-compose.yml`'de de rotasyon tanımlı DEĞİLDİ (varsayılan
>   > `json-file` sürücüsü sınırsız büyür) — `postgres`/`ollama`/`app`
>   > servislerinin üçüne de `logging: {driver: json-file, max-size: 10m,
>   > max-file: "5"}` (`x-log-rotasyonu` anchor'ı ile, `docker/
>   > docker-compose.yml`) eklenerek gerçek bir rotasyon sağlandı —
>   > `restart: unless-stopped` ile sürekli çalışan servislerin disk
>   > doldurmaması için. `baslat.sh`/host modu artık kullanılmadığından bu
>   > yol için ayrıca düzeltme yapılmadı.
> - **Tüm beklenmeyen hatalarda stack trace** — `entegrasyon/app.py`'ye
>   `Mcp_mimarisi/api.py`'deki gibi bir global `@app.exception_handler(Exception)`
>   eklendi (önceden yoktu, FastAPI'nin varsayılan 500'üne bırakılmıştı);
>   `except Exception` bloklarında `exc_info=True` eklendi.
> - **Auth reddi loglanıyor** (`auth.py`, her iki serviste) — token'ın
>   kendisi DEĞİL, sha256 parmak izinin ilk 8 karakteri loglanır (log
>   dosyası sızarsa token sızmasın diye).
> - **Audit log** (`entegrasyon.audit` logger'ı, `_audit_logla()`) — her
>   `/fatura/isle`/`/fatura/onayla` çağrısı için istemci IP + VKN +
>   invoice_id + yön + karar, ayrı JSON satırı olarak. Ham fatura XML'i
>   veya token bu satıra ASLA yazılmaz.
>
> ✅ **Uygulandı** (2026-09-28, kullanıcı kararı — "yerel ağım güvenli, IP
> adreslerini ve dosyaları loglarsak sorun olmaz, log kısmı sağlam olsun"):
> `_audit_logla()`'ya (`entegrasyon/app.py`) `dosya_adi` alanı eklendi —
> önceden bu bilgi SADECE `_test_kaydini_logla`'nın yazdığı Excel
> test-kayıt dosyasında vardı, asıl JSON audit satırında yoktu; "hangi
> dosyanın işlendiği" audit log'dan tek başına cevaplanamıyordu. (Auth
> kapalıyken eklendi; auth aynı gün şirket anahtarlarıyla yeniden açıldı,
> bkz. yukarıdaki not. Loglama bir güvenlik ikamesi değildir — sadece
> sonradan "kim/ne zaman/hangi dosya" sorusuna cevap verir.)
>
> ✅ **Uygulandı** (2026-10-01, kullanıcı isteği — "bu tür hatalı şeyleri
> bizim fark edebilmemiz gerek"): `_audit_logla()`'ya `approvable` (bool)
> ve `red_kodlari` (liste, örn. `["PAYABLE_MISMATCH"]`) alanları eklendi.
> Önceden deterministik doğrulamanın (`model_eval/core/validation.py::
> validate_prediction`) hangi faturayı NEDEN reddettiği audit log'dan tek
> başına çıkarılamıyordu — sadece `asama="tdhp_dogrulama_basarisiz"`
> görünüyordu, hangi kural (`PAYABLE_MISMATCH`, `UNBALANCED` vb.) tetiklendi
> bilinmiyordu. Sadece hata KODU yazılır, mesaj metni YAZILMAZ (tutar/hesap
> kodu gibi detay içerebilir, audit log hassas veri taşımamalı ilkesiyle
> tutarlı). Gerçek, canlı istekle doğrulandı (bilinçli bozulmuş bir fatura
> XML'i gönderilip audit satırında `"approvable": false, "red_kodlari":
> ["PAYABLE_MISMATCH"]` göründüğü teyit edildi). Bu, `PAYABLE_MISMATCH`'in
> gerçek verinin %9,3'ünü reddettiğinin ölçüldüğü oturumda (bkz. `TODO.md`
> "Doğrulama kuralı" bölümü) ortaya çıkan bir ihtiyaçtı — kural doğru
> çalışıyor ama şimdiye kadar bunu TOPLU olarak (zaman içinde, kaç fatura
> hangi kodla reddedildi) izleyecek bir yolumuz yoktu. 5 yeni test:
> `entegrasyon/tests/test_audit_log.py`.
>
> **Otomatik yedekleme** (`scripts/otomatik-yedekleme.sh`, kullanıcı onayıyla
> crontab'a eklendi — her gün 03:00) — PostgreSQL (`pg_dump -F c`) +
> ChromaDB (`docker cp` ile `app` container'ından, tar.gz) `db-yedek/`
> altına tarih damgalı dosya olarak yazılır, 14 günden eski yedekler
> otomatik silinir. Önceden sadece elle alınmış TEK bir dump vardı,
> tekrarlanan/zamanlanmış yedekleme yoktu. Gerçek çalıştırmayla doğrulandı
> (`pg_restore --list` ile dump bütünlüğü teyit edildi).
>
> ✅ **Düzeltildi** (2026-09-28, `baslat.sh` kaldırılınca fark edildi):
> ChromaDB yedeği önceden host'taki `model_eval/vector_db/` dizininden
> alınıyordu — bu, `baslat.sh` (host modu) döneminde biriken bir kopyaydı.
> Sistem artık sadece Docker ile çalıştığından güncel/gerçek RAG verisi
> host dizininde DEĞİL, `docker-compose.yml`'deki `efatura-vector-db` named
> volume'ünde birikiyor (bkz. `docker-ile-calistirma.md` §5.5); host
> dizini yedeklemeye devam etmek sessizce **bayat/yanlış veriyi
> yedeklemek** anlamına geliyordu. Script artık `docker cp` ile
> `app` container'ının içinden (`com.docker.compose.service=app`
> etiketiyle bulunur, container adı proje dizin adına göre değişebildiği
> için isim yerine etiket kullanılır) kopyalıyor.
>
> **Kapsam dışı bırakıldı (kullanıcı kararı, ayrı ele alınabilir):** rate
> limiting, container başlarken otomatik `alembic upgrade head`, Prometheus/
> metrics endpoint'i, CI entegrasyonu — bkz. 2026-09-11 prod-readiness
> denetimi (konuşma geçmişi).

> ✅ **Uygulandı** (2026-09-11, kullanıcı kararı — "işlemleri sıraya alalım,
> hepsini aynı anda işlemeyelim"): Eş zamanlı fatura işleme sınırlaması
> eklendi. Yeni ortak modül `entegrasyon/es_zamanli_sinir.py` (birebir
> kopyası `Mcp_mimarisi/src/efatura_kdv/es_zamanli_sinir.py`) —
> `threading.Semaphore` tabanlı (endpoint'ler sync fonksiyon olduğu için
> `asyncio.Semaphore` DEĞİL). `MAX_ESZAMANLI_ISLEM` env var'ı ile ayarlanır
> (varsayılan 2). `entegrasyon/app.py::fatura_isle` ve
> `Mcp_mimarisi/api.py::fatura_kontrol_et`/`fatura_coklu_kontrol` artık
> `with fatura_isle_sirasi():` bloğu içinde çalışıyor — limiti aşan istekler
> **reddedilmez**, semaphore serbest kalana kadar bekler (rate limiting
> değil, kuyruklama). Gerçek threading testiyle doğrulandı (5 istek, her
> biri 0.5s, limit=2 → toplam ~1.5s, sınırsız olsaydı ~0.5s olurdu).
>
> **Gönderen kullanıcı bilgisi** (aynı kullanıcı isteği — "ilerde kaç fatura
> işlediğini loglarız"): `FaturaIsleIstegi`'ye opsiyonel `gonderen_kullanici`
> alanı eklendi (dış ekibin arayüzü login'den sonra doldurup gönderecek —
> **sistem bu bilgiyi doğrulamaz**, sadece `entegrasyon.audit` logger'ına
> işler). Henüz aktif kullanılmıyor (dış ekip entegrasyonu bekleniyor),
> sadece alan/loglama altyapısı hazır. Şema: `entegrasyon/docs/reference/
> dis-ekip-api-kullanimi.md`.

> ✅ **Uygulandı** (2026-09-28) — **şirket izolasyonu:** `SET search_path
> TO tenant_<vkn>, public` var olmayan şemayı sessizce atladığı için
> onboard edilmemiş bir VKN'nin okuma/yazmaları `public`'e (Akyüzlü'nün
> eski verisine) gidiyordu (geçici bir veritabanında yeniden üretildi).
> Artık `model_eval/core/db.py::get_conn` kayıtsız tenant için
> `TenantKayitliDegilHatasi` fırlatıyor, `/fatura/isle` böyle bir VKN'yi
> LLM'e gitmeden `404` ile reddediyor, `mizan_excel_yukle.py` kayıtsız
> şirkete mizan yazmıyor. Kural tek yerde:
> `core/db.py::tenant_kayitli_mi` (tenant şeması var mı; DEFAULT_OWN_VKN
> her zaman kayıtlı). Yeni kod tenant tablosuna erişirken
> `get_conn(tenant_vkn=...)` kullanmalı, kendi `search_path`'ini
> kurmamalı.
>
> ✅ **Düzeltildi** (2026-10-01) — yukarıdaki notun "kapsam dışı kalan"
> kısmı kapatıldı: `Mcp_mimarisi/src/efatura_kdv/gecmis_kontrol.py::
> _tenant_baglantisi` de artık aynı tek kaynağı
> (`model_eval/core/db.py::tenant_kayitli_mi`) kullanıyor — yeni
> `Mcp_mimarisi/src/efatura_kdv/model_eval_yolu.py` ile model_eval'ı
> import edip (Değişmez kurallar #2'de izin verilen desen) kayıtsız bir
> VKN için `TenantKayitliDegilHatasi` fırlatıyor; `/fatura/gecmis-kontrol`
> ve `/fatura/coklu-kontrol` bunu `api.py`'deki yeni
> `@app.exception_handler(TenantKayitliDegilHatasi)` ile entegrasyon
> tarafıyla tutarlı şekilde `404`'e çeviriyor (önceden sessizce `public`'e
> düşüyordu). Ayrıca `docs/explanation/guvenlik-durumu-2026-07-27.md`'deki
> "`islenmis_faturalar` tenant-scoped değil" bulgusu da bayat çıktı —
> `tenant_onboarding.py`'nin her yeni şirkette çalıştırdığı Alembic
> migration'ları (`9846b14dc658`, `7ec7f9c705a3`) bu tabloyu zaten HER
> tenant şemasında ayrı ayrı oluşturuyor (2026-07-30'da eklendi, bulgudan
> sonra); doc'a düzeltme notu düşüldü. Gerçek PostgreSQL ile doğrulandı:
> `Mcp_mimarisi/test/test_gecmis_kontrol_tenant_db.py` (4 yeni test —
> kayıtlı VKN bağlanabilir, kayıtsız VKN reddedilir, DEFAULT_OWN_VKN her
> zaman kayıtlı, üst seviye sorgu fonksiyonu da korumadan geçer); tüm
> Mcp_mimarisi paketi (32/32, PostgreSQL varken) regresyonsuz geçti.
> **Kapsam dışı bırakılan (ayrı, veri-silme onayı gerektiren TODO maddesi):**
> `public` şemadaki eski Akyüzlü verisinin temizliği — bu düzeltme sadece
> YENİ erişimleri kapatıyor, eski veriyi silmiyor.

> ✅ **Uygulandı** (2026-10-01, kullanıcı kararı) — **port 8000 artık
> `127.0.0.1`'e kısıtlı:** `/fatura/gecmis-kontrol` ve `/fatura/coklu-
> kontrol` (tek bir dahili `MCP_INTERNAL_API_TOKEN`'a bağlı, VKN-bazlı
> yetki kontrolü YOK) daha önce LAN'ın tamamından erişilebilirdi — 2026-
> 09-30'da dış ekibin 8100'e erişebilmesi için 8000 de **yanlışlıkla**
> `0.0.0.0`'a açılmıştı. `entegrasyon` zaten Mcp_mimarisi'ye aynı
> container içinde `http://localhost:8000` ile bağlandığı için
> (`entegrasyon/mcp_mimarisi_istemcisi.py`) bu açıklığın işlevsel bir
> gerekçesi yoktu; dış ekibin hiçbir belgesinde 8000'e dışarıdan erişim
> de yok. `docker/docker-compose.yml`'de 8000 artık Postgres/Ollama gibi
> `127.0.0.1`'e alındı — 8100 dış ekip için `0.0.0.0`'da kalmaya devam
> ediyor. Uygulama seviyesindeki VKN-bazlı yetkilendirme eksikliği
> (TODO.md'de "seçenek A" olarak tartışıldı) kasıtlı olarak YAPILMADI —
> kullanıcı bu ağ-seviyesi daraltmayı yeterli bularak riski kabul etti.
> Gerçek ortamda doğrulandı: `docker compose up -d --no-deps app`
> (ⓘ `--no-deps` şart — düz `up -d`, `ollama` servisi `app`'e
> `depends_on: service_started` ile bağlı olduğu için hiç çekilmemiş
> `ollama` image'ını indirmeye kalkıp gereksiz yere uzun sürüyor) sonrası
> `docker ps` → `127.0.0.1:8000->8000` / `0.0.0.0:8100->8100`, her iki
> servis de `/saglik` ve `/durum` ile sağlıklı. Detay:
> `docs/reference/servisler-ve-portlar.md`,
> `docs/explanation/guvenlik-durumu-2026-07-27.md`.
>
> **Yan bulgu, DÜZELTİLDİ** (2026-10-01): Bu makinede `ollama` container'ı
> (Docker Compose servisi) hiç çalışmıyordu. Kullanıcı host'ta kendi
> Ollama'sını (native, port 11434 — `embeddinggemma` dahil modelleri zaten
> yüklü) çalıştırdı, ama `app` container'ı `OLLAMA_HOST=http://ollama:11434`
> ile Docker Compose'un KENDİ (hiç başlamamış) `ollama` servisini arıyordu
> — `docker exec docker-app-1 curl http://ollama:11434` ile DNS
> çözülemediği doğrulandı. Önce `docker-compose.yml`'i (paylaşılan dosya,
> diğer ortamları da etkiler) değiştirmeyi önerdim, kullanıcı haklı olarak
> önce "dokunma" dedi; sonra **zaten var olan** `docker/
> docker-compose.override.yml`'in (gitignore'da, sadece bu makineye özel,
> 2026-09-11'de hazırlanmış) tam olarak bunu — `OLLAMA_HOST=http://
> host.docker.internal:11434`, `ollama` servisini `profiles: ["disabled"]`
> ile kapatma, `depends_on`'dan çıkarma — yaptığı fark edildi. Asıl sorun
> benim `docker compose -f docker/docker-compose.yml ...` şeklinde repo
> kökünden `-f` ile çalıştırmamdı — Compose, `-f` verildiğinde override
> dosyasını OTOMATİK BİRLEŞTİRMEZ (sadece hiç `-f` verilmeden, dosyaların
> bulunduğu dizinden çalıştırılırsa birleşir). `docker/` dizinine girip
> `docker compose up -d app` ile (bu projenin tüm belgelerinin zaten
> kullandığı doğru biçim) tekrar denendi — `docker compose config` ile
> doğru birleştiği teyit edildi, container hızlıca (ollama'ya hiç
> dokunmadan) yeniden oluşturuldu. Gerçek bir embedding isteği container
> içinden `host.docker.internal:11434/api/embeddings` ile `embeddinggemma`
> modeline atıldı, gerçek bir vektör döndü — RAG embedding artık çalışıyor.
> **Ders:** Bu projede `docker compose` HER ZAMAN `docker/` dizininden (ya
> da hem `docker-compose.yml` hem `docker-compose.override.yml` ile `-f`
> vererek) çalıştırılmalı — tek dosyayla `-f` vermek yerel override'ı
> sessizce devre dışı bırakır.

**Temiz çıkanlar** (bozmayın): SQL injection yok (tüm sorgular parametrize),
unsafe deserialization yok, gömülü API anahtarı yok, `sys.path` manipülasyonu
güvenli.

> ✅ **Uygulandı** (2026-09-25, bu notun kendisi bayatlamıştı — düzeltildi):
> `model_eval/core/single.py::_normalize_entries` hâlâ yalnızca format
> normalizasyonu yapıyor (kod/dc normalize, borç=alacak toplamı) — LLM'in
> verdiği 3 haneli kodu `TDHP_GLOSSARY`'ye karşı doğrulamıyor, tutarı
> faturanın `payable` değeriyle karşılaştırmıyor. AMA bu doğrulama artık
> **ayrı bir modülde var ve pipeline'a bağlı**: `model_eval/core/validation.py
> ::validate_prediction` (kod formatı, `TDHP_GLOSSARY` üyeliği, alt kod
> mizanda var mı, dc geçerliliği, borç=alacak, **ve `payable` ile borç
> toplamının uyuşması** dahil) — bunu `single.py` değil,
> `entegrasyon/model_eval_koprusu.py:182-186`'daki `faturayi_disa_aktar`
> sonrası çağırıyor ve sonucu `sonuc["approvable"]` bayrağına yazıyor. Bu
> bayrak `entegrasyon/app.py:555-559`'da `/fatura/onayla`'yı SUNUCU
> TARAFINDA reddediyor (`approvable=False` ise onaylanamaz; DB sorgusunda da
> `AND approvable = TRUE` şartı var, `model_eval_koprusu.py:302`). Yani
> disiplin ilk aşamada (`single.py`) yok ama sisteme bir bütün olarak
> (`entegrasyon` katmanı üzerinden) bağlı — sadece `model_eval/` tek başına
> incelenirse "hiç çağrılmıyor" gibi görünüyor, asıl çağıran taraf
> `entegrasyon`'dur.
>
> ✅ **Düzeltildi** (2026-09-28, kullanıcı onayıyla) — **tevkifatlı alışta
> yanlış red:** `validate_prediction` borç toplamını sadece `payable`
> ile karşılaştırıyordu; tevkifatlı alışta tam KDV Borç'a yazıldığı için
> borç = KDV dahil toplam (= ödenecek + tevkifat) olur ve doğru kayıtlar
> `PAYABLE_MISMATCH` ile reddediliyordu. Artık borç `payable` VEYA
> `tax_inclusive`'e eşitse geçer (tevkifatsız faturada ikisi aynı —
> kontrol orada gevşemedi). Kanıt: gerçek fatura `HE22026000014163` doğru
> kayıtla artık geçiyor; `Archive2/jsons`'daki 1646 gerçek muhasebeci
> kaydında geçen sayısı 1438 → 1482 (+44, hepsi tevkifatlı); ödenecek
> tutarı hatalı yazılmış fatura hâlâ yakalanıyor. Testler:
> `model_eval/tests/test_validation.py`. **Açık kalan:** düzeltmeden sonra
> bile 162 gerçek kayıt (%9,8) bu kontrolden geçemiyor — çoğu ihracat
> (ISTISNA) faturası, borç ödenecekten %0,3–0,7 fazla (kur farkı olabilir,
> muhasebeciyle netleşmeli), bkz. `TODO.md`.

> Not: Prompt injection yapısal olarak mümkün görünüyor (fatura not alanı
> prompt'a çitlemesiz giriyor) ama canlı LLM ile iki saldırı denendi, ikisi de
> başarısız oldu. "Güvenli" demek için yeterli kanıt yok; savunma modelin
> direncine bırakılmamalı.

## Bu oturumda öğrenilen pratik notlar

- **`arsiv/` klasörü bilinçli bir arşivdir**, çöp değil. Oradan bir şey
  silmeden önce sor.
- **Kök `CLAUDE.MD` ham bir prompt metnidir** (başlığı "Yeni Claude sohbetine
  yapıştırılacak prompt"). İçeriği geçerli, formatı düzensiz — yeniden
  yazılması gerekirse kullanıcıya sor.
- Belgeler arasında **`proje-calistirma.md` güncel olan**; `Mcp_mimarisi`
  altındaki eski kopyalar `arsiv/eski-dokuman/`'a taşındı (bayat yollar
  içeriyordu).
- **Kod değiştirip `docker compose up -d` demek yetmez** — `app` container'ı
  zaten ayaktaysa image rebuild edilmez, kod imaja `COPY` ile gömülü (bind
  mount değil). Değişiklikten sonra `docker compose build app` ŞART, sonra
  `up -d app`. Detay ve 2026-09-30'da yaşanan somut örnek:
  `docs/how-to/docker-ile-calistirma.md` §2.
