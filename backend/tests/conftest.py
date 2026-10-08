import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from linescope.database import Database
from linescope.settings import Settings


@pytest.fixture
def db():
    dsn = os.getenv("LINESCOPE_TEST_DSN")
    if not dsn:
        pytest.skip("Set LINESCOPE_TEST_DSN for PostgreSQL integration tests")
    schema = "foundation_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        yield Database(Settings(dsn=make_conninfo(dsn, options=f"-c search_path={schema}")))
    finally:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
