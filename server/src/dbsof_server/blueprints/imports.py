from __future__ import annotations

import time
import uuid
from typing import Dict, Any, List, Tuple

from flask import Blueprint, jsonify, request

from ..core import (
    IMPORT_JOBS,
    IMPORT_LOCK,
    resolve_instance_id,
    connect,
    seed_target_ontology,
)

SAMPLE_FILES: List[Tuple[str, str]] = [
    (
        "customers.csv",
        """id,name,customer_type,jurisdiction,status,created_at
11111111-1111-1111-1111-000000000001,"Liam O'Connor",residential,IE,active,2021-06-01T00:00:00Z
11111111-1111-1111-1111-000000000002,"Ann Murphy",residential,IE,active,2020-03-12T00:00:00Z
11111111-1111-1111-1111-000000000003,"Patrick Byrne",residential,IE,active,2019-09-18T00:00:00Z
11111111-1111-1111-1111-000000000004,"ACME LTD",commercial,IE,active,2015-01-01T00:00:00Z
11111111-1111-1111-1111-000000000005,"GreenFarm Coop",commercial,IE,active,2017-05-20T00:00:00Z
11111111-1111-1111-1111-000000000006,"NorthSide Logistics",commercial,IE,active,2018-11-02T00:00:00Z
11111111-1111-1111-1111-000000000007,"Pinewood Apartments",commercial,IE,active,2016-08-01T00:00:00Z
11111111-1111-1111-1111-000000000008,"Atlas Manufacturing",commercial,IE,active,2014-04-10T00:00:00Z
11111111-1111-1111-1111-000000000009,"SwiftCouriers",commercial,IE,active,2019-02-15T00:00:00Z
""",
    ),
    (
        "sites.csv",
        """id,customer_id,address,network_region,site_type,active
22222222-2222-2222-2222-000000000001,11111111-1111-1111-1111-000000000001,"12 Oak Rd, Dublin",IE-EAST,residential,true
22222222-2222-2222-2222-000000000002,11111111-1111-1111-1111-000000000004,"ACME Plant 3, Galway",IE-WEST,industrial,true
22222222-2222-2222-2222-000000000003,11111111-1111-1111-1111-000000000005,"GreenFarm Main, Cork",IE-SOUTH,industrial,true
22222222-2222-2222-2222-000000000004,11111111-1111-1111-1111-000000000006,"Logistics Hub, Drogheda",IE-NORTH,industrial,true
22222222-2222-2222-2222-000000000005,11111111-1111-1111-1111-000000000009,"Depot 7, Dublin Port",IE-EAST,industrial,true
""",
    ),
    (
        "meters.csv",
        """id,site_id,meter_type,fuel_type,capabilities,install_date,status
33333333-3333-3333-3333-000000000001,22222222-2222-2222-2222-000000000001,smart,electricity,"{""tou"":false}",2021-03-01,active
33333333-3333-3333-3333-000000000002,22222222-2222-2222-2222-000000000001,legacy,gas,"{}",1998-06-01,faulty
33333333-3333-3333-3333-000000000003,22222222-2222-2222-2222-000000000002,smart,electricity,"{""tou"":true}",2020-01-01,active
33333333-3333-3333-3333-000000000004,22222222-2222-2222-2222-000000000004,smart,electricity,"{}",2022-05-01,active
""",
    ),
    (
        "billingcycles.csv",
        """id,contract_id,period_start,period_end,status,closed_at
44444444-4444-4444-4444-000000000001,55555555-5555-5555-5555-000000000001,2024-01-01,2024-01-31,closed,2024-02-02T00:00:00Z
44444444-4444-4444-4444-000000000002,55555555-5555-5555-5555-000000000001,2024-02-01,2024-02-29,closed,2024-03-02T00:00:00Z
""",
    ),
    (
        "billingexceptions.csv",
        """id,billing_cycle_id,exception_type,detected_at,severity,status,llm_classification,confidence
66666666-6666-6666-6666-000000000001,44444444-4444-4444-4444-000000000002,spike,2024-03-02T01:00:00Z,high,auto_resolved,"Likely estimated-to-actual reconciliation after missing January read",0.87
""",
    ),
    (
        "adjustments.csv",
        """id,invoice_id,adjustment_type,amount,reason,regulatory_basis,applied_at
77777777-7777-7777-7777-000000000001,88888888-8888-8888-8888-000000000002,credit,276.67,"Usage spike due to delayed meter reconciliation","CRU Billing Code §4.3",2024-03-02T01:05:00Z
""",
    ),
]

