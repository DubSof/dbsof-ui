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
AI_PROGRAMS: Dict[str, Dict[str, Any]] = {}
IMPORT_JOBS: Dict[str, Dict[str, Any]] = {}
IMPORT_LOCK = threading.Lock()


def db_path(db_name: str) -> Path:
    safe = "".join(c for c in db_name if c.isalnum() or c in ("_", "-")).strip()
    if not safe:
        raise ValueError("Invalid database name")
    return DATA_DIR / f"{safe}.db"


def ensure_db(db_name: str) -> Path:
    path = db_path(db_name)
    if not path.exists():
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("CREATE TABLE IF NOT EXISTS __meta__ (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        conn.close()
    return path


def connect(db_name: str) -> sqlite3.Connection:
    path = ensure_db(db_name)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    migrate_legacy_lowercase_tables(conn)
    return conn


def list_databases() -> List[Dict[str, Any]]:
    dbs: List[Dict[str, Any]] = []
    for file in DATA_DIR.glob("*.db"):
        dbs.append({"name": file.stem, "lastMigration": None})
    if not dbs:
        seed_target_ontology("main")
        dbs.append({"name": "main", "lastMigration": None})
    return dbs


def seed_target_ontology(db_name: str):
    conn = connect(db_name)
    conn.execute("PRAGMA foreign_keys = ON;")
    migrate_legacy_lowercase_tables(conn)
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS Customer (
  id TEXT PRIMARY KEY,
  name TEXT,
  customer_type TEXT,
  jurisdiction TEXT,
  status TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS Site (
  id TEXT PRIMARY KEY,
  customer_id TEXT REFERENCES Customer(id),
  address TEXT,
  network_region TEXT,
  site_type TEXT,
  active INTEGER
);
CREATE TABLE IF NOT EXISTS Meter (
  id TEXT PRIMARY KEY,
  site_id TEXT REFERENCES Site(id),
  meter_type TEXT,
  fuel_type TEXT,
  capabilities TEXT,
  install_date TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS MeterRead (
  id TEXT PRIMARY KEY,
  meter_id TEXT REFERENCES Meter(id),
  read_type TEXT,
  read_timestamp TEXT,
  value REAL,
  source TEXT,
  quality_flag TEXT
);
CREATE TABLE IF NOT EXISTS Contract (
  id TEXT PRIMARY KEY,
  customer_id TEXT REFERENCES Customer(id),
  site_id TEXT REFERENCES Site(id),
  start_date TEXT,
  end_date TEXT,
  status TEXT,
  terms_text TEXT
);
CREATE TABLE IF NOT EXISTS Tariff (
  id TEXT PRIMARY KEY,
  fuel_type TEXT,
  tariff_code TEXT,
  pricing_model TEXT,
  eligibility_rules TEXT,
  effective_from TEXT,
  effective_to TEXT
);
CREATE TABLE IF NOT EXISTS ContractTariff (
  id TEXT PRIMARY KEY,
  contract_id TEXT REFERENCES Contract(id),
  tariff_id TEXT REFERENCES Tariff(id),
  applied_from TEXT,
  applied_to TEXT,
  is_current INTEGER
);
CREATE TABLE IF NOT EXISTS BillingCycle (
  id TEXT PRIMARY KEY,
  contract_id TEXT REFERENCES Contract(id),
  period_start TEXT,
  period_end TEXT,
  status TEXT,
  closed_at TEXT
);
CREATE TABLE IF NOT EXISTS Invoice (
  id TEXT PRIMARY KEY,
  billing_cycle_id TEXT REFERENCES BillingCycle(id),
  invoice_date TEXT,
  total_amount REAL,
  currency TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS BillingException (
  id TEXT PRIMARY KEY,
  billing_cycle_id TEXT REFERENCES BillingCycle(id),
  exception_type TEXT,
  detected_at TEXT,
  severity TEXT,
  status TEXT,
  llm_classification TEXT,
  confidence REAL
);
CREATE TABLE IF NOT EXISTS Adjustment (
  id TEXT PRIMARY KEY,
  invoice_id TEXT REFERENCES Invoice(id),
  adjustment_type TEXT,
  amount REAL,
  reason TEXT,
  regulatory_basis TEXT,
  applied_at TEXT
);
CREATE TABLE IF NOT EXISTS Complaint (
  id TEXT PRIMARY KEY,
  customer_id TEXT REFERENCES Customer(id),
  received_at TEXT,
  channel TEXT,
  raw_text TEXT,
  inferred_issue TEXT,
  linked_exception_id TEXT REFERENCES BillingException(id),
  status TEXT
);
CREATE TABLE IF NOT EXISTS RegulatoryRule (
  id TEXT PRIMARY KEY,
  jurisdiction TEXT,
  rule_type TEXT,
  rule_text TEXT,
  effective_from TEXT,
  effective_to TEXT
);
CREATE TABLE IF NOT EXISTS WorkflowInstance (
  id TEXT PRIMARY KEY,
  workflow_type TEXT,
  trigger_entity TEXT,
  trigger_id TEXT,
  state TEXT,
  started_at TEXT,
  completed_at TEXT
);
CREATE TABLE IF NOT EXISTS WorkflowAction (
  id TEXT PRIMARY KEY,
  workflow_instance_id TEXT REFERENCES WorkflowInstance(id),
  action_type TEXT,
  input_ref TEXT,
  output_ref TEXT,
  executed_at TEXT
);
"""
    )
    # seed minimal data if empty
    existing = conn.execute("SELECT COUNT(*) AS c FROM Customer").fetchone()[0]
    if existing == 0:
        conn.execute(
            "INSERT INTO Customer (id, name, customer_type, jurisdiction, status, created_at) VALUES (?,?,?,?,?,?)",
            (
                "11111111-1111-1111-1111-111111111111",
                "Acme Energy",
                "commercial",
                "NY",
                "active",
                "2023-01-01T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO Site (id, customer_id, address, network_region, site_type, active) VALUES (?,?,?,?,?,?)",
            (
                "22222222-2222-2222-2222-222222222222",
                "11111111-1111-1111-1111-111111111111",
                "123 Grid St",
                "North",
                "industrial",
                1,
            ),
        )
        conn.execute(
            "INSERT INTO Meter (id, site_id, meter_type, fuel_type, capabilities, install_date, status) VALUES (?,?,?,?,?,?,?)",
            (
                "33333333-3333-3333-3333-333333333333",
                "22222222-2222-2222-2222-222222222222",
                "smart",
                "electricity",
                "{}",
                "2023-02-01",
                "active",
            ),
        )
        conn.execute(
            "INSERT INTO MeterRead (id, meter_id, read_type, read_timestamp, value, source, quality_flag) VALUES (?,?,?,?,?,?,?)",
            (
                "44444444-4444-4444-4444-444444444444",
                "33333333-3333-3333-3333-333333333333",
                "actual",
                "2023-03-01T00:00:00Z",
                1234.5,
                "device",
                "valid",
            ),
        )
    conn.execute("INSERT OR REPLACE INTO __meta__ (k, v) VALUES ('seeded', 'true')")
    conn.commit()
    conn.close()


def migrate_legacy_lowercase_tables(conn: sqlite3.Connection):
    """Rename old snake_case seed tables to PascalCase to match the new schema."""
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    legacy_to_new = {
        "customer": "Customer",
        "site": "Site",
        "meter": "Meter",
        "meter_read": "MeterRead",
        "contract": "Contract",
        "tariff": "Tariff",
        "contract_tariff": "ContractTariff",
        "billing_cycle": "BillingCycle",
        "invoice": "Invoice",
        "billing_exception": "BillingException",
        "adjustment": "Adjustment",
        "complaint": "Complaint",
        "regulatory_rule": "RegulatoryRule",
        "workflow_instance": "WorkflowInstance",
        "workflow_action": "WorkflowAction",
    }
    # Only run if old tables exist
    if not any(old in names for old in legacy_to_new.keys()):
        return

    conn.execute("PRAGMA foreign_keys = OFF;")
    try:
        for old, new in legacy_to_new.items():
            if old in names:
                info = conn.execute(f"PRAGMA table_info('{old}')").fetchall()
                cols = ", ".join(
                    f'"{row["name"]}" {row["type"] or ""} {"NOT NULL" if row["notnull"] else ""}{" PRIMARY KEY" if row["pk"] else ""}'.strip()
                    for row in info
                )
                fk_rows = conn.execute(f"PRAGMA foreign_key_list('{old}')").fetchall()
                fk_sql = ""
                for fk in fk_rows:
                    fk_sql += f", FOREIGN KEY(\"{fk['from']}\") REFERENCES {legacy_to_new.get(fk['table'], fk['table'])}(\"{fk['to']}\")"
                if new not in names:
                    conn.execute(f'CREATE TABLE IF NOT EXISTS {new} ({cols}{fk_sql})')
                    col_names = ", ".join(f'"{row["name"]}"' for row in info)
                    conn.execute(f'INSERT INTO {new} ({col_names}) SELECT {col_names} FROM {old}')
                conn.execute(f'DROP TABLE {old}')
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")


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
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != '__meta__'"
    )
    tables = [r["name"] for r in cur.fetchall()]
    types = []
    for table in tables:
        cols_cur = conn.execute(f"PRAGMA table_info('{table}')")
        cols = cols_cur.fetchall()
        fk_cur = conn.execute(f"PRAGMA foreign_key_list('{table}')")
        fk_rows = fk_cur.fetchall()
        fk_map = {(fk["from"],): {"table": fk["table"], "column": fk["to"]} for fk in fk_rows}
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
                        "references": fk_map.get((c["name"],)),
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
