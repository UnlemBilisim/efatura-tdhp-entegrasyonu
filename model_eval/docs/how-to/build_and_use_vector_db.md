# Vektor veritabanini kurma ve RAG ile fatura degerlendirme

Bu rehber, `../Archive2` icindeki gecmis faturalardan bir vektor veritabani
kurup, gelecekte gelecek faturalari degerlendirirken (`evaluate_models.py`)
LLM'e "benzer bir fatura daha once nasil kodlanmis" ornegi gostermeyi anlatir.
Arka plandaki gerekce icin bkz. `docs/explanation/rag_retrieval.md`; alan/CLI
referansi icin bkz. `docs/reference/vector_db.md`.

## 1. Ortami hazirla (bir kere)

```bash
cd model_eval
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Embedding modelini indir (lokal, veri disariya cikmaz)
ollama pull embeddinggemma
```

## 2. Vektor veritabanini olustur (bir kere, sonra guncelleme icin tekrar calistirilabilir)

```bash
python3 build_vector_db.py
```

Cikis, kac faturanin indekslendigini ve ground-truth kaydi olmadigi icin kac
tanesinin atlandigini gosterir. Sonuc `vector_db/` altina yazilir.

Kucuk bir alt kumeyle denemek icin: `python3 build_vector_db.py --limit 20`.

**Yeni fatura eklendiginde** (prod akisinda faturalastirma kesinlestiginde):
`build_vector_db.py`'yi tekrar calistirin - `invoice_id`'ye gore upsert
yaptigi icin var olan kayitlari bozmadan yeni faturalari ekler.

## 3. RAG ile degerlendirme calistir

```bash
# Once prompt'un nasil goruntugunu gormek icin (API cagirmadan):
python3 evaluate_models.py --models gemma4:31b-cloud --rag --sample-size 5 --dry-run

# Gercek kosu:
python3 evaluate_models.py --models gemma4:31b-cloud --rag --sample-size 100 --seed 42
```

Sonuclar `results/gemma4_31b-cloud_rag.jsonl` (dosya adinda `+rag`
son eki) altina yazilir - RAG'siz sonuclarin uzerine yazmaz, ayri bir
karsilastirma kolu olarak kalir.

`--rag-k` ile few-shot ornek sayisini degistirebilirsiniz (varsayilan 3).

## 4. RAG'li ile RAG'siz sonucu karsilastir

```bash
python3 evaluate_models.py --models gemma4:31b-cloud --summarize-only
python3 evaluate_models.py --models gemma4:31b-cloud --rag --summarize-only
```

Her iki komut da `results/summary.json`'a yazar (bir sonraki
`--summarize-only` cagrisi dosyanin uzerine yazar) - karsilastirma icin
konsol ciktisindaki tabloyu not alin veya `--output-dir` ile ayri klasorlere
yonlendirin.

## Sorun giderme

- **`chromadb`/`ollama` import hatasi**: `pip install -r requirements.txt`
  calistirildi mi kontrol edin - bu paketler sadece `--rag` bayragi
  kullanildiginda gereklidir.
- **Bos/anlamsiz few-shot ornekleri**: `--rag-persist-dir` ve
  `--rag-embed-model`, `build_vector_db.py`'de kullanilanla ayni oldugundan
  emin olun (bkz. `docs/reference/vector_db.md`'deki uyari - farkli embedding
  modeliyle sorgulamak anlamsiz sonuc dondurur).
- **Ollama embedding cagrisi basarisiz**: `ollama pull embeddinggemma`
  calistirildi mi ve `ollama` servisi ayakta mi (`ollama list`) kontrol edin.
