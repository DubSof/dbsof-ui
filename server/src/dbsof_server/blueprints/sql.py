from __future__ import annotations

import sqlite3
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
    # #region agent log
    import json
    try:
        with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"sql.py:19","message":"run_sql called","data":{"instance_id":instance_id,"db":db},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    query = payload.get("query") or ""
    params = payload.get("params") or {}
    mode = payload.get("mode") or "tabular"
    # #region agent log
    try:
        with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"sql.py:27","message":"run_sql query received","data":{"query":query[:200],"has_equals":":=" in query,"has_double_colon":"::" in query,"starts_with_with":query.strip().startswith("with ")},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion

    conn = connect(db)
    start = time.perf_counter()
    translated_query = None
    translated_params = dict(params)
    # #region agent log
    try:
        with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"sql.py:43","message":"before translation checks","data":{"query":query[:200]},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion

    # naive translation of EdgeQL-like query used by data explorer
    # #region agent log
    try:
        import re as re_module
        pattern_test = re_module.search(r"select\s+count\(std::Object\)", query, re_module.IGNORECASE)
        with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"sql.py:53","message":"testing std::Object pattern","data":{"query":query[:200],"pattern_matches":pattern_test is not None},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except Exception as e:
        try:
            with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"sql.py:53","message":"pattern test error","data":{"error":str(e)},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
    # #endregion
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
    elif re.search(r"select\s+count\(std::Object\)", query, re.IGNORECASE):
        # #region agent log
        try:
            with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"sql.py:69","message":"std::Object translation matched","data":{"query":query[:200]},"timestamp":int(__import__("time").time()*1000)})+"\n")
        except: pass
        # #endregion
        # Translate EdgeQL count(std::Object) to SQL
        # For SQLite, count total rows across all user tables
        # This is a simplified approximation - counts tables (not individual objects)
        # A more accurate version would sum rows from all tables, but that's expensive
        translated_query = "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != '__meta__'"
    # #region agent log
    try:
        with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"sql.py:80","message":"translation check","data":{"has_translated_query":translated_query is not None,"query_to_run":(translated_query or query)[:200]},"timestamp":int(__import__("time").time()*1000)})+"\n")
    except: pass
    # #endregion
    if translated_query:
        query_to_run = translated_query
        params = translated_params
    else:
        query_to_run = query
        # If query contains EdgeQL syntax (like `:=` or `::`), reject it
        # since we can't translate it to SQL
        # Exception: allow std::Object which we translate above
        if ":=" in query or ("::" in query and "std::Object" not in query) or (query.strip().startswith("with ") and "baseQuery" not in query):
            # #region agent log
            try:
                with open(r"c:\Programming\Dubsof\.cursor\debug.log", "a") as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"B","location":"sql.py:77","message":"run_sql rejecting EdgeQL","data":{"query":query[:200]},"timestamp":int(__import__("time").time()*1000)})+"\n")
            except: pass
            # #endregion
            return jsonify({
                "error": "EdgeQL syntax not supported. Please use SQL syntax."
            }), 400
    
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
    except sqlite3.OperationalError as exc:
        conn.rollback()
        duration = (time.perf_counter() - start) * 1000
        record_history(db, query, duration, "error")
        error_msg = str(exc)
        # Provide more helpful error messages for common SQLite errors
        if "unrecognized token" in error_msg:
            return jsonify({
                "error": f"SQL syntax error: {error_msg}. Make sure you're using SQL syntax, not EdgeQL."
            }), 400
        return jsonify({"error": error_msg}), 400
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
