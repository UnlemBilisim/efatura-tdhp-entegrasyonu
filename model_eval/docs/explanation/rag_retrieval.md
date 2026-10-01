# Neden RAG / vektor veritabani ile fatura kodlama?

## Sorun

Olculdugu gibi (bkz. `CLAUDE.md` "Kritik gercekler"), referanssiz test
edilen en iyi model (`gemma4:31b-cloud`) 100 faturadan sadece %60.6'sinda
tam dogru hesap kodu +
Borc/Alacak cikarabiliyor. En sik karistirilan kod ciftleri (`320`/`329`,
`150`/`153`, `730`/`770`/`760`) TDHP'nin resmi tanimindan cikarilamaz - ayrim
**sirketin kendi muhasebe aliskanligina** bagli. Modele TDHP'nin tam
listesini vermek (`--with-glossary`) bu sorunu cozmedi: 6 modelin 4'unde
sonucu kotulestirdi, cunku bilgi eksikligi degil, "hangi kodu ne zaman
kullanmali" ayrimindaki muhakeme eksikligi asil sorun.

## Yaklasim: gecmis faturalardan few-shot ornek

Eger sirket X'ten gelen bir telefon faturasi gecmiste hep `770` (Genel
Yonetim) olarak kodlanmissa, X'ten gelen yeni bir faturanin da `770` olmasi
gerektigi cok yuksek olasilikla dogrudur - bu bilgi TDHP'nin tanimindan degil,
**bu sirketin gecmis kayitlarindan** gelir. Bu yuzden:

1. `../Archive2/jsons` icindeki, ground-truth muhasebe kaydi (`accounting_entries`)
   olan ~1646 fatura, anlamsal (semantic) embedding'e cevrilip ChromaDB'de
   saklanir (`build_vector_db.py`).
2. Yeni/degerlendirilen bir fatura icin, once **ayni VKN'nin** (karsi tarafin)
   gecmisinde benzer fatura aranir; yetersizse genel benzerlikle doldurulur
   (`rag_common.py::retrieve_similar`).
3. Bulunan en benzer 1-3 fatura, o zaman kullanilan TDHP kodlariyla birlikte
   LLM'in promptuna few-shot ornek olarak eklenir
   (`rag_common.py::format_few_shot_block`,
   `evaluate_models.py --rag`).

## Neden few-shot (LLM'e ornek gostermek) ve deterministik bir kural motoru degil?

Karsi tarafin gecmisi her zaman %100 tutarli degildir (ayni tedarikciden hem
mal hem hizmet alinabilir, KDV orani/istisna durumu degisebilir). Bu yuzden
"ayni VKN -> otomatik ayni kod" seklinde sert bir kural yerine, LLM'e "gecmiste
boyle kodlanmis, ama faturanin kendi detaylarina uymuyorsa farkli bir kod da
secebilirsin" seklinde bir referans verilir - nihai muhakeme LLM'de kalir. Bu
karar `--tevkifat-hint` (deterministik, cunku KDV bolusumu gercekten sabit bir
formuldur) ile bilincli olarak farklidir: hesap kodu secimi formule
indirgenemeyecek kadar baglama bagli, KDV bolusumu ise degil.

## Neden embedding lokal (Ollama) uzerinden, bulut API'si degil?

Fatura verisi (VKN, tedarikci adi, urun/hizmet aciklamalari, tutarlar) ticari
ve potansiyel olarak kisisel veri icerir. Bulut bir embedding API'sine (OpenAI,
Voyage vb.) gonderilmesi ek bir veri paylasim riski ve maliyeti getirir.
Bunun yerine, sistemde zaten `-cloud` model cagrilari icin kullanilan lokal
Ollama sunucusu, embedding icin de kullanilir (`embeddinggemma` modeli,
`ollama pull embeddinggemma` ile bir kere indirilir). Veri hic disariya
cikmaz.

> ✅ **Uygulandi** (2026-07-10): `build_vector_db.py` (indeksleme),
> `rag_common.py` (embedding fonksiyonu + retrieval mantigi),
> `evaluate_models.py --rag` (prompt entegrasyonu). Bkz.
> `docs/reference/vector_db.md` ve `docs/how-to/build_and_use_vector_db.md`.
