# RAG vektor veritabani — teknik referans

Kodla senkron tutulmasi gereken sabitler ve semalar icin bkz. ilgili dosya/fonksiyon.
Isim/tip/varsayilan degistiginde bu dosya AYNI COMMIT'te guncellenmelidir.

## Bilesenler

| Bilesen | Dosya | Aciklama |
|---|---|---|
| Embedding fonksiyonu | `rag_common.py::OllamaEmbeddingFunction` | Lokal Ollama sunucusu uzerinden embedding uretir (`ollama.Client.embed`) |
| Koleksiyon erisimi | `rag_common.py::get_collection` | `chromadb.PersistentClient` acar/olusturur |
| Indeksleme (CLI) | `build_vector_db.py` | `../Archive2/jsons`'daki ground-truth faturalari koleksiyona yazar |
| Sorgu/few-shot | `rag_common.py::retrieve_similar`, `format_few_shot_block` | `evaluate_models.py --rag` tarafindan kullanilir |

## Varsayilan degerler (`rag_common.py`)

| Sabit | Varsayilan | Aciklama |
|---|---|---|
| `DEFAULT_EMBED_MODEL` | `embeddinggemma` | Ollama embedding modeli. Once `ollama pull embeddinggemma` calistirilmali. |
| `DEFAULT_PERSIST_DIR` | `vector_db/` | ChromaDB'nin diske yazdigi klasor (git'e eklenmez, `.gitignore`'da). |
| `COLLECTION_NAME` | `tdhp_invoices` | Chroma koleksiyon adi. |
| `STRONG_MATCH_MAX_DISTANCE` | `0.15` | Bu mesafenin altindaki emsaller "GUCLU ESLESME" sayilir (few-shot'ta zorlayici dil + self-correct tetikleyicisi). Gecmis bir gozlemsel dagilim analizine gore secildi (bkz. `rag_common.py` yorumu) - esik degistirilirse o analiz de gozden gecirilmeli. |

**Onemli:** embedding modeli degistirilirse (`--rag-embed-model`), eski
koleksiyondaki vektorler YENI modelle uyumsuz olur - ayni `--persist-dir`
uzerinde farkli bir modelle sorgulamak anlamsiz sonuc dondurur. Model
degisikliginde `--persist-dir`'i de degistirip `build_vector_db.py`'yi
sifirdan calistirin.

## Chroma metadata semasi (`invoice_metadata`, `rag_common.py`)

Her indekslenen fatura, `invoice_id` ile upsert edilir ve su metadata'yi tasir:

| Alan | Tip | Aciklama |
|---|---|---|
| `vkn` | str | Karsi tarafin VKN/TCKN'i (`header.account_tax_number`) |
| `account_title` | str | Karsi taraf unvani |
| `direction` | str | `inbox` (alis) / `outbox` (satis) |
| `invoice_type` | str | `SATIS`, `TEVKIFAT`, `ISTISNA`, `IADE`, `IHRACKAYITLI` vb. |
| `entries_json` | str (JSON) | `[{"code": "3 haneli TDHP kodu", "dc": "Borc"/"Alacak", "name": "hesap adi"}, ...]` — o faturada gercekten kullanilan (tekillestirilmis) hesaplar |

Embedding'e giren dokuman metni (`build_retrieval_text`) **sadece** karsi
taraf unvani, fatura tipi, yon, satir kalemi adlari ve vergi adlarindan
olusur — tutar ve hesap kodu **icermez** (bkz.
`docs/explanation/rag_retrieval.md`).

## CLI — `build_vector_db.py`

```
python3 build_vector_db.py \
  --own-vkn <sirketin_vkni> \
  [--data-dir ../Archive2/jsons] \
  [--persist-dir vector_db] \
  [--embed-model embeddinggemma] \
  [--ollama-host http://localhost:11434] \
  [--limit N]
```

`--own-vkn` zorunludur (2026-09-29) — hangi RAG koleksiyonuna
(`tdhp_invoices_<vkn>`, bkz. `rag_common.koleksiyon_adi_coz`) yazılacağını
belirler; verilmezse script çalışmaz. Idempotenttir (invoice_id'ye gore
upsert); yeni fatura eklendiginde tekrar calistirilarak veritabani
guncellenebilir.

## CLI — `evaluate_models.py --rag`

| Bayrak | Varsayilan | Aciklama |
|---|---|---|
| `--rag` | kapali | RAG few-shot'u devreye alir. Ayri sonuc dosyasina yazar (`+rag` son eki, bkz. `result_label`). |
| `--rag-k` | `3` | Prompt'a eklenecek benzer gecmis fatura sayisi |
| `--rag-persist-dir` | `vector_db` | `build_vector_db.py` ile ayni klasor olmali |
| `--rag-embed-model` | `embeddinggemma` | `build_vector_db.py` ile ayni model olmali |
| `--rag-ollama-host` | `http://localhost:11434` | Embedding sorgusu icin Ollama adresi |

`--rag` verilmediginde `chromadb`/`ollama` paketleri hic import edilmez
(bkz. `evaluate_models.py::run_model` icindeki lazy import) - bu iki bayrak
ailesi birbirinden bagimsiz calisir.

### `--rag` + `--self-correct` etkilesimi

`--self-correct` tek basina sadece Borc≠Alacak dengesizligini yakalar.
`--rag` ile birlikte verildiginde, ayrica su durumu da yakalar: model,
`STRONG_MATCH_MAX_DISTANCE` altindaki bir emsalden (ayni tedarikci, cok
yuksek benzerlik) farkli bir `(kod, yon)` seti urettiginde de tek seferlik
bir duzeltme turu tetiklenir (`rag_common.py::strongest_precedent`,
`build_precedent_correction_request`). Sonuc jsonl'deki `self_corrected=True`
kayitlarinda hangi sebep tetikledigini gosteren `self_correct_reason` alani
bulunur: `"balance"` (dengesizlik) veya `"precedent_mismatch"` (emsale
uyumsuzluk). Dengesizlik varsa o once kontrol edilir - ikisi ayni anda
olusabilir, oncelik dengesizliktedir.

### `--rag` + `--iade-hint` etkilesimi

`--iade-hint` (RAG'dan bagimsiz bir bayrak, `evaluate_models.py::compute_iade_hint`)
IADE faturalarinda ters kayit yonunu (Borc/Alacak) ve KDV hesap kodunu
(391 alistan iade / 191 satistan iade) deterministik hesaplayip prompt'a
ekler - RAG'in aksine "hangi hesap" sorusuna karismaz, sadece yon/kod/tutar
verir. `--rag` ile birlikte kullanilabilir: RAG hangi mal/hizmet hesabinin
(150/730/770 vb.) kullanilacagina dair emsal gosterir, `--iade-hint` o
hesabin hangi YONDE (Borc/Alacak) kullanilacagini kesinlestirir. Ayri sonuc
dosyasina yazar (`+iadehint` son eki). Detay ve gerekce:
`core/prompting.py::compute_iade_hint` docstring'i.

## Bagimliliklar

`requirements.txt`: `chromadb`, `ollama` (Python client), ayrica
`ollama pull embeddinggemma` ile CLI uzerinden embedding modeli indirilmis
olmali.

> ✅ **Uygulandi** (2026-07-10): Yukaridaki tum alan adlari/varsayilanlar
> `rag_common.py` ve `build_vector_db.py` ile birebir
> senkrondur. Vektor veritabani, `../Archive2/jsons` icindeki 1646 ground-truth
> faturayla olusturulmustur (bkz. `build_vector_db.py` cikisi).
