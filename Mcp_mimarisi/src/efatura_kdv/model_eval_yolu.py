"""model_eval'ı import edebilmek için ortak yol yardımcısı (2026-10-01,
tenant izolasyonu açığını kapatmak için eklendi — bkz. TODO.md).

model_eval bir pip paketi olarak kurulmadığı (aynı workspace'te duran bir
klasör) için, ondaki `core.*` modüllerini import etmeden önce dizininin
`sys.path`'e eklenmesi gerekir. Aynı desen `entegrasyon/model_eval_yolu.py`
ve `Mcp_mimarisi/scripts/model_eval_yolu.py`'de de var (üçü de ayrı — her
bileşenin kendi kopyası olması kasıtlı, bkz. oradaki docstring'ler); bu
kopya `src/efatura_kdv/` paketinin (canlı API süreci) kullanımı için, dosya
derinliği farklı olduğundan (`scripts/`'tekinden bir seviye daha derin)
`MODEL_EVAL_DIR` hesabı ayrı tutuldu."""

from __future__ import annotations

import sys
from pathlib import Path

MODEL_EVAL_DIR = Path(__file__).resolve().parents[3] / "model_eval"


def model_eval_yolunu_ekle() -> None:
    """model_eval dizinini (yoksa) sys.path'in başına ekler — `from core...`
    import'larının çalışabilmesi için. Idempotent: zaten ekliyse tekrar
    eklemez, birden fazla çağrılması güvenlidir."""
    if str(MODEL_EVAL_DIR) not in sys.path:
        sys.path.insert(0, str(MODEL_EVAL_DIR))
