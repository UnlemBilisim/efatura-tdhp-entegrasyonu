#!/usr/bin/env python3
"""RAG / vektor veritabani ortak mantigi.

build_vector_db.py (indeksleme) ve evaluate_models.py --rag (sorgu/few-shot)
tarafindan paylasilir. Amac: yeni gelen bir faturayi, Archive2'deki gecmis
faturalarin embedding'leriyle karsilastirip "bu faturaya benzer, daha once
nasil muhasebelestirilmis" ornekleri bulup LLM'in promptuna few-shot olarak
eklemek (bkz. model_eval/RESULTS.md "Siradaki Adimlar" - RAG/few-shot).

Bagimlilik notu: bu modul chromadb ve ollama paketlerini import eder. Sadece
--rag / build_vector_db.py kullanan akislarda import edilmelidir (evaluate_models.py
--rag verilmediginde bu modulu hic import etmez, boylece RAG'siz kullanim icin
bu agir bagimliliklar gerekmez).
"""

import json
import threading
from pathlib import Path

import ollama
from chromadb import Documents, EmbeddingFunction, Embeddings
import chromadb

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_EMBED_MODEL = "embeddinggemma"
DEFAULT_PERSIST_DIR = SCRIPT_DIR / "vector_db"
COLLECTION_NAME = "tdhp_invoices"

# Ayni persist_dir'e birden fazla PersistentClient'in AYNI ANDA baglanmasi
# "Could not connect to tenant" hatasina yol aciyor (SQLite tabanli ChromaDB
# coklu-islem/thread ilk-baglanma yarisini kaldirmiyor - bkz. runner.py'deki
# eski not). get_collection() artik (persist_dir, embed_model, ollama_host)
# anahtarina gore process-omru boyunca TEK bir client/collection dondurur -
# CLI'daki "sadece --model-parallelism>1 icin sharedcollection ac" gecici
# cozumune artik gerek yok, her cagiran ayni singleton'i alir.
_collection_cache = {}
_collection_cache_lock = threading.Lock()

# RESULTS.md 6.1'deki hata analizinde ayni tedarikciden/urunden gelen gercek
# emsallerin mesafesi tipik olarak <0.15 cikti (orn. 0.000, 0.036, 0.053, 0.138);
# farkli tedarikci/urune kayan genel-benzerlik doldurmalari 0.27+ mesafede kaldi.
# Bu esik, format_few_shot_block'ta "GUCLU ESLESME" etiketi ve
# strongest_precedent()'in self-correct tetikleyicisi icin kullanilir.
STRONG_MATCH_MAX_DISTANCE = 0.15


class OllamaEmbeddingFunction(EmbeddingFunction):
    """Chroma'nin EmbeddingFunction arayuzu icin lokal Ollama sunucusunu kullanan
    ince bir sarmalayici. Veri hic disariya (buluta) gitmez."""

    def __init__(self, model=DEFAULT_EMBED_MODEL, host=None):
        self.model = model
        self._host = host
        self.client = ollama.Client(host=host) if host else ollama.Client()

    def __call__(self, input: Documents) -> Embeddings:
        resp = self.client.embed(model=self.model, input=list(input))
        return resp["embeddings"]

    def name(self):
        # Chroma, koleksiyonu her acilista embedding fonksiyonunun kimligini
        # bu isimle dogrular - model degisirse farkli bir koleksiyon/isim kullanin.
        return f"ollama-{self.model}"


def get_collection(persist_dir=DEFAULT_PERSIST_DIR, embed_model=DEFAULT_EMBED_MODEL, ollama_host=None):
    key = (str(persist_dir), embed_model, ollama_host)
    if key in _collection_cache:
        return _collection_cache[key]
    with _collection_cache_lock:
        if key not in _collection_cache:
            client = chromadb.PersistentClient(path=str(persist_dir))
            ef = OllamaEmbeddingFunction(model=embed_model, host=ollama_host)
            _collection_cache[key] = client.get_or_create_collection(COLLECTION_NAME, embedding_function=ef)
    return _collection_cache[key]


