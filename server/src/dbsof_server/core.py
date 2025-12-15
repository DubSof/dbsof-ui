from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

INSTANCE_ID = "demo"
INSTANCE_NAME = "Demo Instance"
INSTANCE_ALIASES = {INSTANCE_ID, "default", INSTANCE_NAME, INSTANCE_NAME.lower()}

# in-memory stores
QUERY_HISTORY: Dict[str, List[Dict[str, Any]]] = {}
AI_TASKS: Dict[str, Dict[str, Any]] = {}
AI_TASK_LOCK = threading.Lock()


def db_path(db_name: str) -> Path:
    safe = "".join(c for c in db_name if c.isalnum() or c in ("_", "-")).strip()
    if not safe:
        raise ValueError("Invalid database name")
    return DATA_DIR / f"{safe}.db"


def ensure_db(db_name: str) -> Path:
    path = db_path(db_name)
    if not path.exists():
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS __meta__ (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        conn.close()
    return path


def connect(db_name: str) -> sqlite3.Connection:
    path = ensure_db(db_name)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def list_databases() -> List[Dict[str, Any]]:
    dbs: List[Dict[str, Any]] = []
    for file in DATA_DIR.glob("*.db"):
        dbs.append({"name": file.stem, "lastMigration": None})
    if not dbs:
        conn = connect("main")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS movies (id INTEGER PRIMARY KEY, title TEXT, release_year INTEGER)"
        )
        existing = conn.execute("SELECT COUNT(*) AS c FROM movies").fetchone()[0]
        if existing == 0:
            conn.execute(
                "INSERT INTO movies (title, release_year) VALUES "
                "('Ant-Man', 2015), "
                "('Avengers: Age of Ultron', 2015)"
            )
        conn.commit()
        conn.close()
        dbs.append({"name": "main", "lastMigration": None})
    return dbs


def record_history(db: str, query: str, duration_ms: float, status: str):
    history = QUERY_HISTORY.setdefault(db, [])
    history.insert(
        0,
        {
            "id": str(uuid.uuid4()),
            "query": query,
            "params": {},
            "status": status,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "durationMs": duration_ms,
        },
    )
    if len(history) > 200:
        del history[200:]


def resolve_instance_id(raw_id: str) -> str | None:
    candidate = raw_id.replace("%20", " ")
    return INSTANCE_ID if candidate in INSTANCE_ALIASES else None


def sql_schema(conn: sqlite3.Connection) -> Dict[str, Any]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = [r["name"] for r in cur.fetchall()]
    types = []
    for table in tables:
        cols_cur = conn.execute(f"PRAGMA table_info('{table}')")
        cols = cols_cur.fetchall()
        types.append(
            {
                "name": table,
                "kind": "table",
                "module": "default",
                "references": [],
                "columns": [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "nullable": not bool(c["notnull"]),
                        "default": c["dflt_value"],
                    }
                    for c in cols
                ],
            }
        )
    return {"types": types, "version": "1.0"}


def table_schema(conn: sqlite3.Connection, table: str) -> Dict[str, Any]:
    info = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    indexes = conn.execute(f"PRAGMA index_list('{table}')").fetchall()
    return {
        "name": table,
        "columns": [
            {
                "name": row["name"],
                "type": row["type"],
                "nullable": not bool(row["notnull"]),
                "default": row["dflt_value"],
            }
            for row in info
        ],
        "indexes": [
            {
                "name": idx["name"],
                "expression": idx["name"],
            }
            for idx in indexes
        ],
        "primaryKey": [row["name"] for row in info if row["pk"]],
    }
