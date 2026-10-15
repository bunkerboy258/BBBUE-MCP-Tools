"""/** 批次状态与可直接调用的后续动作 */"""

import copy
import json
import re


def next_call(entry, **arguments):
    """/** @param tool\t公共入口 @param arguments\t完整参数 @return 可执行的调用描述 */"""
    return {"tool": entry, "arguments": arguments}


def response(value):
    """/** @param value\t批次或服务结果 @return 唯一后续动作与当前完成证据 */"""
    result = dict(value) if isinstance(value, dict) else value
    if not isinstance(result, dict):
        return result
    if not any(key in result for key in ("status", "code", "batch", "failure")):
        return result
    result.setdefault("next", None)
    active = result.get("status") in {"queued", "running", "waiting", "cancelling", "connecting", "offline", "unresponsive", "draining"} or result.get("recovering", False)
    recovery = result.get("assets", {}).get("phase") == "fault"
    transient = result.get("code") in {"HOST_UNVERIFIED", "EXECUTION_UNVERIFIED", "GATEWAY_RESTARTED", "EDITOR_OFFLINE", "EDITOR_CONNECTING", "HOST_BUSY", "HOST_DRAINING", "BATCH_ACTIVE", "TEST_HOST_STARTING", "TEST_BATCH_ACTIVE", "OWNED_ACTIVITY_PENDING"}
    if active or recovery or transient:
        arguments = {"wait_seconds": min(30, result.get("retry_after_seconds", 30))}
        if result.get("batch") and isinstance(result["batch"], str) and (active or recovery):
            arguments["batch"] = result["batch"]
        if "revision" in result:
            arguments["after_revision"] = result["revision"]
        result["next"] = next_call("inspect_tasks", **arguments)
    blocked = result.get("blocked")
    if isinstance(blocked, dict):
        blocked = dict(blocked)
        blocked.pop("next", None)
        result["blocked"] = blocked
    failure = result.get("failure")
    if isinstance(failure, dict) and failure.get("needs"):
        result["needs"] = copy.deepcopy(failure["needs"])
        if not recovery:
            result["next"] = failure.get("next")
    if result.get("code") == "OPERATOR_REQUIRED":
        result["needs"] = [{"path": "/arguments/task", "rule": "登记任务", "schema": {"type": "string", "minLength": 1, "maxLength": 20}}]
    if result.get("code") == "OPERATOR_LEVEL_REQUIRED":
        result["needs"] = [{"path": "/operator/level", "rule": "管理权限", "schema": {"const": result.get("required_level", 0)}}]
    if result.get("code") == "ASSET_SCOPE_REQUIRED":
        target = result.get("details", {}).get("tool")
        if target:
            result["next"] = next_call("describe_tool", tool=target)
    return result


def resolve_schema(schema, root):
    """/** @param schema\t当前字段 @param root\t完整契约 @return 有界展开的本地引用 */"""
    visited = set()
    for depth in range(16):
        if not isinstance(schema, dict):
            return {}
        reference = schema.get("$ref", "")
        if not reference.startswith("#/") or reference in visited:
            return schema
        visited.add(reference)
        schema = root
        for name in reference[2:].split("/"):
            schema = schema.get(name.replace("~1", "/").replace("~0", "~"), {})
    return schema


def field_schema(schema, pointer):
    """/** @param schema\t契约 @param pointer\t参数内字段路径 @return 对应字段定义 */"""
    root = schema
    current = schema
    for part in pointer:
        current = resolve_schema(current, root)
        if current.get("type") == "array" or "items" in current:
            current = current.get("items", {})
            continue
        current = current.get("properties", {}).get(part.replace("~1", "/").replace("~0", "~"), current.get("additionalProperties", {}))
    return copy.deepcopy(resolve_schema(current, root))


def argument_failure(details, schema, tool, operation=None, prefix="/arguments"):
    """/** @param details\t校验原因 @param schema\t字段契约 @param tool\t实际工具 @param operation\t批次操作序号 @param prefix\t契约对应路径 @return 精确补参证据 */"""
    text = str(details)
    pointer, separator, rule = text.rpartition(": ")
    if not separator:
        pointer, rule = "/arguments", text
    match = re.match(r"^/operations/(\d+)/arguments", pointer)
    local = pointer
    if match:
        operation = int(match.group(1))
        local = "/arguments" + pointer[match.end():]
    parts = local.removeprefix(prefix).strip("/").split("/") if local != prefix else []
    expected = field_schema(schema, parts)
    result = {"status": "rejected", "code": "ARGUMENT_INVALID", "tool": tool,
              "details": text, "needs": [{"path": pointer, "rule": rule, "schema": expected}], "next": None}
    if rule == "additionalProperties":
        parent = field_schema(schema, parts[:-1])
        result["needs"][0].update(action="remove", allowed_fields=sorted(parent.get("properties", {})))
    if operation is not None:
        result["operation"] = operation
    if len(json.dumps(expected, ensure_ascii=False).encode()) > 2048:
        result["needs"][0]["schema"] = {key: expected[key] for key in ("type", "required", "enum") if key in expected}
        result["next"] = next_call("describe_tool", tool=tool)
    return result
