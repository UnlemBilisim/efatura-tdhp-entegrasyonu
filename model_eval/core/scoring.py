"""Model ciktisini JSON'a cevirme ve ground-truth'a karsi skorlama."""

import json
import re

from .parsing import normalize_code3, normalize_dc, to_float


def extract_json_block(text):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        start = text.find(start_ch)
        end = text.rfind(end_ch)
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def parse_model_output(raw_text):
    parsed = extract_json_block(raw_text)
    if parsed is None:
        return None, "json_parse_error"

    if isinstance(parsed, dict):
        entries = parsed.get("entries")
        if entries is None:
            for v in parsed.values():
                if isinstance(v, list):
                    entries = v
                    break
    elif isinstance(parsed, list):
        entries = parsed
    else:
        entries = None

    if not isinstance(entries, list):
        return None, "no_entries_field"

    return entries, None


def score_entries(gt_pairs, entries):
    pred_pairs = set()
    balance = {"Borc": 0.0, "Alacak": 0.0}
    skipped = 0
    for e in entries or []:
        if not isinstance(e, dict):
            skipped += 1
            continue
        code3 = normalize_code3(e.get("account_code"))
        dc = normalize_dc(e.get("dc"))
        if not code3 or not dc:
            skipped += 1
            continue
        pred_pairs.add((code3, dc))
        balance[dc] += to_float(e.get("amount"))

    gt_codes = {c for c, _ in gt_pairs}
    pred_codes = {c for c, _ in pred_pairs}

    tp_pairs = gt_pairs & pred_pairs
    fp_pairs = pred_pairs - gt_pairs
    fn_pairs = gt_pairs - pred_pairs

    tp_codes = gt_codes & pred_codes
    fp_codes = pred_codes - gt_codes
    fn_codes = gt_codes - pred_codes

    return {
        "pred_pairs": sorted(pred_pairs),
        "tp_pairs": len(tp_pairs),
        "fp_pairs": len(fp_pairs),
        "fn_pairs": len(fn_pairs),
        "fp_pair_codes": [c for c, _ in fp_pairs],
        "fn_pair_codes": [c for c, _ in fn_pairs],
        "tp_codes": len(tp_codes),
        "fp_codes": len(fp_codes),
        "fn_codes": len(fn_codes),
        "fp_code_list": sorted(fp_codes),
        "fn_code_list": sorted(fn_codes),
        "exact_pair_match": pred_pairs == gt_pairs,
        "exact_code_match": pred_codes == gt_codes,
        "balanced": abs(balance["Borc"] - balance["Alacak"]) < 0.01 and len(pred_pairs) > 0,
        "borc_total": round(balance["Borc"], 2),
        "alacak_total": round(balance["Alacak"], 2),
        "n_pred_entries": len(entries or []),
        "n_skipped_entries": skipped,
    }
