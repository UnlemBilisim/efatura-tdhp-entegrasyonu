# Mevzuat MCP mimarisi neden bu şekilde

## Soru: neden tek katmanlı, canlı bir mevzuat sorgu aracı değil?

İlk akla gelen tasarım, fatura işlenirken doğrudan mevzuat.gov.tr/GİB'e canlı
sorgu atan tek bir MCP tool'u olurdu: LLM ham mevzuat metnini o anda okur,
oranı yorumlar, karar verir. Bu proje bunun yerine iki katmanlı bir tasarım
seçti (bkz. [`PROJECT.md`](../../PROJECT.md) §3.6): offline bir **İzleme &
Etiketleme Pipeline** + sorgu-anı **Mevzuat MCP Aracı**. Sebepleri:

1. **Latency/maliyet.** Sistem günde 1K-10K fatura kalemi hacminde
   çalışacak (kullanıcı onayı, 2026-07-17). Her kalem için canlı bir mevzuat
   taraması hem yavaş hem maliyetli olur; önceden etiketlenmiş bir depoyu
   tarih+kapsam filtresiyle sorgulamak sabit ve düşük gecikmeli.

2. **Değişmez Kural 1'in korunması.** KDV oranı/tevkifat/istisna hiçbir zaman
   bir LLM'in o anki serbest yorumundan gelmemeli — statik bir tablo veya bir
   modelin "hatırladığı" oran, yürürlükten kalkmış bir kuralın sessizce
   uygulanması riskini taşır. Oran her zaman yapılandırılmış, kaynağı belli
   bir alandan okunmalı (bkz. `CLAUDE.md`, Değişmez Kural 1).

## Soru: yargi-mcp incelemesi bu kararı nasıl etkiledi?

Bu mimariyi tasarlamadan önce `yargi-mcp` projesi (Türk yargı kararlarına
erişim sağlayan bir MCP sunucusu) incelendi. Çıkan en önemli ders: **14 farklı
resmi kurumun (Yargıtay, Danıştay, AYM, KİK, Rekabet Kurumu, Sayıştay, KVKK,
BDDK, BTK, GİB, Sigorta Tahkim, Uyuşmazlık Mahkemesi...) hiçbirinde tek tip,
tutarlı bir resmi API yok.** Kurumlara göre değişen üç farklı erişim modeli
gözlemlendi:

- Resmi JSON API (Bedesten — Adalet Bakanlığı, BTK, GİB özelge API'si)
- HTML scraping (Uyuşmazlık Mahkemesi'nin ASP.NET WebForms yapısı, Emsal/UYAP,
  Rekabet Kurumu, Sayıştay)
- Üçüncü parti arama motoru üzerinden site-hedefli arama (KVKK/BDDK/Sigorta
  Tahkim → Brave Search / Tavily Search)

Bu gözlem, bu projenin veri kaynağı kararını doğrudan şekillendirdi: GİB ve
mevzuat.gov.tr için de tek, temiz bir resmi API bulunacağı varsayılmadı;
tasarım baştan **GİB özelgeleri (API veya scraping) + mevzuat.gov.tr scraping**
karışımına göre kuruldu (bkz. PROJECT.md §3.6.1). Ayrıca yargi-mcp'nin
`gib_mcp_module`'ü, GİB özelge arama/getirme deseni için doğrudan referans
alınabilecek bir örnek olarak not edildi.

## Soru: LLM'in etiketleme sürecindeki rolü ne, neden tam otomatik değil?

Ham mevzuat metnini (madde, tebliğ, özelge) yapılandırılmış bir kurala
(`{konu, kapsam, oran/kod, yürürlük_başlangıç/bitiş, kaynak_referansı}`)
çevirmek serbest metin yorumlama gerektiren bir iş — tam olarak LLM'in iyi
olduğu ama aynı zamanda hata riski taşıyan bir alan. Bu yüzden süreç şöyle
bölündü:

1. LLM ham metinden bir kural **taslağı** çıkarır.
2. Taslak, Kural Deposu'na doğrudan yazılmaz — bir onay kuyruğuna düşer.
3. Bir insan (analist) taslağı onaylamadan hiçbir sorgu-anı MCP çağrısı o
   kuralı göremez.

Bu, PROJECT.md §3.4'teki "belirsizlik durumunda insana yönlendirme, tahmin
değil" ilkesinin etiketleme aşamasına uygulanmış hali. LLM'in mevzuat
yorumlama esnekliğinden faydalanılıyor, ama nihai otorite insan onayı +
yapılandırılmış depoda kalıyor — böylece Değişmez Kural 1 etiketleme
otomasyonu eklendiğinde de delinmemiş oluyor.

> ✅ Onaylandı (2026-07-17): Kullanıcı bu üç kararı (veri kaynağı, Kural
> Deposu teknolojisi, LLM-taslak + insan-onay akışı) onayladı. Bkz.
> `PROJECT.md` §3.6.1.
