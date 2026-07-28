"""model_eval'ı import edebilmek için ortak yol yardımcısı.

model_eval bir pip paketi olarak kurulmadığı (aynı workspace'te duran bir
klasör) için, ondaki `core.*` modüllerini import etmeden önce dizininin
`sys.path`'e eklenmesi gerekir. Bu desen önceden `yon_tespiti.py` ve
`model_eval_koprusu.py`'de ayrı ayrı (üç kez) tekrarlanıyordu — tek kaynağa
çekildi (2026-07-23, kod tekrarı temizliği). model_eval'ın koduna dokunmaz,
sadece entegrasyon katmanının onu bulabilmesini sağlar.
"""

from __future__ import annotations

import sys
from pathlib import Path

MODEL_EVAL_DIR = Path(__file__).resolve().parent.parent / "model_eval"


def model_eval_yolunu_ekle() -> None:
    """model_eval dizinini (yoksa) sys.path'in başına ekler — `from core...`
    import'larının çalışabilmesi için. Idempotent: zaten ekliyse tekrar
    eklemez, birden fazla çağrılması güvenlidir."""
    if str(MODEL_EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(MODEL_EVAL_DIR))
