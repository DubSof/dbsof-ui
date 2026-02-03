from __future__ import annotations

import time
import re

from flask import Blueprint, jsonify, request

from ..core import QUERY_HISTORY, connect, record_history, resolve_instance_id

bp = Blueprint(
    "sql",
    __name__,
    url_prefix="/instances/<instance_id>/databases/<db>/sql",
)


@bp.post("/commands")
def run_sql(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    query = payload.get("query") or ""
    params = payload.get("params") or {}
    mode = payload.get("mode") or "tabular"

    conn = connect(db)
    start = time.perf_counter()
    translated_query = None
    translated_params = dict(params)

    # naive translation of EdgeQL-like query used by data explorer
    if "baseObjects :=" in query and "SELECT rows" in query:
        match_table = re.search(r"baseObjects\s*:=\s*\(select\s+([A-Za-z0-9_]+)\)", query, re.IGNORECASE)
        if match_table:
            table = match_table.group(1)
            match_limit = re.search(r"LIMIT\s+(\d+)", query, re.IGNORECASE)
            limit = int(match_limit.group(1)) if match_limit else 100
            select_cols = ["id"]
            for line in query.splitlines():
                m = re.search(r"([A-Za-z0-9_]+)\s*:=\s*\.([A-Za-z0-9_]+)", line)
                if m:
                    alias, col = m.groups()
                    select_cols.append(f'"{col}" AS "{alias}"')
            if len(select_cols) == 1:
                select_cols.append("*")
            offset_val = translated_params.get("offset", 0)
            translated_params = {"offset": offset_val}
            translated_query = f'SELECT {", ".join(select_cols)} FROM "{table}" ORDER BY id LIMIT {limit} OFFSET :offset'
    elif re.search(r"with\\s+baseQuery\\s*:=\\s*\\(select\\s+([A-Za-z0-9_]+)\\)", query, re.IGNORECASE):
        match_table = re.search(r"with\\s+baseQuery\\s*:=\\s*\\(select\\s+([A-Za-z0-9_]+)\\)", query, re.IGNORECASE)
        if match_table:
            table = match_table.group(1)
            translated_query = f'SELECT COUNT(*) FROM "{table}"'
    if translated_query:
        query_to_run = translated_query
        params = translated_params
    else:
        query_to_run = query
    try:
        cur = conn.execute(query_to_run, params)
        if query.strip().lower().startswith("select"):
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description] if cur.description else []
            result_rows = [list(row) for row in rows]
            duration = (time.perf_counter() - start) * 1000
            record_history(db, query, duration, "OK")
            return jsonify(
                {
                    "status": "OK",
                    "durationMs": duration,
                    "columns": columns,
                    "rows": result_rows,
                    "rawText": None if mode == "tabular" else "\n".join(str(r) for r in result_rows),
                }
            )
        else:
            conn.commit()
            duration = (time.perf_counter() - start) * 1000
            record_history(db, query, duration, "OK")
            return jsonify(
                {
                    "status": "OK",
                    "durationMs": duration,
                    "columns": [],
                    "rows": [],
                    "rawText": f"{cur.rowcount} rows affected" if mode == "raw" else None,
                }
            )
    except Exception as exc:
        conn.rollback()
        duration = (time.perf_counter() - start) * 1000
        record_history(db, query, duration, "error")
        return jsonify({"error": str(exc)}), 400
    finally:
        conn.close()


@bp.get("/history")
def sql_history(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"items": [], "nextCursor": None}), 404
    limit = min(int(request.args.get("limit", 50)), 200)
    cursor = request.args.get("cursor")
    items = QUERY_HISTORY.get(db, [])
    start_index = 0
    if cursor:
        try:
            start_index = next(i for i, item in enumerate(items) if item["id"] == cursor) + 1
        except StopIteration:
            start_index = 0
    page = items[start_index : start_index + limit]
    next_cursor = page[-1]["id"] if len(page) == limit and start_index + limit < len(items) else None
    return jsonify({"items": page, "nextCursor": next_cursor})
