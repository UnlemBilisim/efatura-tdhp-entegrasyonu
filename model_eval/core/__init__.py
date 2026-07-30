"""TDHP muhasebe degerlendirme paketi.

Alt moduller:
    constants   - sabitler (yollar, TDHP sozlugu, system prompt)
    parsing     - fatura ayristirma (JSON ground-truth + ham UBL XML) ve
                  sayisal alan normalizasyonu
    prompting   - kullanici prompt'u ve deterministik ipucu (iade/tevkifat)
                  olusturma
    scoring     - model ciktisini JSON'a cevirme ve ground-truth'a karsi
                  skorlama
    providers   - Ollama icin API cagrilari (2026-07-29: OpenAI/Anthropic/
                  Google/OpenAI-uyumlu destegi kaldirildi, sadece Ollama
                  kullanilir)
    reporting   - sonuc dosyasi yollari, resume, ozet/rapor tablosu
    runner      - tek bir model spec'i icin fatura kumesini isleyen
                  orkestrasyon fonksiyonu (run_model)
    cli         - argparse + main() giris noktasi

Geriye donuk kullanim kolayligi icin en sik cagrilan isimler burada da
re-export edilir (orn. `import core as em; em.to_float(...)`), ama yeni
kod dogrudan ilgili alt moduluu import etmelidir (orn. `from core.parsing
import to_float`).
"""

from .constants import (
    DEFAULT_DATA_DIR,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_OWN_VKN,
    DEFAULT_SECTOR,
    SCRIPT_DIR,
    SYSTEM_PROMPT,
    TDHP_GLOSSARY,
    UBL_NS,
)
from .parsing import (
    load_invoice_paths,
    normalize_code3,
    normalize_dc,
    parse_invoice,
    parse_invoice_xml,
    render_tax_line,
    to_float,
)
from .prompting import (
    build_direction_text,
    build_glossary_system_prompt,
    build_user_prompt,
    compute_iade_hint,
    compute_tevkifat_hint,
)
from .providers import (
    KNOWN_PROVIDERS,
    PERMANENT_HTTP_ERRORS,
    build_balance_correction_request,
    build_correction_messages,
    call_model,
    call_ollama,
    call_ollama_messages,
    parse_model_spec,
    self_correct_ollama,
)
from .reporting import (
    append_result,
    count_results,
    delete_results,
    load_done_ids,
    print_summary_table,
    result_label,
    safe_div,
    sanitize_file_label,
    summarize_model,
)
from .runner import run_model
from .scoring import extract_json_block, parse_model_output, score_entries
from .cli import main

__all__ = [
    "DEFAULT_DATA_DIR", "DEFAULT_OLLAMA_HOST", "DEFAULT_OUTPUT_DIR",
    "DEFAULT_OWN_VKN", "DEFAULT_SECTOR", "SCRIPT_DIR", "SYSTEM_PROMPT",
    "TDHP_GLOSSARY", "UBL_NS",
    "load_invoice_paths", "normalize_code3", "normalize_dc", "parse_invoice",
    "parse_invoice_xml", "render_tax_line", "to_float",
    "build_direction_text", "build_glossary_system_prompt",
    "build_user_prompt", "compute_iade_hint", "compute_tevkifat_hint",
    "KNOWN_PROVIDERS", "PERMANENT_HTTP_ERRORS",
    "build_balance_correction_request", "build_correction_messages",
    "call_model", "call_ollama", "call_ollama_messages",
    "parse_model_spec", "self_correct_ollama",
    "append_result", "count_results", "delete_results", "load_done_ids",
    "print_summary_table", "result_label", "safe_div", "sanitize_file_label",
    "summarize_model",
    "run_model",
    "extract_json_block", "parse_model_output", "score_entries",
    "main",
]