def reset_collection_cache_for_tests():
    global _collection_cache
    with _collection_cache_lock:
        _collection_cache = {}


def build_retrieval_text(invoice):
    """Bir faturayi (evaluate_models.parse_invoice ciktisi) embedding icin metne
    cevirir. Kasitli olarak SADECE tanimlayici/kategorik bilgi kullanilir (karsi
    taraf, fatura tipi, kalem adlari, vergi turleri) - tutarlar ve muhasebe
    kodlari DAHIL EDILMEZ. Amac "bu ne turden bir fatura" benzerligini yakalamak;
    tutarlar zaten faturadan faturaya degisir ve gercek benzerlik sinyali degildir.
    """
    h = invoice["header"]
    direction_text = "ALIS" if invoice["direction"] == "inbox" else "SATIS"

    parts = [
        f"Karsi taraf: {h.get('account_title', '') or ''}",
        f"Fatura tipi: {h.get('invoice_type', '') or ''}",
        f"Yon: {direction_text}",
    ]
    for ln in invoice.get("lines", []):
        name = (ln.get("product_name") or "").strip()
        if name:
            parts.append(f"Kalem: {name}")
    for t in invoice.get("taxes", []):
        name = (t.get("name") or "").strip()
        if name:
            parts.append(f"Vergi: {name}")
    return "\n".join(parts)


def extract_named_gt_entries(raw_data, normalize_code3, normalize_dc):
    """Ham fatura JSON'undaki accounting_entries'i (account_name dahil) 3 haneli
    TDHP koduna gore tekillestirir. normalize_code3/normalize_dc, evaluate_models
    modulunden gecirilir (ayni normallestirme mantigini tekrar yazmamak icin)."""
    seen = {}
    for e in raw_data.get("accounting_entries", []):
        code3 = normalize_code3(e.get("account_code"))
        dc = normalize_dc(e.get("dc"))
        if not code3 or not dc:
            continue
        key = (code3, dc)
        if key not in seen:
            seen[key] = (e.get("account_name") or "").strip()
    return [
        {"code": code, "dc": dc, "name": name}
        for (code, dc), name in sorted(seen.items())
    ]


def invoice_metadata(invoice, named_entries):
    return {
        "vkn": invoice["header"].get("account_tax_number") or "",
        "account_title": invoice["header"].get("account_title") or "",
        "direction": invoice["direction"],
        "invoice_type": invoice["header"].get("invoice_type") or "",
        "entries_json": json.dumps(named_entries, ensure_ascii=False),
    }


