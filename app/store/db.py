"""Connection, transaction and audit helpers. Only this module opens SQLite."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schema import DDL, SCHEMA_VERSION


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(raw, default=None):
    if raw in (None, ""):
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


class Store:
    def __init__(self, path):
        self.path = ":memory:" if str(path) == ":memory:" else Path(path)
        if self.path != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            if self.path != ":memory:":
                db.execute("PRAGMA journal_mode=WAL")
            db.executescript(DDL)
            db.execute("INSERT INTO meta(key,value) VALUES('schema_version',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(SCHEMA_VERSION),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        """Write transaction. Callers nest reads inside it, never another transaction."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def audit(db, command, entity_type, entity_id, action, payload=None, revision=0, actor=""):
        db.execute(
            "INSERT INTO audit(command,entity_type,entity_id,action,payload,revision,actor,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (command, entity_type, str(entity_id), action, dumps(payload or {}), revision, actor, now()),
        )


def row(db, sql, params=()):
    found = db.execute(sql, params).fetchone()
    return dict(found) if found else None


def rows(db, sql, params=()):
    return [dict(item) for item in db.execute(sql, params)]


def one(db, sql, params=(), default=None):
    found = db.execute(sql, params).fetchone()
    return found[0] if found else default


def insert(db, table, **fields):
    fields.setdefault("created_at", now())
    columns = ",".join(fields)
    marks = ",".join("?" for _ in fields)
    cursor = db.execute(f"INSERT INTO {table}({columns}) VALUES({marks})", tuple(fields.values()))
    return cursor.lastrowid


def update(db, table, row_id, **fields):
    if not fields:
        return
    assignments = ",".join(f"{key}=?" for key in fields)
    db.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*fields.values(), row_id))
