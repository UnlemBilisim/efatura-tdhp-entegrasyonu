"""ilk sema nace_oranlari ve gecmis_fatura_kalemleri

Bu migration, projenin Alembic'ten ÖNCE elle (scripts/excel_to_postgres.py,
scripts/gecmis_faturalari_yukle.py içindeki CREATE TABLE IF NOT EXISTS) kurulan
mevcut şemasını olduğu gibi kaydeder — yeni bir şey EKLEMEZ, sadece mevcut
tabloları Alembic'in versiyon zincirine dahil eder. Production DB'de bu
tablolar zaten varsa bu migration'ı ÇALIŞTIRMA, bunun yerine
`alembic stamp head` kullan (bkz. docs/how-to/migration-calistirma.md) —
aksi halde CREATE TABLE mevcut tabloyla çakışıp hata verir (IF NOT EXISTS
burada bilinçli olarak KULLANILMADI: Alembic'in "bu migration çalıştı mı"
takibiyle "tablo zaten var mı" durumu birbirine karıştırılmamalı).

Revision ID: 9846b14dc658
Revises:
Create Date: 2026-07-22 11:37:03.793697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9846b14dc658'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "nace_oranlari",
        sa.Column("nace_kodu", sa.Text(), primary_key=True),
        sa.Column("kdv_0", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kdv_1", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kdv_10", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kdv_20", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("kaynak_satir", postgresql.JSONB(), nullable=True),
    )

    op.create_table(
        "gecmis_fatura_kalemleri",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("satici_vkn", sa.Text(), nullable=False),
        sa.Column("kalem_adi_normalize", sa.Text(), nullable=False),
        sa.Column("kalem_adi_orijinal", sa.Text(), nullable=False),
        sa.Column("oran", sa.Numeric(), nullable=False),
        sa.Column("istisna_kodu", sa.Text(), nullable=True),
        sa.Column("fatura_no", sa.Text(), nullable=False),
        sa.Column("fatura_tarihi", sa.Date(), nullable=True),
        sa.Column("kaynak_dosya", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_gecmis_eslesme",
        "gecmis_fatura_kalemleri",
        ["satici_vkn", "kalem_adi_normalize"],
    )


def downgrade() -> None:
    op.drop_index("idx_gecmis_eslesme", table_name="gecmis_fatura_kalemleri")
    op.drop_table("gecmis_fatura_kalemleri")
    op.drop_table("nace_oranlari")
