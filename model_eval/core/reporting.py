"""Sonuc depolama (PostgreSQL), resume icin done-id takibi, deney kolu
etiketleme ve ozet/rapor tablosu uretimi.

Onceki surum sonuclari `{output_dir}/{label}.jsonl` dosyalarina yaziyordu -
coklu kullanici/coklu process (HTTP servisi) senaryosunda ayni dosyaya
esizamanli yazma cakismasina yol aciyordu (bkz. mimari denetim, 2026-07-22).
Artik tum sonuclar `model_eval_sonuclar` tablosuna yazilir - `file_label`
(eski dosya adi karsiligi) + `invoice_id` ile sorgulanir, PostgreSQL'in kendi
transaction/concurrency garantileri kullanilir."""

import json
import re
from collections import Counter

from . import db


def result_label(label, with_glossary, tevkifat_hint=False, self_correct=False, rag=False, iade_hint=False):
    """Sonuc kaydinin etiketi - her deney kolu (glossary/tevkifat-hint/
    self-correct/rag/iade-hint) ayri bir file_label altinda saklansin diye
    son ek ekliyoruz, boylece farkli modlarin sonuclari birbirini hic ezmez."""
    suffix = ""
    if with_glossary:
        suffix += "+glossary"
    if tevkifat_hint:
        suffix += "+tevkifathint"
    if iade_hint:
        suffix += "+iadehint"
    if self_correct:
        suffix += "+selfcorrect"
    if rag:
        suffix += "+rag"
    return label + suffix


def sanitize_file_label(label):
    """Eski dosya-adi guvenligi kuralinin karsiligi - file_label serbest
    metin olarak DB'ye yazilabilir ama tutarlilik icin ayni normallestirme
    uygulanir (dosya sistemi kisitlamasi yok ama karisikligi onler)."""
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", label)


def load_done_ids(file_label):
    """Sadece basariyla skorlanmis (hatasiz) faturalari 'tamamlandi' sayar.
    Hata alan kayitlar (429/403/timeout vb.) done sayilmaz, bir sonraki
    calistirmada otomatik tekrar denenir. Bir invoice_id icin birden fazla
    kayit varsa (once hata, sonra basarili tekrar deneme) EN SON kayit
    (id DESC) esas alinir."""
    file_label = sanitize_file_label(file_label)
    query = """
        SELECT DISTINCT ON (invoice_id) invoice_id, is_error
        FROM model_eval_sonuclar
        WHERE file_label = %s
        ORDER BY invoice_id, id DESC
    """
    done = set()
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (file_label,))
            for invoice_id, is_error in cur.fetchall():
                if not is_error:
                    done.add(invoice_id)
    return done


def delete_results(file_label):
    """--overwrite icin: bu file_label altindaki tum onceki kayitlari siler."""
    file_label = sanitize_file_label(file_label)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM model_eval_sonuclar WHERE file_label = %s", (file_label,))
        conn.commit()


def append_result(file_label, record):
    """Bir fatura sonucunu tabloya ekler. Eskiden `out_f.write()` + write_lock
    ile korunan tek-dosyaya-append davranisinin karsiligi - burada satir
    ekleme dogrudan bir INSERT, PostgreSQL kendi ic kilitlemesini yapar,
    ayrica bir uygulama-ici lock'a gerek yok (cok process/worker'da da
    guvenli, tek process'e ozgu threading.Lock'un aksine)."""
    file_label = sanitize_file_label(file_label)
    invoice_id = record.get("invoice_id")
    is_error = bool(record.get("error"))
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_eval_sonuclar (file_label, invoice_id, record, is_error)
                VALUES (%s, %s, %s, %s)
                """,
                (file_label, invoice_id, json.dumps(record, ensure_ascii=False), is_error),
            )
        conn.commit()


def count_results(file_label):
    file_label = sanitize_file_label(file_label)
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT invoice_id) FROM model_eval_sonuclar WHERE file_label = %s",
                (file_label,),
            )
            return cur.fetchone()[0]


def _latest_records(file_label):
    """Her invoice_id icin EN SON kaydi (id DESC) doner - bir fatura hata
    alip sonra basarili tekrar denendiyse eski hata kaydi metrige girmez."""
    file_label = sanitize_file_label(file_label)
    query = """
        SELECT DISTINCT ON (invoice_id) record
        FROM model_eval_sonuclar
        WHERE file_label = %s
        ORDER BY invoice_id, id DESC
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (file_label,))
            return [row[0] for row in cur.fetchall()]


