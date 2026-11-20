"""PostgreSQL access. Spatial work happens in SQL (PostGIS / pgRouting), not in Python."""
import psycopg
from psycopg.rows import dict_row

from smartcity import config


def connect() -> psycopg.Connection:
    return psycopg.connect(config.DATABASE_URL, autocommit=True, row_factory=dict_row)
