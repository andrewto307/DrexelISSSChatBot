import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from isss_bot import config


def connect(database_url: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(database_url or config.DATABASE_URL, row_factory=dict_row)
    register_vector(conn)
    return conn


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)
    conn.commit()


def create_pool(database_url: str | None = None, max_size: int = 10) -> ConnectionPool:
    return ConnectionPool(
        database_url or config.DATABASE_URL,
        kwargs={"row_factory": dict_row},
        configure=_configure,
        min_size=1,
        max_size=max_size,
        open=True,
    )
