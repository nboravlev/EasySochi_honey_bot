import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

from db.db import Base

from db.models import *

import os

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Postgres credentials are not set in environment variables")

DATABASE_URL = DATABASE_URL
# Загрузка .env


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    if hasattr(object, 'schema') and object.schema == 'cron':
        return False
    return True

config = context.config
config.set_main_option(
    "sqlalchemy.url",
     DATABASE_URL
     )

# Логгинг
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata
print("Detected tables:", list(Base.metadata.tables.keys()))
target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
