# Neden doğrulama, TDHP eşlemesinden ÖNCE çalışıyor — ve neden iki faz var

## Soru: neden doğrulama katmanı Hesap Planı Eşleme'den sonra değil önce çalışıyor?

İlk tasarımda (bkz. `PROJECT.md` ilk sürümü, 2026-07-17 öncesi) doğrulama
katmanı Hesap Planı Eşleme (TDHP) modülünün **çıktısını tüketen**, ondan
sonra devreye giren bir katman olarak tanımlanmıştı: önce hesap kodu bulunur,
sonra oranı doğrulanır.

Kullanıcı bunu 2026-07-17'de düzeltti: sıra **tersine** çevrildi. Fatura önce
KDV oranı açısından doğrulanır; oran doğruysa TDHP eşlemesine gider, değilse
TDHP eşlemesine hiç girmez.

**Gerekçe:** Amaç sadece "hatalı oranı yakalamak" değil, hatalı bir faturanın
zaten **muhasebe akışına hiç girmemesini** sağlamak. Sıra "önce eşle, sonra
doğrula" olursa, oranı yanlış bir fatura için gereksiz yere bir TDHP kodu
üretilmiş olur — bu kod sonradan "aslında kullanılamayacak" bir çıktı olarak
atılır. Doğrulamayı öne almak, TDHP eşleme modülünün (dokunulmayan, var olan
sistem) yalnızca zaten doğrulanmış faturalarla çalışmasını garanti eder ve
gereksiz/yanlış hesap kodu üretimini en baştan önler.

## Soru: neden mevzuat MCP'si (offline pipeline + kural deposu) hemen kurulmuyor, iki faza bölünüyor?

`PROJECT.md` §3.6'daki iki katmanlı mevzuat MCP mimarisi (offline izleme &
etiketleme pipeline + sorgu-anı hızlı MCP aracı) hâlâ geçerli bir hedef, ama
kullanıcı 2026-07-17'de kapsamı daralttı: bu ağır altyapı **Faz 2**'ye
ertelendi. **Faz 1**'de sistem sadece elde var olan NACE+KDV Excel referans
tablolarını (`nace_kdv (1).xlsx`, `nace_kod_degisikligi_2026_03_24.xlsx`)
kullanarak kural tabanlı bir kontrol yapıyor: "faturadaki NACE kodu ve beyan
edilen oran, excel'in izin verdiği eşleşmelerden biri mi?"

**Gerekçe (kullanıcının kendi ifadesiyle):** *"biz oran üretmeyeceğiz sadece
elimize gelecek olan faturaların içindeki oranların listedeki oranlarla
karşılaştırılması"* — mevzuat MCP'si gibi bir altyapı olmadan da, sadece
statik bir NACE-oran eşleşmesiyle anlamlı bir ilk doğrulama katmanı kurulabilir
ve bu, kural tabanlı sistemin üzerine kademeli olarak inşa edilebilir bir
temel oluşturur. Büyük bir mimariyi tek seferde kurmak yerine, önce çalışan/
basit bir Faz 1 ile değer üretip, ardından mevzuat MCP'sinin karmaşıklığını
(tarih bazlı sorgu, kural deposu, insan onay kuyruğu) Faz 2'de eklemek.

## Soru: Faz 1'de çok-oranlı bir NACE kodunda (ör. tarım %1/%20) oran listede varsa neden direkt "uygun" deniyor, alt-kategori kontrol edilmiyor mu?

`PROJECT.md` §3.7'nin orijinal tasarımında çok-oranlı NACE kodlarında kalem
metninin LLM ile NACE'ye özel kapalı bir alt-kategori kümesinden birine
atanması planlanmıştı (ör. gayrimenkul 681100'de net alan/ruhsat tarihine
göre %1/%10/%20 ayrımı). Kullanıcı bunu Faz 1 kapsamı dışına aldı: Faz 1'de
kalem metni analizi/LLM sınıflandırması yok, sadece "beyan edilen oran, bu
NACE'nin excel'de dolu olan oran sütunlarından birine denk geliyor mu"
kontrol ediliyor. Oran listede varsa hangi alt-kategori olduğu bilinmese de
`uygun` sayılıyor.

