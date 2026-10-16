"""/** 权限与资源归属决定批次等待和定向保存 */"""

from MCP.mcp_asset_scope import conflicting_packages


MANAGEMENT_ACTIONS = frozenset({"pause_operator", "resume_operator", "cancel_blocker", "terminate_host"})


def require_control(operators, client, action):
    """/** @param operators 干员池 @param client 当前身份 @param action 明确控制动作 @return 当前权限完成核验 */"""
    if action in MANAGEMENT_ACTIONS:
        operators.require(client, level=0)


def assess(job, activity, assets, jobs, operators, activity_owners, pie_owner, draining, corrective):
    """/** @param job 当前批次 @param activity 宿主快照 @param assets 占用登记 @param jobs 批次归属 @param operators 干员权限 @param activity_owners 活动归属 @param pie_owner PIE归属 @param draining 宿主交接状态 @param corrective 收尾操作 @return 原因 完整阻塞证据 定向保存范围 */"""
    pause = operators.paused(job["owner"])
    if pause and not job.get("cancel_requested"):
        return "OPERATOR_PAUSED", {"operator": pause["by"], "until": pause["until"]}, set()
    if draining:
        return "HOST_DRAINING", {}, set()
    active_ids = {item["id"] if isinstance(item, dict) else item for item in activity.get("activities", [])}
    if job["await_activity"] & active_ids:
        return "ACTIVITY_RUNNING", {}, set()
    operations = job["operations"][job["completed"]:]
    if job["access"] == "read" or all(item["access"] == "read" for item in operations):
        return None, {}, set()
    for conflict in assets.conflicts(job["id"], job["targets"]):
        holder = jobs[conflict["batch"]]
        same_owner = holder["owner"] == job["owner"]
        within = bool(job["targets"]) and conflicting_packages(job["targets"], assets.view(holder["id"])["packages"]) == job["targets"]
        continuation = conflict["phase"] == "fault" and all(item["contract"]["id"] != "editor.reload_assets_from_disk" for item in operations)
        if same_owner and within and (corrective or continuation):
            continue
        return "ASSET_BUSY", {**conflict, "mine": same_owner}, set()
    blocking = [item for item in activity.get("activities", []) if not isinstance(item, dict) or item.get("blocking", True)]
    if blocking:
        owners = {activity_owners.get(item["id"] if isinstance(item, dict) else item) for item in blocking}
        if owners - {job["owner"]}:
            return "ACTIVITY_OWNED", {}, set()
        if operations[0]["access"] != "read" and operations[0]["world"] == "editor":
            return "ACTIVITY_RUNNING", {}, set()
    if activity.get("pie_active") or activity.get("worlds"):
        privileged_stop = operators.level(job["owner"]) == 0 and all(
            item["contract"]["name"] == "StopPIE" or item["contract"].get("action") == "stop_pie" for item in operations)
        if pie_owner != job["owner"] and not privileged_stop:
            return "PIE_OWNED", {}, set()
        if operations[0]["access"] != "read" and operations[0]["world"] == "editor":
            return "EDITOR_WORLD_REQUIRED", {}, set()
    dirty = set(activity.get("dirty_packages", [])) - job["owned_dirty"]
    for identity, claim in assets.claims.items():
        if claim["phase"] == "fault" and jobs[identity]["owner"] == job["owner"]:
            dirty -= conflicting_packages(jobs[identity]["owned_dirty"], job["targets"])
    if job.get("yield_dirty") is not None:
        dirty.intersection_update(job["yield_dirty"])
    packages = conflicting_packages(dirty, job["targets"])
    if corrective:
        packages = set()
    return None, {}, packages
