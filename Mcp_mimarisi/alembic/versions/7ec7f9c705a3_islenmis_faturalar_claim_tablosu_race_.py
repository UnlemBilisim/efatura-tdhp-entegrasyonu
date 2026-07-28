"""islenmis_faturalar claim tablosu race condition duzeltmesi

GOREV_MIMARI_DUZELTME.md #1: faturayi_gecmise_kaydet()'teki "SELECT var mı
→ yoksa INSERT" deseni transaction/lock olmadan yapılıyordu, fatura_no
üzerinde de UNIQUE constraint yoktu — iki eşzamanlı istek aynı faturayı
gönderirse ikisi de "yok" görüp ikisi de yazabiliyordu. Bu tablo, PRIMARY
KEY garantisiyle atomik bir "kazanan tek istek" (claim) deseni kurar; asıl
kalem satırları fatura_no'ya UNIQUE koyulamayan gecmis_fatura_kalemleri'nde
kalmaya devam eder (bir fatura N kalem-satırı üretir, bu normaldir).

Revision ID: 7ec7f9c705a3
Revises: 9846b14dc658
Create Date: 2026-07-22 11:37:34.019086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ec7f9c705a3'
down_revision: Union[str, Sequence[str], None] = '9846b14dc658'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "islenmis_faturalar",
        sa.Column("fatura_no", sa.Text(), primary_key=True),
        sa.Column(
            "islenme_zamani",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("islenmis_faturalar")