def safe_div(a, b):
    return a / b if b else 0.0


def summarize_model(file_label, label=None):
    records = _latest_records(file_label)

    total = len(records)
    hard_errors = [r for r in records if r.get("error") in ("json_parse_error", "no_entries_field") or (r.get("error") and "tp_pairs" not in r)]
    scored = [r for r in records if "tp_pairs" in r]

    tp = sum(r["tp_pairs"] for r in scored)
    fp = sum(r["fp_pairs"] for r in scored)
    fn = sum(r["fn_pairs"] for r in scored)
    ctp = sum(r["tp_codes"] for r in scored)
    cfp = sum(r["fp_codes"] for r in scored)
    cfn = sum(r["fn_codes"] for r in scored)

    micro_p = safe_div(tp, tp + fp)
    micro_r = safe_div(tp, tp + fn)
    micro_f1 = safe_div(2 * micro_p * micro_r, micro_p + micro_r)

    code_p = safe_div(ctp, ctp + cfp)
    code_r = safe_div(ctp, ctp + cfn)
    code_f1 = safe_div(2 * code_p * code_r, code_p + code_r)

    exact_pair_rate = safe_div(sum(1 for r in scored if r.get("exact_pair_match")), len(scored))
    exact_code_rate = safe_div(sum(1 for r in scored if r.get("exact_code_match")), len(scored))
    balanced_rate = safe_div(sum(1 for r in scored if r.get("balanced")), len(scored))
    avg_latency = safe_div(sum(r.get("latency_s", 0) for r in records if "latency_s" in r), sum(1 for r in records if "latency_s" in r))

    fn_counter = Counter()
    fp_counter = Counter()
    for r in scored:
        fn_counter.update(r.get("fn_code_list", []))
        fp_counter.update(r.get("fp_code_list", []))

    # "Teknik hata" (n_hard_errors) API/parse basarisizligidir - modelin hic
    # cevap veremedigi durumlar. "Kod hatasi" ise TEKNIK OLARAK cevap verdigi
    # ama YANLIS hesap kodu/yon urettigi durumlarin sayisidir (fp+fn toplami,
    # yani halusinasyon + kacirma). Ikisi farkli seyler - biri altyapi
    # saglamligini, digeri muhasebe dogrulugunu olcer.
    code_mistake_count = fp + fn
    invoices_with_mistake = sum(1 for r in scored if not r.get("exact_pair_match"))

    return {
        "model": label or file_label,
        "n_total": total,
        "n_scored": len(scored),
        "n_hard_errors": len(hard_errors),
        "code_mistake_count": code_mistake_count,
        "invoices_with_mistake": invoices_with_mistake,
        "pair_precision": round(micro_p, 4),
        "pair_recall": round(micro_r, 4),
        "pair_f1": round(micro_f1, 4),
        "code_precision": round(code_p, 4),
        "code_recall": round(code_r, 4),
        "code_f1": round(code_f1, 4),
        "exact_pair_match_rate": round(exact_pair_rate, 4),
        "exact_code_match_rate": round(exact_code_rate, 4),
        "balanced_entry_rate": round(balanced_rate, 4),
        "avg_latency_s": round(avg_latency, 3),
        "most_missed_codes": fn_counter.most_common(10),
        "most_hallucinated_codes": fp_counter.most_common(10),
    }


def print_summary_table(summaries):
    headers = [
        "model", "n", "pair_F1", "code_F1", "exact_pair%", "exact_code%", "balanced%",
        "kod_hatasi", "hatali_fatura", "teknik_hata", "avg_lat_s",
    ]
    rows = []
    for s in summaries:
        rows.append([
            s["model"],
            str(s["n_scored"]),
            f"{s['pair_f1']:.3f}",
            f"{s['code_f1']:.3f}",
            f"{s['exact_pair_match_rate']*100:.1f}",
            f"{s['exact_code_match_rate']*100:.1f}",
            f"{s['balanced_entry_rate']*100:.1f}",
            str(s["code_mistake_count"]),
            f"{s['invoices_with_mistake']}/{s['n_scored']}",
            str(s["n_hard_errors"]),
            f"{s['avg_latency_s']:.2f}",
        ])
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    def fmt_row(row):
        return " | ".join(c.ljust(w) for c, w in zip(row, widths))
    print("\n" + fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt_row(r))

    for s in summaries:
        print(f"\n[{s['model']}] en cok kacirilan kodlar: {s['most_missed_codes']}")
        print(f"[{s['model']}] en cok halusinasyon kodlar: {s['most_hallucinated_codes']}")
