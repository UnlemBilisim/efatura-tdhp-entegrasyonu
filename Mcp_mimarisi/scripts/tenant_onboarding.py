"""Yeni bir şirketi (tenant) sisteme kaydeder (2026-07-30, çoklu şirket geçişi).

Adımlar:
1. VKN formatını doğrular (10 hane, sayısal).
2. `CREATE SCHEMA IF NOT EXISTS tenant_<vkn>`.
3. Alembic migration'larını bu şema üzerinde çalıştırır (ALEMBIC_TENANT_SCHEMA
   env var'ı ile) — `gecmis_fatura_kalemleri`/`islenmis_faturalar` oluşur,
   `nace_oranlari` (paylaşılan mevzuat referansı) ATLANIR, bkz. migration
   9846b14dc658'in upgrade() koşulu.
4. model_eval'ın `model_eval_sonuclar` tablosunu aynı şemada oluşturur
   (`model_eval/core/db.py::_SCHEMA`'yı tenant search_path'iyle çalıştırarak).
5. Özet rapor yazdırır.

Bu script sadece ŞEMA/TABLO OLUŞTURUR, veri KOPYALAMAZ — mevcut bir şirketin
(Aküzülü gibi) public şemadaki verisini taşımak için bkz.
scripts/akyuzlu_public_to_tenant_gocu.py (ayrı, tek seferlik script).

Çalıştırma (Mcp_mimarisi kökünden):

    DATABASE_URL=postgresql://user:pass@localhost:5432/efatura_kdv \\
        python3 scripts/tenant_onboarding.py --vkn 1234567890
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

from model_eval_yolu import model_eval_yolunu_ekle

SCRIPT_DIR = Path(__file__).resolve().parent
MCP_MIMARISI_DIR = SCRIPT_DIR.parent

sys.path.insert(0, str(MCP_MIMARISI_DIR / "src"))  # efatura_kdv.sirket_bilgileri icin

model_eval_yolunu_ekle()
from core.db import _SCHEMA as MODEL_EVAL_SCHEMA_SQL  # noqa: E402 (path once model_eval_yolunu_ekle() calls)


def _vkn_dogrula(vkn: str) -> str:
    if not vkn or not vkn.isdigit() or len(vkn) != 10:
        raise ValueError(f"Geçersiz VKN: {vkn!r} — 10 haneli sayısal olmalı")
    return vkn


def _sema_olustur(database_url: str, sema: str) -> None:
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(sema)))
        conn.commit()
    finally:
        conn.close()


def _alembic_migration_calistir(database_url: str, sema: str) -> None:
    env = dict(os.environ, DATABASE_URL=database_url, ALEMBIC_TENANT_SCHEMA=sema)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(MCP_MIMARISI_DIR),
        env=env,
        check=True,
    )


def _model_eval_semasini_olustur(database_url: str, sema: str) -> None:
    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(sema)))
            cur.execute(MODEL_EVAL_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def onboard_et(vkn: str, database_url: str, nace_kodlari: list[str] | None = None) -> str:
    vkn = _vkn_dogrula(vkn)
    sema = f"tenant_{vkn}"

    print(f"[1/5] Şema oluşturuluyor: {sema}")
    _sema_olustur(database_url, sema)

    print(f"[2/5] Alembic migration'ları çalıştırılıyor (ALEMBIC_TENANT_SCHEMA={sema})")
    _alembic_migration_calistir(database_url, sema)

    print("[3/5] model_eval_sonuclar tablosu oluşturuluyor")
    _model_eval_semasini_olustur(database_url, sema)

    print("[4/5] NACE kod(lar)ı kaydediliyor")
    if nace_kodlari:
        from efatura_kdv.sirket_bilgileri import nace_kodlarini_kaydet

        nace_kodlarini_kaydet(vkn, nace_kodlari, database_url=database_url)
        print(f"  Kaydedildi: {nace_kodlari}")
    else:
        print(
            "  Uyarı: NACE kodu verilmedi — outbox faturalarda KDV ön filtresi "
            "çalışmayacak, sonradan eklemek için: --nace <kod1> --nace <kod2> "
            "ile tekrar çalıştırın (upsert, veri kaybetmez)."
        )

    print(f"[5/5] Tamamlandı — {sema} şeması hazır.")
    print(
        "Not: bu şirket için mizan ve RAG geçmişi henüz YOK olabilir. "
        f"Mizanı yüklemek için: python3 model_eval/mizan_excel_yukle.py --vkn {vkn} "
        "--excel <mizan.xlsx>. RAG yoksa sistem emsalsiz tahmin yoluna düşer."
    )
    return sema


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vkn", required=True, help="Şirketin VKN'si (10 hane)")
    ap.add_argument(
        "--nace", action="append", default=[], dest="nace_kodlari",
        help="Şirketin NACE kodu (tekrarlanabilir, örn. --nace 25.40.04 --nace 28.22.10). "
             "KDV ön filtresi için gerekli — verilmezse outbox faturalarda ön filtre çalışmaz.",
    )
    args = ap.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL env var tanımlı değil.", file=sys.stderr)
        sys.exit(1)

    onboard_et(args.vkn, database_url, nace_kodlari=args.nace_kodlari)


if __name__ == "__main__":
    main()
