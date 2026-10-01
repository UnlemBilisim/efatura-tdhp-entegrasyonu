#!/usr/bin/env python3
"""Archive2/jsons icindeki gecmis faturalardan ChromaDB vektor veritabani insa eder.

Amac: evaluate_models.py --rag'in sorgulayacagi bilgi tabanini olusturmak.
Sadece ground-truth muhasebe kaydi (accounting_entries) olan faturalar indekslenir
- kaydi olmayan bir fatura "daha once nasil kodlandi" sorusuna ornek olamaz.

Kullanim
--------
    cd model_eval
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    ollama pull embeddinggemma   # embedding modeli (bir kere)
    python3 build_vector_db.py

Idempotent'tir: invoice_id'ye gore upsert yapar, tekrar calistirmak veriyi
kopyalamaz/bozmaz. Yeni fatura eklendiginde (prod akisinda, faturalastirma
kesinlestiginde) bu script tekrar calistirilarak veritabani guncellenebilir.

--own-vkn (2026-09-29, cok sirketli onboarding hazirligi): HANGI sirketin
RAG koleksiyonuna yazildigini belirler (rag_common.koleksiyon_adi_coz ile
ayni kural - Akyuzlu'nun DEFAULT_OWN_VKN'i sabit "tdhp_invoices" adina
duser, digerleri "tdhp_invoices_<vkn>"). ONCEDEN bu parametre YOKTU, script
HER ZAMAN sabit koleksiyona yaziyordu - yeni bir sirketin faturalari bu
sekilde calistirilsaydi Akyuzlu'nun emsal havuzuna KARISIRDI. Artik --own-vkn
ZORUNLU (varsayilani yok) - hangi sirket icin calistirildigi acikca
belirtilmeden hicbir yazma yapilmaz, sessizce yanlis koleksiyona dusulmez.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.parsing import load_invoice_paths, parse_invoice, normalize_code3, normalize_dc
from rag_common import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_PERSIST_DIR,
    build_retrieval_text,
    extract_named_gt_entries,
    get_collection,
    invoice_metadata,
    koleksiyon_adi_coz,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = SCRIPT_DIR.parent / "Archive2" / "jsons"
BATCH_SIZE = 64


def index_directory(
    own_vkn: str,
    data_dir=DEFAULT_DATA_DIR,
    persist_dir=DEFAULT_PERSIST_DIR,
    embed_model=DEFAULT_EMBED_MODEL,
    ollama_host=None,
    limit=None,
) -> dict:
    """Asil indeksleme mantigi - hem CLI (main()) hem baska script'lerin
    (scripts/musteri_onboard_toplu.py) dogrudan import edip cagirmasi icin
    ayri bir fonksiyon (2026-09-29). subprocess/sys.argv manipulasyonu
    GEREKMEZ - cagiran taraf Python seviyesinde hatayi yakalayabilir."""
    paths = load_invoice_paths(data_dir)
    if not paths:
        raise SystemExit(f"{data_dir} icinde .json fatura bulunamadi.")

    if limit:
        paths = paths[:limit]

    collection_name = koleksiyon_adi_coz(own_vkn)
    print(f"Hedef koleksiyon: {collection_name} (own_vkn={own_vkn})")
    collection = get_collection(
        persist_dir=persist_dir, embed_model=embed_model, ollama_host=ollama_host,
        collection_name=collection_name,
    )

    ids, docs, metas = [], [], []
    skipped_no_gt = 0

    def flush():
        if not ids:
            return
        collection.upsert(ids=ids, documents=docs, metadatas=metas)
        ids.clear()
        docs.clear()
        metas.clear()

    for i, path in enumerate(paths, 1):
        invoice = parse_invoice(path)
        if not invoice["gt_pairs"]:
            skipped_no_gt += 1
            continue

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        named_entries = extract_named_gt_entries(raw, normalize_code3, normalize_dc)
        if not named_entries:
            skipped_no_gt += 1
            continue

        ids.append(invoice["invoice_id"])
        docs.append(build_retrieval_text(invoice))
        metas.append(invoice_metadata(invoice, named_entries))

        if len(ids) >= BATCH_SIZE:
            flush()
            print(f"  {i}/{len(paths)} islendi...")

    flush()

    total = collection.count()
    print(f"\nTamamlandi. Toplam {len(paths)} fatura tarandi, {skipped_no_gt} tanesi ground-truth kaydi olmadigi icin atlandi.")
    print(f"Vektor veritabanindaki toplam kayit: {total} (persist-dir: {persist_dir})")
    return {"taranan": len(paths), "atlanan": skipped_no_gt, "toplam_kayit": total, "koleksiyon": collection_name}


def main():
    ap = argparse.ArgumentParser(description="Archive2 faturalarindan RAG vektor veritabani olusturur")
    ap.add_argument(
        "--own-vkn", required=True,
        help="Bu faturalarin ait oldugu sirketin VKN'si - hangi RAG koleksiyonuna "
             "yazilacagini belirler (rag_common.koleksiyon_adi_coz). Yanlis VKN "
             "verilirse faturalar BASKA sirketin emsal havuzuna karisir.",
    )
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Fatura JSON'larinin bulundugu klasor")
    ap.add_argument("--persist-dir", default=str(DEFAULT_PERSIST_DIR), help="ChromaDB'nin diske yazacagi klasor")
    ap.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL, help="Ollama embedding modeli (once 'ollama pull <model>')")
    ap.add_argument("--ollama-host", default=None, help="Ollama API adresi (varsayilan: localhost:11434)")
    ap.add_argument("--limit", type=int, default=None, help="Test icin ilk N faturayla sinirla")
    args = ap.parse_args()

    index_directory(
        own_vkn=args.own_vkn, data_dir=args.data_dir, persist_dir=args.persist_dir,
        embed_model=args.embed_model, ollama_host=args.ollama_host, limit=args.limit,
    )


if __name__ == "__main__":
    main()
