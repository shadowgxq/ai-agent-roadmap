"""Offline SQL generation requires no credentials or running database."""

import os
from alembic import context
from sqlalchemy import create_engine


if context.is_offline_mode():
    context.configure(url="postgresql+psycopg://", literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    from dotenv import load_dotenv
    from support_agent.config.settings import PROJECT_ROOT
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    url = os.environ["SUPPORT_APP_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    with create_engine(url).connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
