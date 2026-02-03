from __future__ import annotations

import time
import uuid
from typing import Dict, Any

from flask import Blueprint, jsonify, request

from ..core import AI_TASKS, AI_TASK_LOCK, AI_PROGRAMS, resolve_instance_id

bp = Blueprint(
    "ai",
    __name__,
    url_prefix="/instances/<instance_id>/databases/<db>/ai",
)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _progress_program(task: Dict[str, Any]):
    """Incrementally add nodes over time, then mark done after expected duration."""
    if task["status"] != "running":
        return
    program = AI_PROGRAMS.get(task["programId"])
    if not program:
        return
    elapsed = time.time() - task.get("started_ts", time.time())
    expected = float(task.get("expected_seconds", 20.0))
    template = program.get("_template") or {"nodes": [], "edges": []}
    graph = program["graph"]
    total_nodes = len(template["nodes"])
    if total_nodes == 0:
        return

    # desired count: spread nodes across timeline; last node only near completion
    progress = max(0.0, min(1.0, elapsed / max(expected, 0.1)))
    target_count = max(1, min(total_nodes, int(progress * (total_nodes - 1)) + 1))
    # add at most one node per tick to keep it progressive
    target_count = min(target_count, len(graph["nodes"]) + 1)

    if len(graph["nodes"]) < target_count:
        new_nodes = template["nodes"][len(graph["nodes"]) : target_count]
        graph["nodes"].extend(new_nodes)
        present_ids = {n["id"] for n in graph["nodes"]}
        for edge in template["edges"]:
            if (
                edge["from"] in present_ids
                and edge["to"] in present_ids
                and edge not in graph["edges"]
            ):
                graph["edges"].append(edge)
        program["updatedAt"] = _now_iso()

    # update node statuses
    for idx, node in enumerate(graph["nodes"]):
        node["status"] = "in-progress" if idx == len(graph["nodes"]) - 1 else "done"

    if elapsed >= expected or len(graph["nodes"]) >= total_nodes:
        task["status"] = "completed"
        task["completedAt"] = _now_iso()
        program["status"] = "ready"
        program["updatedAt"] = task["completedAt"]
        for n in graph["nodes"]:
            n["status"] = "done"
        # ensure all nodes/edges are present at completion
        if len(graph["nodes"]) < total_nodes:
            graph["nodes"] = template["nodes"][:]
        if len(graph["edges"]) < len(template["edges"]):
            graph["edges"] = template["edges"][:]


