from flask import Blueprint, jsonify

from ..core import INSTANCE_ID, INSTANCE_NAME, list_databases, resolve_instance_id

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