**Gerekçe:** Bu, Faz 1'in kapsamını bilinçli olarak dar tutma kararının
doğal sonucu — alt-kategori ayrımı (net alan, ruhsat tarihi gibi ek veri
gerektiren) zaten Faz 2'nin LLM+MCP altyapısını gerektiriyor. Faz 1'de bunu
zorlamak, ya yanlış bir tahmin riski (golden rule 3'ü ihlal) ya da her
çok-oranlı NACE'yi otomatik olarak insana düşürüp Faz 1'in pratik değerini
azaltmak anlamına gelirdi. Kullanıcı, oran listede olduğu sürece yeterli
kabul edilmesini seçti (2026-07-17).

> ✅ Onaylandı (2026-07-17): Kullanıcı akış sırası tersine çevirme kararını,
> Faz 1/Faz 2 ayrımını ve çok-oranlı NACE'lerde "listede varsa yeterli"
> kuralını onayladı. Uygulama detayı için bkz. `PROJECT.md` §0.1 ve
> `docs/reference/nace-kdv-excel-yapisi.md`.

## Soru: satır bazında NACE tespiti eklenirken (2026-07-20) neden VKN→NACE excel lookup yazılmadı?

İlk tasarımda (PROJECT.md §0.2, ilk sürüm) alt-adım 3'ün "NACE veri kaynağı
(VKN→NACE listesi) kullanıcı tarafından eklenecek" şeklinde bir excel/lookup
dosyası bekleyeceği varsayılmıştı. Kullanıcı bunu 2026-07-20'de netleştirdi:
**gelen faturayla birlikte satıcının NACE kod(ları) da dışarıdan (üst
sistemden) geliyor** — çünkü sistem zaten sadece fatura sahibinin (satıcının)
kestiği faturalarda çalışabiliyor, bu bilgi ayrıca bir excel'den aranmasına
gerek kalmadan üst sistem tarafından sağlanıyor.

**Gerekçe:** Bağımsız bir VKN→NACE lookup dosyası hem veri bakımı (kim
güncelleyecek, ne sıklıkla) hem de tutarlılık riski (üst sistemin bildiği
NACE ile lookup'ın verdiği NACE farklı olabilir) taşırdı. Bunun yerine
`SaticiNaceBilgisi(vkn, nace_kodlari)` dışarıdan parametre olarak alınıyor —
`satir_bazli_kontrol_et()` fonksiyonu başında bu VKN'nin faturanın kendi
satıcı VKN'siyle uyuştuğunu da kontrol ediyor (yanlış satıcıya ait NACE ile
sessizce karşılaştırma yapılmasını önlemek için).

## Soru: çoklu-NACE'li satıcılarda kalem metnine bakılıp LLM ile "hangi NACE'ye ait" tespiti denendi, sonra neden tamamen kaldırıldı?

**İlk deneme (2026-07-20, sabah):** Bir satıcının birden fazla NACE kodu
olduğunda, kalem metninin hangi NACE'ye ait olduğunu bulmak için iki
aşamalı bir yaklaşım kuruldu: önce sayısal eleme (beyan edilen oranın hangi
aday NACE ile tutarlı olduğuna bakmak, `kdv_oran_referans2.xlsx`/`NACE_KDV`
sayfası üzerinden), daraltamazsa LLM ile kapalı-küme seçim (Ollama,
`glm-5.2:cloud` — önce yerel `qwen2.5:0.5b` denendi ama basit bir talimatı
bile takip edemediği görülüp daha güçlü bir uzak model tercih edildi).

**Neden kaldırıldı (aynı gün, kullanıcı kararı):** Kullanıcı bu yaklaşımı
tamamen değiştirdi: *"kalem içeriğine bakmayalım sadece kalemin kdv oranına
bakalım ve bu oranı kullanabilir mi diye nace kodlarındaki yetkilerine
bakalım"*. Yani "hangi kalem hangi NACE'ye ait" sorusu artık hiç sorulmuyor
— bunun yerine satıcının TÜM NACE kodlarının izin verdiği oranlar tek bir
**havuzda** birleştiriliyor, kalemin oranı bu havuzda mı diye bakılıyor.
Kalem metni hiç okunmuyor, LLM tamamen kaldırıldı.

**Gerekçe:** Bu, sistemi hem çok daha basit (LLM/Ollama/SSH tüneli
bağımlılığı yok, tek bir deterministik sayısal karşılaştırma) hem de daha
hızlı (LLM çağrıları 5-70 saniye sürebiliyordu, artık anlık) hale getiriyor.
Trade-off: sistem artık "bu kalem gerçekten hangi NACE'ye ait" sorusuna
cevap vermiyor — sadece "satıcının sahip olduğu NACE'lerden HERHANGİ BİRİ bu
oranı destekliyor mu" diye bakıyor. Bu, golden rule 2'nin ("kalem içeriği
NACE ile çelişirse kalem kazanır") kalem-bazlı ayrımını bilinçli olarak terk
ediyor — kullanıcı bunu Faz 1'in kapsamını daraltma kararı olarak verdi.

> ✅ Onaylandı (2026-07-20): Kullanıcı önce VKN→NACE lookup'ın kaldırılması
> kararını, sonra aynı gün kalem-içeriği/LLM tabanlı eşlemenin tamamen
> kaldırılıp "NACE havuzu" mantığına geçilmesi kararını verdi. Uygulama:
> `src/efatura_kdv/kalem_nace_esleme.py`, bkz. `PROJECT.md` §0.2 alt-adım 3.