def _cfg_for_feature(feature: str) -> Dict[str, Any]:
    """Return a hard-coded CFG for the requested feature."""
    # normalize
    text = (feature or "").lower()

    # Default CFG: automated billing spike resolution workflow
    nodes = [
        {"id": "start", "label": "Start", "status": "pending"},
        {"id": "load_cycle", "label": "LoadBillingCycleData", "status": "pending"},
        {"id": "load_rules", "label": "LoadRegulations", "status": "pending"},
        {"id": "load_history", "label": "LoadHistoryAndReads", "status": "pending"},
        {"id": "baseline", "label": "ComputeBaseline", "status": "pending"},
        {"id": "detect_spike", "label": "DetectSpike", "status": "pending"},
        {"id": "classify_cause", "label": "ClassifyRootCause", "status": "pending"},
        {"id": "score_confidence", "label": "ScoreConfidence", "status": "pending"},
        {"id": "justify", "label": "BuildJustification", "status": "pending"},
        {"id": "check_regulation", "label": "CheckRegulation", "status": "pending"},
        {"id": "decide_adjust", "label": "DecidePath", "status": "pending"},
        {"id": "auto_adjust", "label": "AutoAdjust", "status": "pending"},
        {"id": "compose_messages", "label": "ComposeMessages", "status": "pending"},
        {"id": "escalate", "label": "Escalate", "status": "pending"},
        {"id": "final", "label": "Finalize", "status": "pending"},
    ]
    edges = [
        {"from": "start", "to": "load_cycle", "label": ""},
        {"from": "load_cycle", "to": "load_rules", "label": ""},
        {"from": "load_rules", "to": "load_history", "label": ""},
        {"from": "load_history", "to": "baseline", "label": ""},
        {"from": "baseline", "to": "detect_spike", "label": ""},
        {"from": "detect_spike", "to": "classify_cause", "label": "spike"},
        {"from": "detect_spike", "to": "final", "label": "no spike"},
        {"from": "classify_cause", "to": "score_confidence", "label": ""},
        {"from": "score_confidence", "to": "justify", "label": ""},
        {"from": "justify", "to": "check_regulation", "label": ""},
        {"from": "check_regulation", "to": "decide_adjust", "label": ""},
        {"from": "decide_adjust", "to": "auto_adjust", "label": "auto"},
        {"from": "decide_adjust", "to": "escalate", "label": "escalate"},
        {"from": "auto_adjust", "to": "compose_messages", "label": ""},
        {"from": "compose_messages", "to": "final", "label": ""},
        {"from": "escalate", "to": "final", "label": ""},
    ]

    if "complaint" in text or "llm" in text or "resolve" in text:
        nodes = [
            {"id": "start", "label": "Start", "status": "pending"},
            {"id": "load_complaints", "label": "LoadComplaints", "status": "pending"},
            {"id": "load_exceptions", "label": "LoadBillingExceptions", "status": "pending"},
            {"id": "for_complaint", "label": "ForEach(complaint)", "status": "pending"},
            {"id": "if_linked", "label": "If(linked_exception)", "status": "pending"},
            {"id": "enrich_llm", "label": "LLMClassify", "status": "pending"},
            {"id": "attach_workflow", "label": "AttachWorkflow", "status": "pending"},
            {"id": "final", "label": "Finalize", "status": "pending"},
        ]
        edges = [
            {"from": "start", "to": "load_complaints", "label": ""},
            {"from": "load_complaints", "to": "load_exceptions", "label": ""},
            {"from": "load_exceptions", "to": "for_complaint", "label": ""},
            {"from": "for_complaint", "to": "if_linked", "label": ""},
            {"from": "if_linked", "to": "attach_workflow", "label": "yes"},
            {"from": "if_linked", "to": "enrich_llm", "label": "no"},
            {"from": "enrich_llm", "to": "attach_workflow", "label": ""},
            {"from": "attach_workflow", "to": "final", "label": ""},
        ]

    return {"nodes": nodes, "edges": edges}


@bp.post("/programs")
def create_program(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    payload = request.get_json(force=True, silent=True) or {}
    feature = payload.get("feature") or payload.get("prompt") or ""
    program_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    created = _now_iso()
    cfg = _cfg_for_feature(feature)
    program = {
        "id": program_id,
        "feature": feature,
        "status": "building",
        "createdAt": created,
        "updatedAt": created,
        # start with only the first node visible
        "graph": {"nodes": [cfg["nodes"][0]] if cfg["nodes"] else [], "edges": []},
        "_template": cfg,
    }
    task = {
        "id": task_id,
        "programId": program_id,
        "status": "running",
        "prompt": feature,
        "createdAt": created,
        "completedAt": None,
        "started_ts": time.time(),
        "expected_seconds": 20.0,
        "step": 0,
    }
    with AI_TASK_LOCK:
        AI_PROGRAMS[program_id] = program
        AI_TASKS[task_id] = task
    return jsonify({"task": task, "program": program}), 202


@bp.get("/programs")
def list_programs(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    with AI_TASK_LOCK:
        for t in AI_TASKS.values():
            _progress_program(t)
        programs = list(AI_PROGRAMS.values())
    return jsonify(programs)


@bp.get("/programs/<program_id>")
def get_program(instance_id: str, db: str, program_id: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify({"error": "instance not found"}), 404
    with AI_TASK_LOCK:
        for t in AI_TASKS.values():
            _progress_program(t)
        program = AI_PROGRAMS.get(program_id)
    if not program:
        return jsonify({"error": "program not found"}), 404
    return jsonify(program)


@bp.post("/tasks")
def create_task(instance_id: str, db: str):
    # redirect to program creation for backwards compatibility
    return create_program(instance_id, db)


@bp.get("/tasks")
def list_tasks(instance_id: str, db: str):
    resolved = resolve_instance_id(instance_id)
    if resolved is None:
        return jsonify([]), 404
    status = request.args.get("status")
    with AI_TASK_LOCK:
        for t in AI_TASKS.values():
            _progress_program(t)
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
        if task:
            _progress_program(task)
            program = AI_PROGRAMS.get(task["programId"])
        else:
            program = None
    if not task:
        return jsonify({"error": "task not found"}), 404
    resp = {"task": task}
    if program:
        resp["program"] = program
    return jsonify(resp)