bp = Blueprint(
    "imports",
    __name__,
    url_prefix="/instances/<instance_id>/databases/<db>/imports",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _update_progress(job: Dict[str, Any]):
    if job["status"] != "running":
        return
    elapsed = time.time() - job.get("started_ts", time.time())
    duration = max(12.0, job.get("expected_seconds", 15.0))
    # stall at 0 until done to avoid spinner feeling finite
    if elapsed >= duration:
        job["progress"] = 100.0
        job["status"] = "completed"
        job["completedAt"] = _now_iso()
        job["updatedAt"] = job["completedAt"]
        if not job.get("applied"):
            inserted = _apply_seed_data(job["db"])
            if inserted and not job.get("rows"):
                job["rows"] = inserted
            job["applied"] = True


@bp.post("")
def create_import(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404

    # accept multipart/form-data or json
    payload = request.form if request.form else request.get_json(silent=True) or {}
    files = request.files.getlist("files") or ([] if not request.files else [request.files.get("file")])
    first_file = files[0] if files else None

    job_id = str(uuid.uuid4())
    now = _now_iso()
    started_ts = time.time()
    rows = int(payload.get("rows") or 0)
    file_info = []
    for f in files:
        if not f:
            continue
        data = f.read()
        file_info.append({"filename": f.filename, "size": len(data)})
        f.stream.seek(0)
    if not file_info:
        file_info = [{"filename": name, "size": len(content.encode("utf-8"))} for name, content in SAMPLE_FILES]

    default_name = payload.get("name") or (first_file.filename if first_file else file_info[0]["filename"] if file_info else "Import")
    job = {
        "id": job_id,
        "name": default_name,
        "source": payload.get("source") or ("upload" if file_info else "manual"),
        "notes": payload.get("notes") or "",
        "rows": rows,
        "status": "running",
        "progress": 0.0,
        "createdAt": now,
        "completedAt": None,
        "updatedAt": now,
        "started_ts": started_ts,
        "expected_seconds": 15.0,
        "files": file_info,
        "db": db,
        "applied": False,
    }

    with IMPORT_LOCK:
        IMPORT_JOBS[job_id] = job

    return jsonify(job), 202


@bp.get("")
def list_imports(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    with IMPORT_LOCK:
        for job in IMPORT_JOBS.values():
            _update_progress(job)
        jobs = [job for job in IMPORT_JOBS.values() if job.get("db") == db]
    return jsonify(jobs)


@bp.get("/<job_id>")
def get_import(instance_id: str, db: str, job_id: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    with IMPORT_LOCK:
        job = IMPORT_JOBS.get(job_id)
        if job and job.get("db") == db:
            _update_progress(job)
        else:
            job = None
    if not job:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


def _apply_seed_data(db: str) -> int:
    """Apply a canned import dataset to the target database."""
    seed_target_ontology(db)
    conn = connect(db)
    conn.execute("PRAGMA foreign_keys = ON;")
    cur = conn.cursor()

    customers: List[Tuple] = [
        ("11111111-1111-1111-1111-000000000001", "Liam O'Connor", "residential", "IE", "active", "2021-06-01T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000002", "Ann Murphy", "residential", "IE", "active", "2020-03-12T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000003", "Patrick Byrne", "residential", "IE", "active", "2019-09-18T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000004", "ACME LTD", "commercial", "IE", "active", "2015-01-01T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000005", "GreenFarm Coop", "commercial", "IE", "active", "2017-05-20T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000006", "NorthSide Logistics", "commercial", "IE", "active", "2018-11-02T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000007", "Pinewood Apartments", "commercial", "IE", "active", "2016-08-01T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000008", "Atlas Manufacturing", "commercial", "IE", "active", "2014-04-10T00:00:00Z"),
        ("11111111-1111-1111-1111-000000000009", "SwiftCouriers", "commercial", "IE", "active", "2019-02-15T00:00:00Z"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Customer (id, name, customer_type, jurisdiction, status, created_at) VALUES (?,?,?,?,?,?)",
        customers,
    )

    sites: List[Tuple] = [
        ("22222222-2222-2222-2222-000000000001", "11111111-1111-1111-1111-000000000001", "12 Oak Rd, Dublin", "IE-EAST", "residential", 1),
        ("22222222-2222-2222-2222-000000000002", "11111111-1111-1111-1111-000000000004", "ACME Plant 3, Galway", "IE-WEST", "industrial", 1),
        ("22222222-2222-2222-2222-000000000003", "11111111-1111-1111-1111-000000000005", "GreenFarm Main, Cork", "IE-SOUTH", "industrial", 1),
        ("22222222-2222-2222-2222-000000000004", "11111111-1111-1111-1111-000000000006", "Logistics Hub, Drogheda", "IE-NORTH", "industrial", 1),
        ("22222222-2222-2222-2222-000000000005", "11111111-1111-1111-1111-000000000009", "Depot 7, Dublin Port", "IE-EAST", "industrial", 1),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Site (id, customer_id, address, network_region, site_type, active) VALUES (?,?,?,?,?,?)",
        sites,
    )

    meters: List[Tuple] = [
        ("33333333-3333-3333-3333-000000000001", "22222222-2222-2222-2222-000000000001", "smart", "electricity", '{"tou":false}', "2021-03-01", "active"),
        ("33333333-3333-3333-3333-000000000002", "22222222-2222-2222-2222-000000000001", "legacy", "gas", "{}", "1998-06-01", "faulty"),
        ("33333333-3333-3333-3333-000000000003", "22222222-2222-2222-2222-000000000002", "smart", "electricity", '{"tou":true}', "2020-01-01", "active"),
        ("33333333-3333-3333-3333-000000000004", "22222222-2222-2222-2222-000000000004", "smart", "electricity", "{}", "2022-05-01", "active"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Meter (id, site_id, meter_type, fuel_type, capabilities, install_date, status) VALUES (?,?,?,?,?,?,?)",
        meters,
    )

    contracts: List[Tuple] = [
        (
            "55555555-5555-5555-5555-000000000001",
            "11111111-1111-1111-1111-000000000004",
            "22222222-2222-2222-2222-000000000002",
            "2024-01-01",
            None,
            "active",
            "Standard supply agreement",
        )
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Contract (id, customer_id, site_id, start_date, end_date, status, terms_text) VALUES (?,?,?,?,?,?,?)",
        contracts,
    )

    billing_cycles: List[Tuple] = [
        ("44444444-4444-4444-4444-000000000001", "55555555-5555-5555-5555-000000000001", "2024-01-01", "2024-01-31", "closed", "2024-02-02T00:00:00Z"),
        ("44444444-4444-4444-4444-000000000002", "55555555-5555-5555-5555-000000000001", "2024-02-01", "2024-02-29", "closed", "2024-03-02T00:00:00Z"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO BillingCycle (id, contract_id, period_start, period_end, status, closed_at) VALUES (?,?,?,?,?,?)",
        billing_cycles,
    )

    invoices: List[Tuple] = [
        ("88888888-8888-8888-8888-000000000001", "44444444-4444-4444-4444-000000000001", "2024-02-02", 0.0, "EUR", "issued"),
        ("88888888-8888-8888-8888-000000000002", "44444444-4444-4444-4444-000000000002", "2024-03-02", 276.67, "EUR", "issued"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Invoice (id, billing_cycle_id, invoice_date, total_amount, currency, status) VALUES (?,?,?,?,?,?)",
        invoices,
    )

    billing_exceptions: List[Tuple] = [
        (
            "66666666-6666-6666-6666-000000000001",
            "44444444-4444-4444-4444-000000000002",
            "spike",
            "2024-03-02T01:00:00Z",
            "high",
            "auto_resolved",
            "Likely estimated-to-actual reconciliation after missing January read",
            0.87,
        )
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO BillingException (id, billing_cycle_id, exception_type, detected_at, severity, status, llm_classification, confidence) VALUES (?,?,?,?,?,?,?,?)",
        billing_exceptions,
    )

    adjustments: List[Tuple] = [
        (
            "77777777-7777-7777-7777-000000000001",
            "88888888-8888-8888-8888-000000000002",
            "credit",
            276.67,
            "Usage spike due to delayed meter reconciliation",
            "CRU Billing Code §4.3",
            "2024-03-02T01:05:00Z",
        )
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO Adjustment (id, invoice_id, adjustment_type, amount, reason, regulatory_basis, applied_at) VALUES (?,?,?,?,?,?,?)",
        adjustments,
    )

    conn.commit()
    conn.close()
    return (
        len(customers)
        + len(sites)
        + len(meters)
        + len(contracts)
        + len(billing_cycles)
        + len(invoices)
        + len(billing_exceptions)
        + len(adjustments)
    )
