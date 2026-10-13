import json
import base64
import hashlib
from pathlib import Path


def object_path(value):
    """/** @param value\t对象或包路径 @return 原生对象引用路径 */"""
    if isinstance(value, str) and value.startswith(("/Game/", "/Engine/")) and "." not in value and ":" not in value:
        return value + "." + value.rsplit("/", 1)[-1]
    return value


def result_artifacts(value, directory):
    """/** @param value\t原生结果 @param directory\t所属输出目录 @return 文件证据与紧凑业务结果 */"""
    if isinstance(value, list):
        return [result_artifacts(item, directory) for item in value]
    if not isinstance(value, dict):
        return value
    payload = value.get("image_data")
    if value.get("type") == "image":
        payload = value.get("data")
    if isinstance(payload, str):
        data = base64.b64decode(payload, validate=True)
        digest = hashlib.sha256(data).hexdigest()
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if any(path.is_symlink() or (path.exists() and getattr(path.stat(), "st_file_attributes", 0) & 0x400) for path in (root, *root.parents)):
            raise ValueError("RESULT_OUTPUT_LINK")
        suffix = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".bin"
        output = root / (digest[:24] + suffix)
        output.write_bytes(data)
        result = {key: item for key, item in value.items() if key not in {"image_data", "data"}}
        result["artifact"] = {"path": str(output), "bytes": len(data), "sha256": digest, "mime_type": value.get("mimeType", "image/png")}
        return result
    return {key: result_artifacts(item, directory) for key, item in value.items()}


def clean_result_artifacts(directory):
    """/** @param directory\t所属输出目录 @return 已交付输出回收完成 */"""
    root = Path(directory)
    if not root.exists():
        return
    if root.parent.name != "McpResults" or len(root.name) != 16 or any(char not in "0123456789abcdef" for char in root.name):
        raise ValueError("RESULT_OUTPUT_IDENTITY")
    paths = list(root.iterdir())
    if any(path.is_symlink() or (getattr(path.stat(), "st_file_attributes", 0) & 0x400) for path in (root, *root.parents, *paths)) or any(not path.is_file() for path in paths):
        raise ValueError("RESULT_OUTPUT_LINK")
    for path in paths:
        path.unlink()
    root.rmdir()


class McpBusinessError(RuntimeError):
    """/** 业务失败保留原始结果供调用者检查 */"""

    def __init__(self, value):
        """
        /**
         * @param value	业务失败结果
         * @return 异常实例
         */
        """
        self.value = value
        super().__init__("MCP 业务失败: " + json.dumps(value, ensure_ascii=False))


class McpExecutionError(McpBusinessError):
    """/** 工具提供已核实的业务失败执行证据 */"""

    def __init__(self, state, code, message, details=None):
        """
        /**
         * @param state\t执行前拒绝或部分执行
         * @param code\t固定业务错误码
         * @param message\t客户端可读说明
         * @param details\t实际执行与清理证据
         * @return 可通过官方字符串返回值传输的业务失败
         */
        """
        if state not in {"rejected", "partial"}:
            raise ValueError("执行失败证据需要明确状态")
        super().__init__({"success": False, "code": code, "error": message,
            "execution": {"state": state, "details": details or {}}})


def decode_json_value(value):
    """
    /**
     * @param value	字符串或已经解析的返回值
     * @return JSON 值或原始普通文本
     */
    """
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def require_business_success(value):
    """
    /**
     * 仅检查业务根字段 不把查询结果中的嵌套诊断当作调用失败
     * @param value	原始业务返回值
     * @return 检查后的业务值
     */
    """
    value = decode_json_value(value)
    if isinstance(value, dict) and (value.get("success") is False or value.get("error") or (value.get("status") == "rejected" and "batch" not in value)):
        raise McpBusinessError(value)
    return value


def decode_tool_result(response):
    """
    /**
     * 解码官方 MCP 返回包装 并检查业务失败
     * @param response	完整协议响应
     * @return 业务返回值或发现接口的普通文本
     */
    """
    result = response["result"]
    value = result.get("structuredContent")
    if value is None:
        texts = [item["text"] for item in result.get("content", []) if item.get("type") == "text"]
        if len(texts) != 1:
            if result.get("isError"):
                raise McpBusinessError({"error": "TOOL_ERROR", "execution": {"state": "unknown"}})
            return result
        value = decode_json_value(texts[0])
    if isinstance(value, dict) and "returnValue" in value:
        value = value["returnValue"]
    value = require_business_success(value)
    if result.get("isError"):
        if isinstance(value, dict):
            raise McpBusinessError(value)
        raise McpBusinessError({"error": value, "execution": {"state": "unknown"}})
    return value


