from flask import Blueprint, jsonify, request

from ..core import (
    INSTANCE_ID,
    INSTANCE_NAME,
    create_database,
    get_database_migrations,
    list_databases,
    resolve_instance_id,
)

bp = Blueprint("instances", __name__)


@bp.get("/instances")
def instances():
    return jsonify([{"id": INSTANCE_ID, "name": INSTANCE_NAME}])


@bp.get("/instances/<instance_id>/databases")
def databases(instance_id: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    return jsonify(list_databases())


@bp.post("/instances/<instance_id>/databases")
def create_database_endpoint(instance_id: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    
    payload = request.get_json(force=True, silent=True) or {}
    db_name = payload.get("name") or ""
    from_branch = payload.get("fromBranch")
    copy_data = payload.get("copyData", False)
    
    if not db_name:
        return jsonify({"error": "Database name is required"}), 400
    
    try:
        result = create_database(db_name, from_branch, copy_data)
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to create database: {str(e)}"}), 500


@bp.get("/instances/<instance_id>/databases/<db>/migrations")
def get_migrations(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    
    try:
        migrations = get_database_migrations(db)
        return jsonify(migrations)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
