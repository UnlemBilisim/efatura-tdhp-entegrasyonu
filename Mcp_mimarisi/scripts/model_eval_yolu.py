"""model_eval'ı import edebilmek için ortak yol yardımcısı (2026-08-05,
kod-tekrarı temizliği kararıyla eklendi — bkz. kök CLAUDE.md).

model_eval bir pip paketi olarak kurulmadığı (aynı workspace'te duran bir
klasör) için, ondaki `core.*` modüllerini import etmeden önce dizininin
`sys.path`'e eklenmesi gerekir. Aynı desen `entegrasyon/model_eval_yolu.py`'de
de var (ayrı, çünkü entegrasyon ve Mcp_mimarisi birbirinden bağımsız
çalışabilir, ikisinin de kendi kopyası olması kasıtlı) — model_eval'ın
koduna dokunmaz, sadece Mcp_mimarisi tarafının onu bulabilmesini sağlar.
"""

from __future__ import annotations

import sys
from pathlib import Path

MODEL_EVAL_DIR = Path(__file__).resolve().parent.parent.parent / "model_eval"


def model_eval_yolunu_ekle() -> None:
    """model_eval dizinini (yoksa) sys.path'in başına ekler — `from core...`
    import'larının çalışabilmesi için. Idempotent: zaten ekliyse tekrar
    eklemez, birden fazla çağrılması güvenlidir."""
    if str(MODEL_EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(MODEL_EVAL_DIR))
