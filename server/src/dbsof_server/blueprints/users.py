from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core import get_user_settings, update_user_settings

bp = Blueprint("users", __name__)


@bp.get("/users/<user_id>/settings")
def get_settings(user_id: str):
    """Get user settings for a specific user."""
    try:
        settings = get_user_settings(user_id)
        return jsonify(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.put("/users/<user_id>/settings")
def update_settings(user_id: str):
    """Update user settings for a specific user."""
    payload = request.get_json(force=True, silent=True) or {}
    
    if not payload:
        return jsonify({"error": "Settings data is required"}), 400
    
    try:
        updated_settings = update_user_settings(user_id, payload)
        return jsonify(updated_settings)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to update settings: {str(e)}"}), 500