def graph_view(snapshot, view="overview", node_guids=None, offset=0, limit=40, expected_snapshot=""):
    """/** @param snapshot\t完整原生快照 @param view\t读取视图 @param node_guids\t指定节点 @param offset\t分页起点 @param limit\t分页数量 @param expected_snapshot\t分页版本 @return 完整节点范围与单向连线 */"""
    if view not in {"overview", "logic", "geometry"} or type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 128:
        raise ValueError("GRAPH_VIEW_INVALID")
    if (offset and not expected_snapshot) or (expected_snapshot and expected_snapshot != snapshot["snapshot"]):
        raise ValueError("GRAPH_SNAPSHOT_CHANGED")
    nodes = snapshot["nodes"]
    if node_guids:
        wanted = set(node_guids)
        if wanted - {node["guid"] for node in nodes}:
            raise ValueError("GRAPH_NODE_UNKNOWN")
        nodes = [node for node in nodes if node["guid"] in wanted]
    page = nodes[offset:offset + limit]
    result = {key: value for key, value in snapshot.items() if key != "nodes" and key != "geometry"}
    result.update(view=view, totalNodes=len(snapshot["nodes"]), selectedNodes=len(nodes), offset=offset)
    result["nodes"] = []
    links = []
    for node in page:
        if view == "overview":
            result["nodes"].append({key: node[key] for key in ("guid", "title", "nodeClass", "function", "variable", "isComment", "nodeComment", "details", "members") if key in node})
            continue
        if view == "geometry":
            result["nodes"].append({key: value for key, value in node.items() if key in {"guid", "path", "x", "y", "width", "height", "isComment", "members", "nodeComment", "details", "pins", "estimated"}})
            continue
        item = {key: value for key, value in node.items() if key not in {"x", "y", "width", "height", "pins"}}
        item["pins"] = []
        for pin in node.get("pins", []):
            item["pins"].append({key: value for key, value in pin.items() if key != "links"})
            if "output" in str(pin.get("direction", "")).casefold():
                links.extend({"source": node["guid"], "pin": pin.get("name"), "target": link} for link in pin.get("links", []))
        result["nodes"].append(item)
    if view == "logic":
        result["links"] = links
    if view == "geometry" and "geometry" in snapshot:
        result["geometry"] = snapshot["geometry"]
    if offset + len(page) < len(nodes):
        result["next_page"] = {"offset": offset + len(page), "expected_snapshot": snapshot["snapshot"]}
    return result


def public_value(value):
    """/** @param value\t原生结果 @return 统一路径引用的业务结果 */"""
    if isinstance(value, list):
        return [public_value(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"refPath"}:
            return value["refPath"]
        return {key: public_value(item) for key, item in value.items()}
    return value


def requested_values_match(expected, actual):
    """/** @param expected\t声明字段 @param actual\t原生回读 @return 每个声明字段与实际值一致 */"""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and requested_values_match(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(requested_values_match(left, right) for left, right in zip(expected, actual))
    if isinstance(expected, bool):
        return type(actual) is bool and expected == actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        import math
        return math.isclose(expected, actual, rel_tol=1e-6, abs_tol=1e-6)
    return expected == actual


def property_schema(value):
    """/** @param value\t原生反射类型 @return 使用路径字符串的公开字段类型 */"""
    if isinstance(value, dict):
        if "refPath" in value.get("properties", {}):
            return {"type": "string", "format": "unreal-object-path"}
        return {key: property_schema(child) for key, child in value.items()}
    if isinstance(value, list):
        return [property_schema(child) for child in value]
    return value


def native_property_values(value, schema):
    """/** @param value\t公开属性值 @param schema\t原生字段类型 @return 原生引用与嵌套结构 */"""
    if not isinstance(schema, dict):
        return value
    if isinstance(value, str):
        for branch in schema.get("anyOf", []):
            if "refPath" in branch.get("properties", {}):
                return {"refPath": object_path(value)}
    if "refPath" in schema.get("properties", {}) and isinstance(value, str):
        return {"refPath": object_path(value)}
    if isinstance(value, dict):
        return {key: native_property_values(child, schema.get("properties", {}).get(key, {})) for key, child in value.items()}
    if isinstance(value, list):
        return [native_property_values(child, schema.get("items", {})) for child in value]
    return value
