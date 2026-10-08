from contextlib import contextmanager
from hashlib import sha256
from importlib.resources import files

import psycopg
from psycopg.rows import dict_row

MIGRATION_LOCK = 127987


class Database:
    def __init__(self, settings):
        self.settings = settings

    def connect(self):
        connection = psycopg.connect(
            self.settings.dsn,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=self.settings.connect_seconds,
            application_name="linescope",
        )
        try:
            connection.execute(
                "SELECT set_config('statement_timeout',%s,false)",
                (str(self.settings.statement_ms),),
            )
            connection.execute(
                "SELECT set_config('lock_timeout',%s,false)", (str(self.settings.lock_ms),)
            )
        except Exception:
            connection.close()
            raise
        return connection

    @contextmanager
    def transaction(self):
        with self.connect() as connection, connection.transaction():
            yield connection

    def check(self):
        with self.transaction() as connection:
            return connection.execute("SELECT 1 AS healthy").fetchone()["healthy"] == 1

    def migrate(self, sources=None):
        if sources is None:
            directory = files("linescope").joinpath("migrations")
            sources = [
                (p.name, p.read_text(encoding="utf-8"))
                for p in directory.iterdir()
                if p.name.endswith(".sql")
            ]
        if len({name for name, _ in sources}) != len(sources):
            raise ValueError("Duplicate migration names")
        applied = []
        with self.transaction() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK,))
            connection.execute("""CREATE TABLE IF NOT EXISTS schema_migration(
                version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""")
            for name, script in sorted(sources):
                checksum = sha256(script.encode("utf-8")).hexdigest()
                existing = connection.execute(
                    "SELECT checksum FROM schema_migration WHERE version=%s", (name,)
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise ValueError(f"Applied migration was modified: {name}")
                    continue
                connection.execute(script)
                connection.execute(
                    "INSERT INTO schema_migration(version,checksum) VALUES(%s,%s)", (name, checksum)
                )
                applied.append(name)
        return applied