def upsert_approved_invoice(collection, invoice, entries):
    """Kullanicinin arayuzde 'bu dogru' diye onayladigi bir LLM tahminini RAG
    koleksiyonuna ekler/gunceller (2026-07-23, kullanici karari).

    build_vector_db.py'nin "sadece ground-truth (Archive2/jsons) faturalari
    indeksle" kurali burada BILEREK genisletiliyor: kullanici onayi da bir
    tur ground-truth sayiliyor - LLM'in urettigi tahmin, insan tarafindan
    dogrulandiktan sonra gelecekteki faturalar icin few-shot ornegi olarak
    kullanilabilir hale geliyor. Bu, build_vector_db.py'nin script'ini
    DEGISTIRMEZ (o hala sadece Archive2/jsons'u tarar) - bu fonksiyon ayni
    ChromaDB koleksiyonuna ayrica, farkli bir yoldan (kullanici onayi ile)
    yaziyor.

    entries: predict_single_invoice() ciktisindaki format
    [{"account_code": "150", "dc": "Borc", "amount": 1234.56}, ...] -
    extract_named_gt_entries()'in urettigi {"code","dc","name"} formatindan
    FARKLI (LLM ciktisinda hesap ADI yok, sadece kod). Hesap adi TDHP_GLOSSARY
    sozlugunden otomatik dolduruluyor (core/constants.py) - bu, TUM
    muhasebecilerin ayni TDHP kodlarini kullandigi varsayimina dayanir.
    Ileride her muhasebeci icin ayri bir kod->isim listesi eklenmesi
    planlaniyor (bkz. model_eval/CLAUDE.md) - o zaman bu fonksiyon
    guncellenmeli, glossary yerine muhasebeciye ozel sozluk kullanilmali.

    Idempotent (build_vector_db.py'deki upsert ile ayni yontem, ayni
    invoice_id tekrar onaylanirsa GUNCELLENIR, cift kayit olusmaz) - ama
    cagiran taraf (entegrasyon/model_eval_koprusu.py) bilerek yinelenen
    onay kontrolu YAPMIYOR (kullanici karari, 2026-07-23: "her onay ayri
    bir kayit olsun, ama tarih kaydedilsin, ileride temizlenir") - PostgreSQL
    tarafinda (core/reporting.py::append_result) her onay ayri satir olarak
    birikiyor, sadece bu ChromaDB kaydi (invoice_id ayni oldugunda) upsert
    ile guncelleniyor."""
    from core.constants import TDHP_GLOSSARY

    named_entries = [
        {
            "code": e["account_code"],
            "dc": e["dc"],
            "name": TDHP_GLOSSARY.get(e["account_code"], ""),
        }
        for e in entries
    ]
    collection.upsert(
        ids=[invoice["invoice_id"]],
        documents=[build_retrieval_text(invoice)],
        metadatas=[invoice_metadata(invoice, named_entries)],
    )


def retrieve_similar(collection, invoice, k=3, prefer_same_vkn=True):
    """Verilen fatura icin en benzer k gecmis faturayi dondurur (kendisi haric).

    prefer_same_vkn=True ise once ayni karsi tarafin (VKN) gecmisinden arar
    (RESULTS.md'nin notu: 320/329 gibi ayrimlar sirketin kendi aliskanligina
    bagli, bunu en iyi ayni tedarikcinin gecmisi yakalar); yetmezse genel
    benzerlikle doldurur.
    """
    query_text = build_retrieval_text(invoice)
    self_id = invoice["invoice_id"]
    vkn = invoice["header"].get("account_tax_number") or ""

    picked = {}

    if prefer_same_vkn and vkn:
        res = collection.query(
            query_texts=[query_text], n_results=k + 1, where={"vkn": vkn}
        )
        _merge_query_result(picked, res, exclude_id=self_id, limit=k)

    if len(picked) < k:
        res = collection.query(query_texts=[query_text], n_results=k + len(picked) + 1)
        _merge_query_result(picked, res, exclude_id=self_id, limit=k)

    ordered = sorted(picked.values(), key=lambda r: r["distance"])[:k]
    return ordered


def _merge_query_result(picked, chroma_result, exclude_id, limit):
    ids = chroma_result["ids"][0]
    dists = chroma_result["distances"][0]
    metas = chroma_result["metadatas"][0]
    for inv_id, dist, meta in zip(ids, dists, metas):
        if inv_id == exclude_id or inv_id in picked:
            continue
        if len(picked) >= limit:
            break
        picked[inv_id] = {
            "invoice_id": inv_id,
            "distance": dist,
            "account_title": meta.get("account_title", ""),
            "vkn": meta.get("vkn", ""),
            "direction": meta.get("direction", ""),
            "invoice_type": meta.get("invoice_type", ""),
            "entries": json.loads(meta.get("entries_json") or "[]"),
        }


