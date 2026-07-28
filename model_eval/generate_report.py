#!/usr/bin/env python3
"""Bir sonuc .jsonl dosyasindan (evaluate_models.py --data-format xml ciktisi)
okunakli bir .md raporu uretir: her fatura icin karsi taraf/tarih/tip/tutar ozeti
ve kullanilan TDHP hesap kodlari + adlari + Borc/Alacak tutarlari tablosu.

Kullanim:
    cd model_eval
    .venv/bin/python3 generate_report.py results/<dosya>.jsonl <cikti.md>

Ornek:
    .venv/bin/python3 generate_report.py \\
        results/gemma4_31b-cloud_tevkifathint_iadehint_selfcorrect_rag.jsonl \\
        yeni_faturalar_tdhp.md
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import TDHP_GLOSSARY
from core.scoring import extract_json_block


def extract_field(prompt, label):
    m = re.search(re.escape(label) + r": (.+)", prompt)
    return m.group(1).strip() if m else "?"


def parse_entries(raw):
    parsed = extract_json_block(raw)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        entries = parsed.get("entries")
        if entries is None:
            for v in parsed.values():
                if isinstance(v, list):
                    entries = v
                    break
        return entries or []
    return []


def load_latest_records(jsonl_path):
    """Ayni invoice_id icin birden fazla satir varsa (hata + retry basarisi
    gibi) sadece EN SON kaydi tutar."""
    records = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            inv_id = rec.get("invoice_id")
            if inv_id is None:
                continue
            records[inv_id] = rec
    return records


def build_report(jsonl_path, title=None):
    records = load_latest_records(jsonl_path)
    errors = {inv_id: r for inv_id, r in records.items() if r.get("error")}
    ok_records = {inv_id: r for inv_id, r in records.items() if not r.get("error")}

    lines = []
    lines.append(f"# {title or 'Muhasebe Kayitlari'}\n")
    lines.append(f"**Kaynak:** `{jsonl_path}`\n")
    lines.append(f"**Toplam fatura:** {len(records)} ({len(ok_records)} basarili, {len(errors)} hatali)\n")
    lines.append(
        "**Not:** Bu tablo bir TAHMIN raporudur - model, ground-truth "
        "(gercek muhasebe kaydi) olmadan tahmin uretmistir. Gercek muhasebeye "
        "islemeden once kontrol edilmelidir.\n"
    )
    lines.append("---\n")

    if errors:
        lines.append("## Hatali Faturalar (islenemedi)\n")
        for inv_id, rec in sorted(errors.items()):
            lines.append(f"- **{inv_id}**: {rec['error']}")
        lines.append("")

    for inv_id, rec in sorted(ok_records.items()):
        prompt = rec.get("sent_user_prompt", "")
        karsi_taraf_m = re.search(r"Karsi Taraf: (.+?) \(VKN", prompt)
        karsi_taraf = karsi_taraf_m.group(1).strip() if karsi_taraf_m else "?"
        tarih = extract_field(prompt, "Fatura Tarihi")
        tip = extract_field(prompt, "Fatura Tipi")
        para_birimi = extract_field(prompt, "Para Birimi")
        tutar = extract_field(prompt, "Odenecek/Alinacak Tutar")
        direction = rec.get("direction", "?")

        entries = parse_entries(rec.get("raw_response", ""))
        tot_borc = sum(e["amount"] for e in entries if e.get("dc") == "Borc")
        tot_alacak = sum(e["amount"] for e in entries if e.get("dc") == "Alacak")
        balanced = abs(tot_borc - tot_alacak) < 0.01
        denge_isareti = "OK" if balanced else "HATA"

        lines.append(f"## {inv_id} - {karsi_taraf}\n")
        lines.append(f"- **Tarih:** {tarih}")
        lines.append(f"- **Tip:** {tip} ({direction})")
        lines.append(f"- **Para Birimi:** {para_birimi}")
        lines.append(f"- **Tutar:** {tutar} {para_birimi}")
        lines.append(f"- **Dengeli:** {denge_isareti} (Borc={tot_borc:,.2f} / Alacak={tot_alacak:,.2f})\n")

        lines.append("| Hesap | Borc | Alacak |")
        lines.append("|---|---|---|")
        for e in entries:
            code = e.get("account_code", "?")
            amount = e.get("amount", 0)
            dc = e.get("dc")
            ad = TDHP_GLOSSARY.get(code, "(bilinmeyen kod)")
            borc_col = f"{amount:,.2f} {para_birimi}" if dc == "Borc" else "-"
            alacak_col = f"{amount:,.2f} {para_birimi}" if dc == "Alacak" else "-"
            lines.append(f"| {code} {ad} | {borc_col} | {alacak_col} |")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    jsonl_path = sys.argv[1]
    out_path = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else None

    report = build_report(jsonl_path, title=title)
    Path(out_path).write_text(report, encoding="utf-8")
    print(f"yazildi: {out_path}")


if __name__ == "__main__":
    main()
