from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path(os.getenv("FACTCHECK_CACHE_PATH", "outputs/factcheck_runs/factcheck_cache.sqlite3"))


class SQLiteCache:
    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS factcheck_cache (
                    namespace TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(namespace, cache_key)
                )
                """
            )

    def get(self, namespace: str, key: str) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM factcheck_cache WHERE namespace = ? AND cache_key = ?",
                (namespace, key),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except Exception:
            return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO factcheck_cache(namespace, cache_key, payload, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(namespace, cache_key) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (namespace, key, payload, datetime.utcnow().isoformat(timespec="seconds")),
            )


_DEFAULT_CACHE = SQLiteCache()


def get_cache() -> SQLiteCache:
    return _DEFAULT_CACHE
