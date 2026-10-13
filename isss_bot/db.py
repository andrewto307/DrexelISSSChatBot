from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from isss_bot import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect() -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row)
    register_vector(conn)
    return conn


def create_schema() -> None:
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as conn:
        conn.execute(SCHEMA_PATH.read_text())
