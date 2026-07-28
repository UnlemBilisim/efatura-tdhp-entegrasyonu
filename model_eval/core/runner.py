"""Tek bir model spec'i icin fatura kumesini isleyip sonucu PostgreSQL'e yazan
orkestrasyon fonksiyonu (es zamanlilik, resume, RAG, self-correct dahil)."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .constants import SYSTEM_PROMPT
from .prompting import build_glossary_system_prompt, build_user_prompt
from .providers import (
    build_balance_correction_request,
    call_model,
    self_correct_ollama,
)
from .reporting import append_result, delete_results, load_done_ids, result_label
from .scoring import parse_model_output, score_entries


def run_model(spec, invoices, args, sector, rag_collection=None):
    label = spec["label"]
    with_glossary = getattr(args, "with_glossary", False)
    system_prompt = build_glossary_system_prompt() if with_glossary else SYSTEM_PROMPT
    rag = getattr(args, "rag", False)
    iade_hint = getattr(args, "iade_hint", False)
    file_label = result_label(
        label, with_glossary,
        getattr(args, "tevkifat_hint", False), getattr(args, "self_correct", False),
        rag, iade_hint,
    )
    if args.overwrite:
        delete_results(file_label)
        done_ids = set()
    else:
        done_ids = load_done_ids(file_label)

    todo = [inv for inv in invoices if inv["invoice_id"] not in done_ids]
    print(f"\n=== {label} === toplam {len(invoices)} fatura, {len(done_ids)} zaten var, {len(todo)} calisacak")

    if not todo:
        return

    completed = 0
    errors = 0

    tevkifat_hint = getattr(args, "tevkifat_hint", False)
    self_correct = getattr(args, "self_correct", False)

    if rag:
        # --rag icin chromadb/ollama sadece burada, gerektiginde import edilir -
        # RAG kullanmayan calistirmalar bu agir bagimliliklari gerektirmez.
        # Import, rag_collection paylasilmis olarak gelse bile HER ZAMAN
        # yapilmali - asagida (retrieve_rag_context, self-correct precedent
        # kontrolu) rag_common modulune referans var.
        import rag_common
        if rag_collection is None:
            # get_collection() process-omru boyunca singleton dondurur (bkz.
            # rag_common.py) - burada disaridan paylasilmamis gelse bile
            # kendi cagrisi ayni singleton'i alir, birden fazla PersistentClient
            # ayni persist_dir'e baglanmaz.
            rag_collection = rag_common.get_collection(
                persist_dir=args.rag_persist_dir,
                embed_model=args.rag_embed_model,
                ollama_host=args.rag_ollama_host,
            )

    def retrieve_rag_context(inv):
        """RAG blogunu (prompt'a eklenecek metin) ve ham 'similar' listesini
        (self-correct'in emsal-uyumsuzlugu kontrolu icin) birlikte dondurur."""
        if rag_collection is None:
            return "", None
        similar = rag_common.retrieve_similar(rag_collection, inv, k=args.rag_k)
        block = rag_common.format_few_shot_block(similar)
        rag_block = f"\n{block}\n" if block else ""
        return rag_block, similar

    def process(inv):
        rag_block, rag_similar = retrieve_rag_context(inv)
        user_prompt = build_user_prompt(inv, sector, tevkifat_hint=tevkifat_hint, rag_block=rag_block, iade_hint=iade_hint)
        raw, latency, err = call_model(spec, system_prompt, user_prompt, args.temperature, args.timeout)
        if err:
            record = {
                "invoice_id": inv["invoice_id"],
                "invoice_type": inv["header"].get("invoice_type"),
                "direction": inv["direction"],
                "sent_system_prompt": system_prompt,
                "sent_user_prompt": user_prompt,
                "error": err,
            }
            if inv.get("direction_uncertain"):
                record["direction_uncertain"] = True
            return record

        entries, parse_err = parse_model_output(raw)
        record = {
            "invoice_id": inv["invoice_id"],
            "invoice_type": inv["header"].get("invoice_type"),
            "direction": inv["direction"],
            "sent_system_prompt": system_prompt,
            "sent_user_prompt": user_prompt,
            "latency_s": round(latency, 3),
            "raw_response": raw[:2000],
        }
        if inv.get("direction_uncertain"):
            record["direction_uncertain"] = True
        if parse_err:
            record["error"] = parse_err
        else:
            metrics = score_entries(inv["gt_pairs"], entries)

            correction_request = None
            correction_reason = None
            if self_correct and not metrics["balanced"]:
                correction_request = build_balance_correction_request(metrics)
                correction_reason = "balance"
            elif self_correct and rag_similar is not None:
                # RAG'a guclu bir emsal (ayni tedarikci, cok yuksek benzerlik) dustuyse
                # ve model ona uymadiysa, RESULTS.md 6.1'in bulgusuna gore (16 hatanin
                # 10'unda dogru emsal gosterilmis ama gormezden gelinmis) modele bunu
                # hatirlatip tek seferlik bir gozden gecirme sansi ver.
                strong = rag_common.strongest_precedent(rag_similar)
                if strong is not None:
                    correction_request = rag_common.build_precedent_correction_request(strong, metrics["pred_pairs"])
                    correction_reason = "precedent_mismatch"

            if correction_request and spec["provider"] == "ollama":
                corr_raw, corr_latency, corr_err = self_correct_ollama(
                    spec["base_url"], spec["model"], system_prompt, user_prompt, raw, correction_request,
                    args.temperature, args.timeout,
                )
                if not corr_err:
                    corr_entries, corr_parse_err = parse_model_output(corr_raw)
                    if not corr_parse_err:
                        corr_metrics = score_entries(inv["gt_pairs"], corr_entries)
                        record["pre_correction_balanced"] = metrics["balanced"]
                        record["pre_correction_raw_response"] = raw[:2000]
                        record["self_corrected"] = True
                        record["self_correct_reason"] = correction_reason
                        raw = corr_raw
                        metrics = corr_metrics
                        latency += corr_latency
                        record["raw_response"] = raw[:2000]
                        record["latency_s"] = round(latency, 3)
            if inv.get("has_ground_truth", True):
                record.update(metrics)
                record["gt_pairs"] = sorted(inv["gt_pairs"])
            else:
                # Ground-truth yok (--data-format xml): fp_pairs/exact_pair_match
                # gibi karsilastirma alanlari gt_pairs=bos oldugu icin YANILTICI
                # olur (sanki model "hep yanlis" yapmis gibi gorunur). Bunun yerine
                # sadece temiz bir tahmin kaydi yaz - "dogru/yanlis" hic iddia etme.
                record["has_ground_truth"] = False
                record["predicted_entries"] = [
                    {"account_code": code, "dc": dc}
                    for code, dc in metrics["pred_pairs"]
                ]
                record["balanced"] = metrics["balanced"]
        return record

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(process, inv): inv for inv in todo}
        for fut in as_completed(futures):
            record = fut.result()
            if record.get("error"):
                errors += 1
            # Her INSERT kendi transaction'ini acip kapatir (append_result) -
            # eskiden tek-process'e ozgu bir threading.Lock ile korunan dosya
            # yazma yerine, PostgreSQL'in kendi satir-bazli yazma garantisine
            # dayanir; coklu process/worker'da da guvenlidir.
            append_result(file_label, record)
            completed += 1
            if completed % 25 == 0 or completed == len(todo):
                print(f"  [{label}] {completed}/{len(todo)} tamamlandi ({errors} hata)")
