"""CLI giris noktasi: argparse tanimlari ve main() akisi."""

import argparse
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .constants import (
    DEFAULT_DATA_DIR,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OWN_VKN,
    DEFAULT_SECTOR,
    SYSTEM_PROMPT,
)
from .parsing import load_invoice_paths, parse_invoice, parse_invoice_xml
from .prompting import build_glossary_system_prompt, build_user_prompt
from .providers import parse_model_spec
from .reporting import count_results, print_summary_table, result_label, summarize_model
from .runner import run_model


def main():
    ap = argparse.ArgumentParser(description="TDHP bilgisi icin coklu model karsilastirma testi")
    ap.add_argument(
        "--models",
        required=True,
        help=(
            "Virgulle ayrilmis Ollama model listesi (orn. gemma4:31b-cloud). "
            "Onek yoksa ya da 'ollama:' onekliyse Ollama sayilir - sadece "
            "Ollama destekleniyor (2026-07-29)."
        ),
    )
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Archive2/jsons klasoru (ya da --data-format xml ise ham UBL XML klasoru)")
    ap.add_argument(
        "--data-format",
        choices=["json", "xml"],
        default="json",
        help=(
            "json (varsayilan): Archive2/jsons'daki ground-truth icerikli faturalar, "
            "dogruluk olculur. xml: ham UBL e-fatura XML'leri (henuz muhasebelesmemis "
            "YENI faturalar) - ground-truth YOKTUR, sonuclar TAHMIN'dir, skorlama yapilmaz."
        ),
    )
    ap.add_argument(
        "--own-vkn",
        default=DEFAULT_OWN_VKN,
        help="Sirketin kendi VKN'si - --data-format xml ile inbox/outbox yonunu ve karsi tarafi tespit etmek icin kullanilir.",
    )
    ap.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST, help="Ollama API adresi (env OLLAMA_HOST ile de ayarlanabilir)")
    ap.add_argument("--sector", default=DEFAULT_SECTOR, help="Prompt'ta verilen sirket sektoru baglami")
    ap.add_argument("--sample-size", type=int, default=None, help="Test edilecek fatura sayisi (varsayilan: hepsi)")
    ap.add_argument(
        "--invoice-type",
        default=None,
        help="Sadece belirli fatura tipini test et (orn. TEVKIFAT, SATIS, ISTISNA, IADE, IHRACKAYITLI). Virgulle birden fazla verilebilir.",
    )
    ap.add_argument("--seed", type=int, default=42, help="Ornekleme icin rastgele tohum")
    ap.add_argument("--concurrency", type=int, default=4, help="Model basina es zamanli istek sayisi")
    ap.add_argument("--model-parallelism", type=int, default=1, help="Ayni anda calisacak model sayisi (1=sirayla, N=N modeli birlikte calistir)")
    ap.add_argument("--timeout", type=float, default=180.0, help="Istek basina zaman asimi (sn)")
    ap.add_argument("--temperature", type=float, default=0.0, help="Model sicakligi")
    ap.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Sonuclarin yazilacagi klasor")
    ap.add_argument("--overwrite", action="store_true", help="Var olan sonuclari silip bastan calistir")
    ap.add_argument("--summarize-only", action="store_true", help="API cagirma, sadece mevcut sonuc dosyalarini ozetle")
    ap.add_argument("--dry-run", action="store_true", help="Sadece ilk faturanin prompt'unu yazdir, API cagirma")
    ap.add_argument(
        "--with-glossary",
        action="store_true",
        help=(
            "DIKKAT: orijinal 'hesap plani vermeden test' senaryosunun TERSI. "
            "System prompt'a TDHP kod aciklamalarini (glossary) ekler. Ayri bir "
            "sonuc dosyasina yazar (+glossary son eki), mevcut referanssiz "
            "sonuclari ETKILEMEZ/EZMEZ - ayri bir karsilastirma kolu olarak kullanin."
        ),
    )
    ap.add_argument(
        "--tevkifat-hint",
        action="store_true",
        help=(
            "Tevkifatli faturalarda KDV bolusumunu (satici payi / tevkif edilen pay) "
            "Python'da onceden hesaplayip prompt'a ekler - LLM'e aritmetik biraktirmaz. "
            "Ayri sonuc dosyasina yazar (+tevkifathint son eki)."
        ),
    )
    ap.add_argument(
        "--iade-hint",
        action="store_true",
        help=(
            "IADE faturalarinda ters kayit yonunu (Borc/Alacak) ve KDV hesap "
            "kodunu (391 alistan iade / 191 satistan iade) Python'da onceden "
            "hesaplayip prompt'a ekler - LLM'e sadece hangi mal/hizmet hesabini "
            "kullanacagi kalir. Ayrica IADE faturalarda direction_text'in "
            "('biz saticiyiz'/'biz aliciyiz') yanlis cerceveledigi durum her "
            "zaman (bu bayrak olmadan da) duzeltilmistir - bkz. RESULTS.md SS6.3. "
            "Ayri sonuc dosyasina yazar (+iadehint son eki)."
        ),
    )
    ap.add_argument(
        "--self-correct",
        action="store_true",
        help=(
            "Model cevabi dengesizse (Borc != Alacak), ona kendi cevabini ve "
            "dengesizligi gosterip tek seferlik duzeltme sansi verir. --rag ile "
            "birlikte kullanilirsa, model RAG'in gosterdigi GUCLU bir emsalden "
            "(ayni tedarikci, cok yuksek benzerlik) farkli bir kod urettiginde de "
            "aynı duzeltme turu tetiklenir (bkz. RESULTS.md 6.1/6.2 - 16 hatanin "
            "10'unda dogru emsal gosterilmis ama model gormezden gelmisti). Sadece "
            "Ollama saglayicisi icin calisir. Ayri sonuc dosyasina yazar "
            "(+selfcorrect son eki)."
        ),
    )
    ap.add_argument(
        "--rag",
        action="store_true",
        help=(
            "build_vector_db.py ile onceden olusturulmus ChromaDB'de bu faturaya "
            "en benzer gecmis faturalari arar, o faturalarda kullanilan TDHP "
            "kodlarini few-shot ornek olarak prompt'a ekler. Once "
            "'python build_vector_db.py' calistirilmis olmali. Ayri sonuc "
            "dosyasina yazar (+rag son eki). chromadb + ollama paketleri gerekir."
        ),
    )
    ap.add_argument("--rag-k", type=int, default=3, help="Prompt'a eklenecek benzer gecmis fatura sayisi")
    ap.add_argument("--rag-persist-dir", default=None, help="ChromaDB'nin diske yazdigi klasor (varsayilan: model_eval/vector_db)")
    ap.add_argument("--rag-embed-model", default=None, help="Ollama embedding modeli (varsayilan: embeddinggemma)")
    ap.add_argument("--rag-ollama-host", default=None, help="Embedding icin Ollama API adresi (varsayilan: localhost:11434)")
    args = ap.parse_args()

    if args.rag:
        import rag_common
        if args.rag_persist_dir is None:
            args.rag_persist_dir = str(rag_common.DEFAULT_PERSIST_DIR)
        if args.rag_embed_model is None:
            args.rag_embed_model = rag_common.DEFAULT_EMBED_MODEL

    model_strs = [m.strip() for m in args.models.split(",") if m.strip()]
    if not model_strs:
        print("En az bir model belirtmelisiniz: --models qwen2.5:14b-instruct", file=sys.stderr)
        sys.exit(1)

    try:
        specs = [parse_model_spec(m, args.ollama_host) for m in model_strs]
    except ValueError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        sys.exit(1)

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        summaries = [
            summarize_model(
                result_label(s["label"], args.with_glossary, args.tevkifat_hint, args.self_correct, args.rag, args.iade_hint),
            )
            for s in specs
        ]
        print_summary_table(summaries)
        with open(Path(args.output_dir) / "summary.json", "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)
        return

    paths = load_invoice_paths(args.data_dir, data_format=args.data_format)
    if not paths:
        print(f"Uyari: {args.data_dir} icinde .{args.data_format} fatura bulunamadi.", file=sys.stderr)
        sys.exit(1)

    if args.data_format == "xml":
        invoices = [parse_invoice_xml(p, own_vkn=args.own_vkn) for p in paths]
        print(
            f"XML modu: {len(invoices)} ham fatura ayristirildi. Bunlarin ground-truth "
            f"muhasebe kaydi YOK - sonuclar TAHMIN'dir, dogruluk olculmez."
        )
    else:
        invoices = [parse_invoice(p) for p in paths]
        invoices = [inv for inv in invoices if inv["gt_pairs"]]  # ground truth'u olmayanlari degerlendiremeyiz

    if args.invoice_type:
        wanted_types = {t.strip().upper() for t in args.invoice_type.split(",") if t.strip()}
        before = len(invoices)
        invoices = [inv for inv in invoices if (inv["header"].get("invoice_type") or "").upper() in wanted_types]
        print(f"--invoice-type filtresi ({', '.join(sorted(wanted_types))}): {before} faturadan {len(invoices)} tanesi kaldi.")
        if not invoices:
            print("Uyari: filtreye uyan fatura bulunamadi.", file=sys.stderr)
            sys.exit(1)

    if args.sample_size is not None and args.sample_size < len(invoices):
        rng = random.Random(args.seed)
        invoices = rng.sample(invoices, args.sample_size)

    if args.data_format == "xml":
        print(f"Toplam {len(invoices)} fatura (ham XML, ground-truth yok) tahmin edilecek.")
    else:
        print(f"Toplam {len(invoices)} fatura (ground-truth muhasebe kaydi olan) test edilecek.")

    if args.dry_run:
        sample = invoices[0]
        active_prompt = build_glossary_system_prompt() if args.with_glossary else SYSTEM_PROMPT
        rag_block = ""
        if args.rag:
            collection = rag_common.get_collection(
                persist_dir=args.rag_persist_dir, embed_model=args.rag_embed_model, ollama_host=args.rag_ollama_host,
            )
            similar = rag_common.retrieve_similar(collection, sample, k=args.rag_k)
            block = rag_common.format_few_shot_block(similar)
            rag_block = f"\n{block}\n" if block else ""
        print("\n--- SYSTEM PROMPT" + (" (+glossary)" if args.with_glossary else "") + " ---\n" + active_prompt)
        print("--- USER PROMPT (ornek: {}) ---\n".format(sample["invoice_id"]) + build_user_prompt(sample, args.sector, tevkifat_hint=args.tevkifat_hint, rag_block=rag_block, iade_hint=args.iade_hint))
        if sample.get("has_ground_truth", True):
            print("--- GROUND TRUTH (modele verilmeyecek) ---")
            print(sorted(sample["gt_pairs"]))
        else:
            print("--- GROUND TRUTH YOK (bu fatura icin gercek kayit henuz mevcut degil - sonuc TAHMIN olacak) ---")
        return

    # get_collection() artik process-omru boyunca singleton dondurdugu icin
    # (bkz. rag_common.py) burada ayrica "once ac, paylas" yapmaya gerek yok -
    # her run_model() cagrisi zaten ayni Collection nesnesini alir. Bu onceden
    # acma islemi yine de zararsiz (ayni singleton'i erken tetikler), main()
    # akisini basitce koruyoruz.
    shared_rag_collection = None
    if args.rag and args.model_parallelism > 1:
        import rag_common
        shared_rag_collection = rag_common.get_collection(
            persist_dir=args.rag_persist_dir,
            embed_model=args.rag_embed_model,
            ollama_host=args.rag_ollama_host,
        )

    if args.model_parallelism <= 1:
        for spec in specs:
            run_model(spec, invoices, args, args.sector, rag_collection=shared_rag_collection)
    else:
        print(f"\n{len(specs)} model, es zamanli calisiyor (model-parallelism={args.model_parallelism})...")
        with ThreadPoolExecutor(max_workers=args.model_parallelism) as pool:
            futures = [
                pool.submit(run_model, spec, invoices, args, args.sector, shared_rag_collection)
                for spec in specs
            ]
            for fut in as_completed(futures):
                fut.result()  # burada patlarsa hemen gorelim, sessizce yutulmasin

    if args.data_format == "xml":
        # Ground-truth yok - pair_F1/exact_pair% gibi dogruluk metrikleri
        # anlamsiz (hesaplanamaz). Skorlama tablosu yerine sadece kac
        # faturanin tahmin edildigini ve nereye yazildigini bildir.
        for s in specs:
            file_label = result_label(s["label"], args.with_glossary, args.tevkifat_hint, args.self_correct, args.rag, args.iade_hint)
            n = count_results(file_label)
            print(f"[{s['label']}] {n} fatura icin tahmin uretildi -> model_eval_sonuclar (file_label={file_label})")
        print(f"\nTahminler: PostgreSQL model_eval_sonuclar tablosunda (ground-truth olmadigi icin dogruluk metrigi hesaplanmadi)")
        return

    summaries = [
        summarize_model(
            result_label(s["label"], args.with_glossary, args.tevkifat_hint, args.self_correct, args.rag, args.iade_hint),
        )
        for s in specs
    ]
    print_summary_table(summaries)
    with open(Path(args.output_dir) / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)
    print(f"\nSonuclar: model_eval_sonuclar tablosunda; ozet: {args.output_dir}/summary.json")
