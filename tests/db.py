import os
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

CREATED_SCHEMAS = []
CREATED_DATABASES = []


def base_postgres_url():
    url = os.getenv("FAIRY_TEST_POSTGRES_URL")
    if not url:
        raise RuntimeError("FAIRY_TEST_POSTGRES_URL is required")
    return url


def postgres_url(_tmp_path=None):
    base = make_url(base_postgres_url())
    schema = "fairy_test_" + uuid4().hex
    with create_engine(base, pool_pre_ping=True).begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    CREATED_SCHEMAS.append(schema)
    query = dict(base.query)
    query["options"] = f"-csearch_path={schema}"
    return base.set(query=query).render_as_string(hide_password=False)


def postgres_database():
    base = make_url(base_postgres_url())
    name = "fairy_test_db_" + uuid4().hex
    admin = create_engine(base, pool_pre_ping=True, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    CREATED_DATABASES.append(name)
    return base.set(database=name).render_as_string(hide_password=False)


def cleanup_schemas():
    base = make_url(base_postgres_url())
    if CREATED_SCHEMAS:
        with create_engine(base, pool_pre_ping=True).begin() as connection:
            for schema in CREATED_SCHEMAS:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    if CREATED_DATABASES:
        admin = create_engine(base, pool_pre_ping=True, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            for database in CREATED_DATABASES:
                connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
                )
        admin.dispose()
    CREATED_SCHEMAS.clear()
    CREATED_DATABASES.clear()
