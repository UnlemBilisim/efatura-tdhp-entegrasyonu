import os
from logging.config import fileConfig

import sqlalchemy as sa
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Bağlantı adresi DATABASE_URL env var'ından okunur — projenin geri
# kalanıyla (nace_kural_kontrolu.py, gecmis_kontrol.py) aynı desen,
# alembic.ini'ye sabit/gizli bağlantı bilgisi yazılmaz.
_database_url = os.environ.get("DATABASE_URL")
if _database_url:
    config.set_main_option("sqlalchemy.url", _database_url)

# ALEMBIC_TENANT_SCHEMA (2026-07-30, çoklu şirket geçişi): verilirse
# migration'lar public'e değil bu şemaya uygulanır — şema önce oluşturulur,
# search_path bu şemaya çevrilir, alembic_version da bu şema içinde tutulur
# (her tenant kendi migration geçmişini ayrı takip eder). Verilmezse
# (varsayılan, boş) davranış DEĞİŞMEZ: migration'lar hep public'e gider.
#
# Şema adı SQL identifier'dır, parametrize edilemez (f-string ile gömülüyor,
# aşağıda) — bu yüzden burada sıkı doğrulanır (sadece harf/rakam/altçizgi).
_tenant_schema = os.environ.get("ALEMBIC_TENANT_SCHEMA")
if _tenant_schema and not all(c.isalnum() or c == "_" for c in _tenant_schema):
    raise ValueError(f"ALEMBIC_TENANT_SCHEMA geçersiz karakter içeriyor: {_tenant_schema!r}")

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if _tenant_schema:
            connection.execute(sa.text(f'CREATE SCHEMA IF NOT EXISTS "{_tenant_schema}"'))
            connection.execute(sa.text(f'SET search_path TO "{_tenant_schema}", public'))
            connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=_tenant_schema,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
