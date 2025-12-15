from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core import connect, sql_schema, table_schema, resolve_instance_id

bp = Blueprint(
    "schema",
    __name__,
    url_prefix="/instances/<instance_id>/databases/<db>",
)


@bp.get("/schema")
def schema(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"types": [], "version": "0"}), 404
    conn = connect(db)
    try:
        return jsonify(sql_schema(conn))
    finally:
        conn.close()


@bp.get("/tables")
def tables(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    conn = connect(db)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = []
        for row in cur.fetchall():
            name = row["name"]
            cnt = conn.execute(f"SELECT COUNT(*) as c FROM '{name}'").fetchone()[0]
            cols = table_schema(conn, name)["columns"]
            tables.append({"name": name, "rowCount": cnt, "columns": cols})
        return jsonify(tables)
    finally:
        conn.close()


@bp.get("/tables/<table>/schema")
def table_schema_route(instance_id: str, db: str, table: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({}), 404
    conn = connect(db)
    try:
        return jsonify(table_schema(conn, table))
    finally:
        conn.close()


@bp.get("/tables/<table>/rows")
def table_rows(instance_id: str, db: str, table: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({}), 404
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = max(int(request.args.get("offset", 0)), 0)
    where = request.args.get("where")
    order_by = request.args.get("orderBy")

    conn = connect(db)
    try:
        base = f"SELECT * FROM '{table}'"
        clauses = []
        params = []
        if where:
            clauses.append(f"({where})")
        if clauses:
            base += " WHERE " + " AND ".join(clauses)
        if order_by:
            base += f" ORDER BY {order_by}"
        base += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = conn.execute(base, params)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        total = conn.execute(f"SELECT COUNT(*) FROM '{table}'").fetchone()[0]
        return jsonify(
            {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "total": total,
            }
        )
    finally:
        conn.close()