def format_few_shot_block(similar_invoices):
    """Benzer gecmis faturalari, LLM promptuna eklenecek Turkce bir metin
    bloguna cevirir. Bos liste icin bos string dondurur (blok hic eklenmez).

    Her ornek, mesafesine gore kademeli bir dille etiketlenir: mesafe
    STRONG_MATCH_MAX_DISTANCE altindaysa "[GUCLU ESLESME]" (aksi bir sebep
    yoksa AYNI kodu kullanmasi istenir), ustundeyse "[referans]" (sadece
    ilham amacli). RESULTS.md 6.1'deki analiz, ilk versiyondaki tek-duzey
    "referans amaclidir, kor kor kopyalama yapma" dilinin, model dogru
    emsali gorse bile onu gormezden gelmesine yol actigini gosterdi (16
    hatali faturanin 10'unda dogru emsal gosterilmisti) - bu yuzden guclu
    eslesmelerde daha zorlayici bir ifade kullanilir."""
    if not similar_invoices:
        return ""

    lines = [
        "### BENZER GECMIS FATURALAR",
        "Vektor veritabaninda bu faturaya en cok benzeyen, daha once muhasebelestirilmis "
        "gecmis faturalar ve o zaman kullanilan TDHP kodlari asagida.",
        "[GUCLU ESLESME] etiketli bir ornek varsa (ayni tedarikci, cok yuksek benzerlik): "
        "aksi bir sebep yoksa (orn. bariz sekilde farkli bir urun/hizmet turu) AYNI hesap "
        "kodlarini kullan - bu, TDHP hakkindaki genel bilginden daha guvenilir bir sinyaldir. "
        "[referans] etiketli ornekler ise sadece ilham amaclidir, kor kopyalama yapma.",
    ]
    for i, sim in enumerate(similar_invoices, 1):
        tag = "GUCLU ESLESME" if sim["distance"] < STRONG_MATCH_MAX_DISTANCE else "referans"
        direction_text = "ALIS" if sim["direction"] == "inbox" else "SATIS"
        entries_text = ", ".join(
            f"{e['code']} ({e['name']}) - {e['dc']}" if e.get("name") else f"{e['code']} - {e['dc']}"
            for e in sim["entries"]
        ) or "(kayit yok)"
        lines.append(
            f"{i}. [{tag}] Karsi taraf: {sim['account_title']} | Tip: {sim['invoice_type']} | Yon: {direction_text}\n"
            f"   Kullanilan hesaplar: {entries_text}"
        )
    return "\n".join(lines)


def strongest_precedent(similar_invoices):
    """En dusuk mesafeli ('en guclu') emsali dondurur; STRONG_MATCH_MAX_DISTANCE
    esigi altinda hicbir ornek yoksa None. self-correct'in "modele emsali
    hatirlat" tetikleyicisi icin kullanilir (bkz. build_precedent_correction_request)."""
    candidates = [s for s in similar_invoices if s["distance"] < STRONG_MATCH_MAX_DISTANCE]
    if not candidates:
        return None
    return min(candidates, key=lambda s: s["distance"])


def build_precedent_correction_request(strong, pred_pairs):
    """Model, kendisine gosterilen guclu bir emsalden farkli bir (kod, yon)
    seti urettiyse, bunu hatirlatip tek seferlik bir gozden gecirme sansi
    vermek icin duzeltme metni olusturur. Model zaten emsalle ayni cevabi
    verdiyse None doner (duzeltmeye gerek yok, ekstra API cagrisi yapilmaz)."""
    precedent_pairs = {(e["code"], e["dc"]) for e in strong["entries"]}
    if precedent_pairs == set(pred_pairs):
        return None
    entries_text = ", ".join(f"{c} ({dc})" for c, dc in sorted(precedent_pairs))
    return (
        f"Bu faturaya cok benzeyen (ayni tedarikci: {strong['account_title']}, "
        f"benzerlik mesafesi={strong['distance']:.3f} - COK YAKIN) gecmis bir faturada "
        f"su hesaplar kullanilmisti: {entries_text}. Sen farkli bir kombinasyon yazdin. "
        f"Bu faturanin da ayni turden oldugunu dusunuyorsan cevabini bu emsale gore "
        f"duzelt; gercekten farkli bir durum oldugunu dusunuyorsan (orn. bariz sekilde "
        f"farkli bir urun/hizmet) ayni cevabi koruyabilirsin. SADECE (duzeltilmis ya da "
        f"onaylanmis) JSON'u don, baska hicbir metin ekleme."
    )
