"""sirket_bilgileri tablosu - nace kodlari onboarding'de saklanir

2026-09-29, kullanici karari: dis ekip her /fatura/isle istegine kendi
NACE kodlarini eklemek zorunda kalmasin (hata riski - unutulursa outbox
faturada KDV on filtresi hic calismaz, bkz. kalem_nace_esleme.py). NACE
kodlari artik onboarding sirasinda BIR KERE kaydedilir, /fatura/isle'daki
satici_nace_kodlari alani opsiyonel kalmaya devam eder ama artik "ezber
degerdir" - bos gelirse burada kayitli NACE kullanilir (bkz. api.py).

Fatura XML'i NACE kodu TASIMAZ (bkz. Mcp_mimarisi/CLAUDE.md "Kritik
gercekler") - bu, mimarinin zaten ongordugu "NACE ayri bir kaynaktan
gelecek" ilkesiyle CELISMEZ, sadece o kaynagin "her istekte dis ekip"
yerine "onboarding'de bir kere biz" olmasini saglar.

Bu tablo SADECE public semada yasar (nace_oranlari ile ayni desen, bkz.
9846b14dc658) - VKN zaten birincil anahtar oldugu icin tenant izolasyonuna
ihtiyac yok, tum sirketleri tek tabloda gormek bakim/onboarding icin daha
pratik. Migration bir tenant semasinda (ALEMBIC_TENANT_SCHEMA set edilmis)
calistirildiginda CREATE atlanir - aksi halde HER tenant onboarding'inde
migration bu tabloyu KENDI (tenant_<vkn>) semasinda tekrar olusturmaya
calisir, bu hem gereksizdir hem "hangi VKN'nin sirket_bilgileri kaydi
nerede" sorusunu belirsizlestirir (2026-09-29, ilk denemede TAM BU HATA
yasandi - tablo yanlislikla tenant_1122334455 semasinda olustu, public'te
degil, gecici DB ile test edilirken fark edildi).

UYARI (2026-09-30, ikinci mock musteri onboarding'inde fark edildi): Bu
migration `public` semasina karsi FIILEN HIC calistirilmadi - projede
Alembic sadece tenant onboarding akisinda (ALEMBIC_TENANT_SCHEMA ile)
calistiriliyor (bkz. tenant_onboarding.py), public icin ayri bir
`alembic upgrade` cagrisi yok ve `public.alembic_version` tablosu hic
olusmadi. Diger public tablolari (nace_oranlari, api_anahtarlari, vb.)
bu yuzden runtime'da kendiliginden `CREATE TABLE IF NOT EXISTS` ile var
oluyor - gercek kaynak bu migration DEGIL. Ayni tutarsizliga dusmemek
icin `sirket_bilgileri.py`'ye de ayni lazy-create deseni eklendi
(`_tabloyu_hazirla()`) - asil calisan kod odur, bu migration dosyasi
sadece tarihsel/belgeleme amacli kalir.

Revision ID: 56d739edb09d
Revises: 7ec7f9c705a3
Create Date: 2026-09-29 16:49:30.607340

"""
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '56d739edb09d'
down_revision: Union[str, Sequence[str], None] = '7ec7f9c705a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    if os.environ.get("ALEMBIC_TENANT_SCHEMA"):
        return
    op.create_table(
        "sirket_bilgileri",
        sa.Column("vkn", sa.Text(), primary_key=True),
        sa.Column("nace_kodlari", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column(
            "guncellenme_zamani",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="public",
    )


def downgrade() -> None:
    """Downgrade schema."""
    if os.environ.get("ALEMBIC_TENANT_SCHEMA"):
        return
    op.drop_table("sirket_bilgileri", schema="public")
