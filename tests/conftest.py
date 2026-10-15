import os

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from isss_bot import config, db, migrate


@pytest.fixture(scope="session")
def database_url() -> str:
    if os.environ.get("TEST_DATABASE_URL"):
        return os.environ["TEST_DATABASE_URL"]
    name = f"{conninfo_to_dict(config.DATABASE_URL).get('dbname', 'isss')}_test"
    try:
        with psycopg.connect(
            make_conninfo(config.DATABASE_URL, dbname="postgres"), autocommit=True, connect_timeout=3
        ) as admin:
            if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.OperationalError:
        pytest.skip("Postgres is not running; start it with `docker compose up -d`")
    return make_conninfo(config.DATABASE_URL, dbname=name)


@pytest.fixture(scope="session")
def migrated_database_url(database_url) -> str:
    migrate.apply(database_url)
    return database_url


@pytest.fixture
def conn(migrated_database_url):
    connection = db.connect(migrated_database_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
