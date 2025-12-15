from __future__ import annotations

import time
import uuid

from flask import Blueprint, jsonify, request

from ..core import AI_TASKS, AI_TASK_LOCK, resolve_instance_id

bp = Blueprint(
    "ai",
    __name__,
    url_prefix="/instances/<instance_id>/databases/<db>/ai",
)


@bp.post("/tasks")
def create_task(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "status": "completed",
        "prompt": payload.get("prompt", ""),
        "model": payload.get("model", "mock-model"),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "output": [
            {
                "role": "assistant",
                "content": "Mock response for prompt: " + payload.get("prompt", ""),
            }
        ],
    }
    with AI_TASK_LOCK:
        AI_TASKS[task_id] = task
    return jsonify(task), 202


@bp.get("/tasks")
def list_tasks(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    status = request.args.get("status")
    with AI_TASK_LOCK:
        tasks = list(AI_TASKS.values())
    if status:
        tasks = [t for t in tasks if t["status"] == status]
    return jsonify(tasks)


@bp.get("/tasks/<task_id>")
def get_task(instance_id: str, db: str, task_id: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    with AI_TASK_LOCK:
        task = AI_TASKS.get(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(task)
