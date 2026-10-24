import ast
import copy
from functools import lru_cache, wraps
import inspect
import json
import hashlib
from pathlib import Path
import re

from MCP.mcp_result import require_business_success, McpExecutionError
from MCP.mcp_asset_scope import asset_targets
from MCP.mcp_discovery import ALIASES, HINTS, SUMMARIES
from MCP.mcp_workflows import guidance, ROUTES, PURPOSES
from MCP.mcp_contracts import TOOL_POLICIES, compile_contract, default_arguments


TOOL_DOMAINS = {
    "BBBHudAssetToolset": "hud",
    "BBBTraversalToolset": "traversal",
    "BBBMeleeToolset": "melee",
    "BBBAnimationMigrationToolset": "animation",
    "BBBExternalToolset": "external",
    "BBBGenericEditorToolset": "editor",
    "BBBLevelEditingToolset": "level",
    "BBBBlueprintGraphToolset": "blueprint",
    "BBBRigidPartToolset": "rigid",
    "BBBControlRigAuthoringToolset": "control_rig",
    "BBBHandRetargetBatchToolset": "control_rig",
    "BBBGripAuthoringToolset": "grip",
    "BBBMcpRuntimeToolset": "runtime",
    "BBBMcpTaskToolset": None,
    "BBBAssetMaintenanceToolset": "assets",
    "BBBAnimationPreviewToolset": "preview",
    "BBBAnimationGraphToolset": "animation_graph",
    "BBBAnimationFinishToolset": "animation_finish",
    "BBBHitReactionToolset": "hit",
    "BBBMonsterGoreToolset": "monster_gore",
    "BBBSkeletalMeshImportToolset": "skeletal_import",
    "BBBRetargetAssetAuditToolset": "retarget",
    "AssetTools": "asset",
    "ObjectTools": "object",
    "BlueprintTools": "blueprint_base",
    "ControlRigTools": "control_rig_base",
    "SequencerTools": "sequencer",
    "EditorAppToolset": "app",
}
TOOLSET_ROUTES = tuple(name for name in TOOL_DOMAINS if name.startswith("BBB"))

HELPER_MODULES = (
    "BBBGraphFormatter",
    "BBBGripCaptureTools",
    "BBBGripGeometryTools",
    "BBBHandPoseLayerTools",
    "BBBAnimationMotionTools",
    "BBBAnimationTrajectoryTools", "BBBArmTwistTools", "BBBWeaponHandlingTools", "BBBRecoilProbeTools",
    "BBBAnimationViewTools",
    "BBBFactAnimationCaptureTools",
    "BBBAnimationPoseBaking",
    "BBBSoundAssetAudit", "BBBRecoilAnimationTools", "BBBDisplayAssetCaptureTools", "BBBBlueprintMigration",
)
SCRIPTS_ROOT = Path(__file__).resolve().parent


def register_activity(identity, status, blocking=True, wait=True):
    """/** @param identity	活动唯一标识 @param status	实际状态回读函数 @param blocking	保护共享副作用 @param wait	等待完成后续跑 @return 登记完成 */"""
    import builtins
    if not hasattr(builtins, "BBB_MCP_ACTIVITIES"):
        builtins.BBB_MCP_ACTIVITIES = {}
    builtins.BBB_MCP_ACTIVITIES[identity] = (status, blocking, wait)


def active_activities():
    """/** @return 已登记活动的实际状态 */"""
    import builtins
    records = getattr(builtins, "BBB_MCP_ACTIVITIES", {})
    active = []
    for identity, (callback, blocking, wait) in list(records.items()):
        try:
            value = callback()
        except Exception:
            value = {"status": "unknown"}
        if isinstance(value, bool):
            value = {"status": "running" if value else "completed"}
        if value.get("status") in {"pending", "running", "unknown"} or value.get("running") or value.get("state") in {"waiting", "running"} or value.get("releaseError") or value.get("cleanupError"):
            item = {"id": identity, "status": value.get("status", value.get("state", "running"))}
            if not blocking:
                item["blocking"] = False
            if not wait:
                item["wait"] = False
            active.append(item)
            continue
        records.pop(identity, None)
    return sorted(active, key=lambda item: item["id"])


def start_automation_activity(test_filter):
    """/** @param test_filter 测试前缀 @return 已登记的正式测试请求 */"""
    import uuid
    import unreal
    command = unreal.SystemLibrary.get_command_line()
    match = re.search(r'(?i)(?:^|\s)-(?:abslog|log)=(?:"([^"]+)"|(\S+))', command)
    log_name = Path(unreal.Paths.get_project_file_path()).stem + ".log"
    if match is not None:
        log_name = match.group(1) or match.group(2)
    log_path = Path(log_name)
    if not log_path.is_absolute():
        log_path = Path(unreal.Paths.project_log_dir()) / log_path
    if not log_path.is_file():
        raise McpExecutionError("rejected", "AUTOMATION_LOG_REQUIRED", "测试活动需要当前宿主日志")
    state = {"status": "pending", "offset": log_path.stat().st_size, "tail": b"", "seen": False}
    marker = "BBB_MCP_AUTOMATION_" + uuid.uuid4().hex
    def status():
        with log_path.open("rb") as handle:
            handle.seek(state["offset"])
            value = state["tail"] + handle.read(65536)
            state["offset"] = handle.tell()
        if marker.encode() in value:
            state["seen"] = True
            value = value.split(marker.encode(), 1)[1]
            state["status"] = "running"
        if state["seen"] and b"Automation Test Queue Empty" in value:
            state["status"] = "completed"
        state["tail"] = value[-256:]
        return {"status": state["status"]}
    register_activity("automation:" + marker, status)
    unreal.log(marker)
    unreal.SystemLibrary.execute_console_command(None, "Automation RunTests " + test_filter)
    return {"filter": test_filter, "requested": True, "log_file": str(log_path), "log_offset": state["offset"]}


@lru_cache(maxsize=None)
def source_index(module_name):
    """
    /**
     * 只缓存当前加载周期的源码元数据 不缓存资产或注册状态
     * @param module_name	本仓库模块名称
     * @return 源码函数与模块导入映射
     */
    """
    path = SCRIPTS_ROOT / (module_name + ".py")
    if module_name.endswith("_actions"):
        path = SCRIPTS_ROOT / "MCP/ThirdParty/GenOrca" / (module_name + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    functions = {}
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions[node.name] = node
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name
        if isinstance(node, ast.ImportFrom) and node.module in HELPER_MODULES:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
    definition = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == module_name), None)
    public = []
    if definition is not None:
        public = [node.name for node in definition.body if isinstance(node, ast.FunctionDef)
            and any(ast.unparse(decorator) in {"mcp_tool", "toolset_registry.tool_call"} for decorator in node.decorator_list)]
    return {"functions": functions, "imports": imports, "public_tools": sorted(public)}


@lru_cache(maxsize=None)
def native_requirements(module_name, function_name):
    """
    /**
     * @param module_name	源码模块
     * @param function_name	工具或辅助函数
     * @return 当前加载周期的静态原生引用 不包含宿主状态
     */
    """
    return _walk_native_requirements(module_name, function_name, set())


def _walk_native_requirements(module_name, function_name, visited, arguments=None):
    """
    /**
     * 追踪静态原生引用和本仓库辅助调用 动态业务条件仍由工具预检
     * @param module_name	源码模块
     * @param function_name	工具或辅助函数
     * @param visited	当前递归路径
     * @return 原生类到所需函数名称集合
     */
    """
    key = (module_name, function_name, repr(arguments))
    if key in visited:
        return {}
    visited.add(key)
    index = source_index(module_name)
    function = index["functions"].get(function_name)
    if function is None:
        return {}
    if arguments is not None:
        function = copy.deepcopy(function)
        function.body = selected_statements(function.body, arguments)
    requirements = {}
    aliases = {}
    call_targets = {id(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "unreal":
            if node.attr.startswith("BBB"):
                aliases[ast.unparse(node)] = node.attr
                requirements.setdefault(node.attr, set())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and ast.unparse(node.args[0]) == "unreal" and isinstance(node.args[1], ast.Constant):
                name = node.args[1].value
                if isinstance(name, str) and (name.startswith("BBB")):
                    aliases[ast.unparse(node)] = name
                    requirements.setdefault(name, set())
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and ast.unparse(node.value) in aliases:
            for target in node.targets:
                aliases[ast.unparse(target)] = aliases[ast.unparse(node.value)]
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and ast.unparse(node.value) in aliases:
            owner = aliases[ast.unparse(node.value)]
            if id(node) in call_targets or owner.endswith("Library"):
                requirements[owner].add(node.attr)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and len(node.args) >= 2:
            owner = aliases.get(ast.unparse(node.args[0]))
            if owner and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                requirements[owner].add(node.args[1].value)
        if not isinstance(node, ast.Call):
            continue
        child = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in index["functions"]:
                child = (module_name, name)
            if isinstance(index["imports"].get(name), tuple):
                child = index["imports"][name]
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            imported = index["imports"].get(node.func.value.id)
            if imported in HELPER_MODULES:
                child = (imported, node.func.attr)
            if node.func.value.id == module_name and node.func.attr in index["functions"]:
                child = (module_name, node.func.attr)
        if child:
            bound = None
            if arguments is not None:
                target = source_index(child[0])["functions"].get(child[1])
                if target is not None:
                    bound = {parameter.arg: value for parameter, expression in zip(target.args.args, node.args) for value in [static_value(expression, arguments)] if value is not UNKNOWN_VALUE}
                    bound.update({keyword.arg: value for keyword in node.keywords for value in [static_value(keyword.value, arguments)] if keyword.arg is not None and value is not UNKNOWN_VALUE})
            for name, methods in _walk_native_requirements(*child, visited, bound).items():
                requirements.setdefault(name, set()).update(methods)
    return requirements


UNKNOWN_VALUE = object()


def static_value(expression, arguments):
    """/** @param expression\t源码条件 @param arguments\t已绑定标量参数 @return 可确定值或未知标记 */"""
    if isinstance(expression, ast.Name):
        value = arguments.get(expression.id, UNKNOWN_VALUE)
        return value if isinstance(value, (str, int, float, bool, type(None))) else UNKNOWN_VALUE
    try:
        return ast.literal_eval(expression)
    except (ValueError, TypeError):
        pass
    if isinstance(expression, ast.UnaryOp) and isinstance(expression.op, ast.Not):
        value = static_value(expression.operand, arguments)
        return not value if value is not UNKNOWN_VALUE else UNKNOWN_VALUE
    if isinstance(expression, ast.BoolOp):
        values = [static_value(child, arguments) for child in expression.values]
        if isinstance(expression.op, ast.And) and any(value is not UNKNOWN_VALUE and not value for value in values):
            return False
        if isinstance(expression.op, ast.Or) and any(value is not UNKNOWN_VALUE and value for value in values):
            return True
        if all(value is not UNKNOWN_VALUE for value in values):
            return all(values) if isinstance(expression.op, ast.And) else any(values)
    if isinstance(expression, ast.Compare) and len(expression.ops) == 1:
        left = static_value(expression.left, arguments)
        right = static_value(expression.comparators[0], arguments)
        if left is not UNKNOWN_VALUE and right is not UNKNOWN_VALUE:
            operations = {ast.Eq: lambda: left == right, ast.NotEq: lambda: left != right, ast.In: lambda: left in right, ast.NotIn: lambda: left not in right, ast.Lt: lambda: left < right, ast.LtE: lambda: left <= right, ast.Gt: lambda: left > right, ast.GtE: lambda: left >= right, ast.Is: lambda: left is right, ast.IsNot: lambda: left is not right}
            callback = operations.get(type(expression.ops[0]))
            if callback is not None:
                try:
                    return callback()
                except TypeError:
                    return UNKNOWN_VALUE
    return UNKNOWN_VALUE


def selected_statements(statements, arguments):
    """/** @param statements\t函数语句 @param arguments\t已绑定参数 @return 当前分支可能执行的语句 */"""
    result = []
    for statement in statements:
        if isinstance(statement, ast.If):
            value = static_value(statement.test, arguments)
            if value is not UNKNOWN_VALUE:
                selected = selected_statements(statement.body if value else statement.orelse, arguments)
                result.extend(selected)
                if selected and isinstance(selected[-1], (ast.Return, ast.Raise)):
                    break
                continue
        result.append(statement)
        if isinstance(statement, (ast.Return, ast.Raise)):
            break
    return result


def dependency_status(requirements, unreal_module):
    """
    /**
     * @param requirements	原生类及函数要求
     * @param unreal_module	当前宿主 API
     * @return 缺失符号与可用状态
     */
    """
    missing_classes = []
    missing_functions = []
    for name, methods in sorted(requirements.items()):
        definition = getattr(unreal_module, name, None)
        if definition is None:
            missing_classes.append(name)
            continue
        for method in sorted(methods):
            if not callable(getattr(definition, method, None)):
                missing_functions.append(name + "." + method)
    return {
        "required_native_classes": sorted(requirements),
        "required_native_functions": sorted(name + "." + method for name, methods in requirements.items() for method in methods),
        "missing_native_classes": missing_classes,
        "missing_native_functions": missing_functions,
        "native_dependencies_ready": not missing_classes and not missing_functions,
    }


def mcp_tool(method):
    """
    /**
     * 统一项目工具的原生符号与业务失败边界 保留官方注册和参数结构
     * @param method	静态公开工具
     * @return 官方可注册函数
     */
    """
    import unreal
    import toolset_registry

    function = method.__func__ if isinstance(method, staticmethod) else method
    module_name = Path(function.__code__.co_filename).stem
    requirements = native_requirements(module_name, function.__name__)

    @wraps(function)
    def invoke(*args, **kwargs):
        arguments = inspect.signature(function).bind(*args, **kwargs)
        arguments.apply_defaults()
        selected = _walk_native_requirements(module_name, function.__name__, set(), arguments.arguments) if requirements else {}
        status = dependency_status(selected, unreal)
        if not status["native_dependencies_ready"]:
            return json.dumps(McpExecutionError("rejected", "NATIVE_DEPENDENCY_MISSING", "原生依赖待准备", status).value, ensure_ascii=False)
        try:
            result = function(*args, **kwargs)
        except McpExecutionError as error:
            return json.dumps(error.value, ensure_ascii=False)
        require_business_success(result)
        return result

    invoke.__signature__ = inspect.signature(function)
    return toolset_registry.tool_call(staticmethod(invoke))






BLOCKED_TOOLS = {
    "execute_tool_script", "execute_python_command", "execute_python_script", "execute_editor_script",
    "execute_console_command", "execute_script",
}







def clean_schema(value, fields=False):
    """/** @param value 官方参数结构 @return 精简参数结构 */"""
    if isinstance(value, list):
        return [clean_schema(item) for item in value]
    if isinstance(value, dict):
        result = {key: clean_schema(item, key in {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"})
            for key, item in value.items() if fields or key not in {"title", "examples", "$schema"}}
        return result
    return value


class ArgumentValidationError(ValueError):
    """/** 有界字段问题集合 */"""

    def __init__(self, issues):
        """/** @param issues 字段问题 @return 保留首项文本与完整有界证据的异常 */"""
        self.issues = issues[:16]
        super().__init__(self.issues[0])


def validate_arguments(value, schema, path="/arguments", root=None):
    """/** @param value 参数值 @param schema 参数结构 @param path 字段路径 @return 全部有界字段问题核验完成 */"""
    issues = []
    _validate_arguments(value, schema, path, root, issues)
    if issues:
        raise ArgumentValidationError(issues)


def _validate_arguments(value, schema, path, root, issues):
    """/** @param value 参数值 @param schema 参数结构 @param path 字段路径 @return 参数核验完成 */"""
    if root is None:
        root = schema
    if len(issues) >= 16:
        return
    if schema is True:
        return
    if schema is False:
        issues.append(path + ": forbidden")
        return
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/"):
            raise ValueError("LOCAL_SCHEMA_REFERENCE_REQUIRED")
        child = root
        for part in reference[2:].split("/"):
            child = child[part.replace("~1", "/").replace("~0", "~")]
        _validate_arguments(value, child, path, root, issues)
    for branch in schema.get("allOf", []):
        _validate_arguments(value, branch, path, root, issues)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            accepted = 0
            for branch in schema[keyword]:
                try:
                    validate_arguments(value, branch, path, root)
                    accepted += 1
                except ValueError:
                    pass
            if accepted == 0 or (keyword == "oneOf" and accepted != 1):
                issues.append(path + ": schema branch")
    expected = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float), "null": type(None)}
    if expected is not None:
        options = expected if isinstance(expected, list) else [expected]
        accepted = any(isinstance(value, types[item]) and not (item in {"integer", "number"} and isinstance(value, bool)) for item in options)
        if not accepted:
            issues.append(path + ": expected " + str(expected))
            return
    if "enum" in schema and value not in schema["enum"]:
        issues.append(path + ": enum")
    if "const" in schema and value != schema["const"]:
        issues.append(path + ": const")
    if "if" in schema:
        branch = "then"
        try:
            validate_arguments(value, schema["if"], path, root)
        except ValueError:
            branch = "else"
        if branch in schema:
            _validate_arguments(value, schema[branch], path, root, issues)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        for key in sorted(missing)[:max(0, 16 - len(issues))]:
            issues.append(path + "/" + key.replace("~", "~0").replace("/", "~1") + ": required")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            for key in sorted(set(value) - set(properties))[:max(0, 16 - len(issues))]:
                issues.append(path + "/" + key.replace("~", "~0").replace("/", "~1") + ": additionalProperties")
        for key, item in value.items():
            child = properties.get(key)
            if child is None and isinstance(schema.get("additionalProperties"), dict):
                child = schema["additionalProperties"]
            if child is not None:
                _validate_arguments(item, child, path + "/" + key.replace("~", "~0").replace("/", "~1"), root, issues)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            issues.append(path + ": items")
        for index, item in enumerate(value):
            _validate_arguments(item, schema.get("items", {}), path + "/" + str(index), root, issues)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            issues.append(path + ": length")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            issues.append(path + ": pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        import math
        if not math.isfinite(value) or value < schema.get("minimum", value) or value > schema.get("maximum", value):
            issues.append(path + ": range")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            issues.append(path + ": exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            issues.append(path + ": exclusiveMaximum")


def tool_contract(toolset, name, schema, description=""):
    """/** @param toolset 注册工具集 @param name 函数名称 @param schema 官方参数 @param description 原用途 @return 唯一工具契约 */"""
    definition = re.sub(r"_0x[0-9a-fA-F]{8}$", "", toolset.rsplit(".", 1)[-1])
    domain = TOOL_DOMAINS.get(definition)
    if domain is None and not definition.startswith("BBB") and definition != "ProgrammaticToolset":
        domain = re.sub(r"(?<!^)(?=[A-Z])", "_", definition.removesuffix("Tools")).lower()
    if domain is None or name in BLOCKED_TOOLS or definition == "BBBExternalToolset":
        return None
    parameters = clean_schema(schema)
    parameters.setdefault("additionalProperties", False)
    if definition.startswith("BBB"):
        function = source_index(definition)["functions"].get(name)
        if function is None or name.startswith("_"):
            return None
        if function is not None:
            for argument, value in zip(function.args.args[-len(function.args.defaults):], function.args.defaults):
                try:
                    default = ast.literal_eval(value)
                except (ValueError, TypeError):
                    continue
                parameters.get("properties", {}).get(argument.arg, {}).setdefault("default", default)
            if "action" in parameters.get("properties", {}):
                actions = set()
                for node in ast.walk(function):
                    if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "action":
                        for child in node.comparators:
                            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                                actions.add(child.value)
                            if isinstance(child, (ast.Tuple, ast.List, ast.Set)):
                                actions.update(value.value for value in child.elts if isinstance(value, ast.Constant) and isinstance(value.value, str))
                if actions:
                    parameters["properties"]["action"]["enum"] = sorted(actions)
    access = TOOL_POLICIES.get(domain + "." + name, {}).get("access", "write")
    if "access" not in TOOL_POLICIES.get(domain + "." + name, {}) and name.startswith(("audit_", "validate_", "verify_", "export_")):
        access = "read"
    if not definition.startswith("BBB") and (name.startswith(("get_", "list_", "find_", "is_", "has_", "search_", "read_")) or name in {"can_edit", "load_asset", "trace_world"}):
        access = "read"
    if not definition.startswith("BBB") and name.startswith(("Get", "Is", "Has", "Search", "List", "WorldPosTo", "ScreenCoordsTo")):
        access = "read"
    if name in {"get_actor_transform_at_frame", "get_node_type_pins"}:
        access = "write"
    world = "any" if access == "read" else "editor"
    if "pie" in name.lower().split("_") or definition == "BBBAnimationPreviewToolset" or TOOL_POLICIES.get(domain + "." + name, {}).get("world") == "pie":
        world = "pie" if access == "write" else "any"
    if definition == "EditorAppToolset" and name in {"StartPIE", "StopPIE"}:
        access, world = "pie", "any"
    if definition == "BBBAnimationMigrationToolset" and name in {"start_locomotion_runtime_probe", "stop_locomotion_runtime_probe"}:
        access, world = "pie", "any"
    if definition == "BBBGenericEditorToolset" and name == "run_automation_tests":
        access, world = "pie", "any"
    summary = re.sub(r"/\*\*|\*/|^\s*\*", "", description, flags=re.M).strip().split("\n")[0][:100]
    return compile_contract({"id": domain + "." + name, "toolset": toolset, "name": name, "parameters": parameters,
        "summary": summary or name, "access": access, "world": world, "definition": definition})


def resolve_access(contract, arguments):
    """/** @param contract 工具契约 @param arguments 本次参数 @return 权限与世界约束 */"""
    access, world = contract["access"], contract["world"]
    if contract["id"] == "grip.author_weapon" and arguments.get("action", "inspect") in {"inspect", "audit", "review"}:
        return "read", "editor"
    if contract["id"] == "control_rig.capture_attachment_pose" and arguments.get("action", "start") == "status":
        return "read", "any"
    if contract["definition"] == "BBBGenericEditorToolset" and contract["name"] == "schedule_pie_actor_function" and arguments.get("action") == "status":
        return "read", "any"
    if "dry_run" in contract["parameters"].get("properties", {}) and arguments.get("dry_run", contract["parameters"]["properties"]["dry_run"].get("default", False)) is True:
        access, world = "read", "any"
    if contract["definition"] == "BBBAnimationPreviewToolset" and contract["name"] == "inspect_mass_inspection_population" and arguments.get("pause_game", False) is False:
        access, world = "read", "any"
    if contract["definition"] == "BBBAnimationMigrationToolset" and contract["name"] in {"sample_weapon_handling_runtime", "sample_backward_recoil_runtime", "sample_recoil_runtime"} and arguments.get("action") == "status":
        access, world = "read", "any"
    if contract["definition"] == "BBBGenericEditorToolset" and contract["name"] == "generate_and_inspect_pcg" and arguments.get("generate", False) is False:
        access = "read"
    return access, world


def write_scope(contract, arguments, access=None, world=None):
    """/** @param contract 契约 @param arguments 本次参数 @param access 权限 @param world 世界 @return 目标字段值与范围证据 */"""
    if access is None:
        access, world = resolve_access(contract, arguments)
    scope = contract.get("scope", TOOL_POLICIES.get(contract["id"], {}).get("scope", {}))
    if scope.get("kind") in {"session", "world"}:
        return [], True
    row_fields = scope.get("rows")
    if row_fields is not None:
        field, key = row_fields
        keys = key if isinstance(key, list) else [key]
        rows = arguments.get(field, [])
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or not isinstance(row.get(name), str) or not asset_targets(row[name]) for row in rows for name in keys):
            return [], False
        return [row[name] for row in rows for name in keys], True
    if scope.get("join"):
        parent, name = scope["join"]
        path = str(arguments.get(parent, "")).rstrip("/") + "/" + str(arguments.get(name, ""))
        return [path], bool(asset_targets(path))
    fields = scope.get("fields")
    targets = [arguments.get(field, contract["parameters"].get("properties", {}).get(field, {}).get("default")) for field in fields or ()]
    targets = [target for target in targets if target is not None]
    scoped = access == "read" or world == "pie" or access == "pie" or contract["id"] == "runtime.configure_mcp_resources" or bool(fields and targets and asset_targets(targets))
    return targets, scoped


class ToolCatalog:
    """/** 注册工具的唯一精简契约目录 */"""

    def __init__(self, backend):
        """/** @param backend 官方后端 @return 实际目录 */"""
        self.backend = backend
        self.tools = {}
        for toolset, descriptors in backend.descriptors():
            for descriptor in descriptors:
                name = descriptor["name"].rsplit(".", 1)[-1]
                contract = tool_contract(toolset, name, descriptor.get("inputSchema", {"type": "object"}), descriptor.get("description", ""))
                if contract is None or contract["definition"] == "BBBExternalToolset":
                    continue
                self.add(contract)
        for contract in backend.external_contracts():
            self.add(contract)

    def add(self, contract):
        """/** @param contract 已核实契约 @return 登记完成 */"""
        if contract["id"] in self.tools:
            raise ValueError("DUPLICATE_TOOL_ID")
        item = contract if "codecs" in contract else compile_contract(contract)
        item["dependencies"] = []
        if item["definition"] in TOOL_DOMAINS and item["definition"].startswith("BBB"):
            item["dependencies"] = sorted(library + "." + function for library, functions in native_requirements(item["definition"], item["name"]).items() for function in functions)
        item.setdefault("summary", item["name"].replace("_", " "))
        if item["summary"] == item["name"] and item["id"] in SUMMARIES:
            item["summary"] = SUMMARIES[item["id"]]
        self.tools[item["id"]] = item
        self._search_cache = None

    def version(self):
        """/** @return 当前注册契约集合的确定版本 */"""
        return hashlib.sha256(json.dumps([sorted((identity, item["version"], item["summary"]) for identity, item in self.tools.items()), ROUTES, PURPOSES], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]

    def find(self, query, limit=3):
        """/** @param query 目标关键字 @param limit 结果上限 @return 候选工具 */"""
        normalized = query.casefold().strip()
        if any(word in normalized for word in ("关闭编辑器", "退出编辑器", "关编辑器", "关闭ue", "退出ue", "shutdown_host", "close editor", "quit editor")):
            result = self.describe("control_task")
            result["arguments"] = {"action": "shutdown_host"}
            result["call"] = {"tool": "control_task", "arguments": result["arguments"]}
            return [result]
        if normalized == "inspect_tasks" or any(word in normalized for word in ("干员", "会话占用", "operator", "session occupancy")):
            result = self.describe("inspect_tasks")
            result["arguments"] = {"operators": True}
            result["call"] = {"tool": "inspect_tasks", "arguments": {"operators": True}}
            return [result]
        groups = [values for word, values in ALIASES.items() if word in normalized]
        tokens = set(re.findall(r"[a-z]+", normalized))
        reading = any(word in normalized for word in ("读取", "查询", "检查", "获取", "查看", "列出", "查一下")) or bool(tokens & {"inspect", "get", "read", "list", "check", "show"})
        writing = any(word in normalized for word in ("修改", "改一下", "设置", "添加", "增加", "创建", "删除", "保存", "导入", "导出", "移动", "重建", "调整", "注释", "布局", "排版", "整理", "摆整齐", "排整齐")) or bool(tokens & {"set", "edit", "add", "create", "delete", "configure", "annotate", "layout", "write", "save", "resave", "import", "export", "move", "rebuild"})
        groups.extend((token,) for token in re.findall(r"[a-z][a-z0-9]*(?:\.[a-z_]+)*", normalized) if token not in {"the", "a", "of", "for", "to", "and"} and not re.search(r"\d", token))
        cache = getattr(self, "_search_cache", None)
        if cache is None or cache[0] is not self.tools:
            entries = []
            for contract in self.tools.values():
                identity = contract["id"].casefold()
                hint = HINTS.get(identity, "")
                words = set((identity.replace(".", " ").replace("_", " ") + " " + hint).split())
                text = (identity + " " + contract["summary"] + " " + hint).casefold()
                text += " " + " ".join(str(value) for field in contract["parameters"].get("properties", {}).values() for value in field.get("enum", []))
                entries.append((contract, identity, words, text))
            cache = (self.tools, entries)
            self._search_cache = cache
        candidates = []
        for contract, identity, words, text in cache[1]:
            score = 1000 if normalized == identity or normalized == contract["name"].casefold() else 0
            matched = 0
            for values in groups:
                weight = max((12 if value in words else 6 if value in text else 0 for value in values), default=0)
                score += weight + (3 if values[0] in words else 0)
                matched += bool(weight)
            for word in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
                if word in contract["summary"]:
                    score += 8
            if matched:
                score += 16 * matched / max(1, len(groups))
            if reading:
                score += 8 if contract["access"] == "read" else -8
            if writing and not reading:
                score += 8 if contract["access"] != "read" else -8
            if not reading and not writing:
                score += 8 if contract["access"] == "read" else 0
            if any(word in normalized for word in ("注释", "comment", "annotate", "区块")) or any("annotate" in group for group in groups):
                score += 18 if "annotate" in words else 0
            if any(word in normalized for word in ("布局", "排版", "layout", "整理")) and not any(word in normalized for word in ("注释", "comment", "annotate", "区块")):
                score += 18 if "layout" in words else 0
            if "通知" in normalized and not any(word in normalized for word in ("添加", "修改", "删除", "设置", "创建")):
                score += 16 if contract["access"] == "read" else -16
            if "验收" in normalized and "换弹" in normalized:
                score += 12 if "acceptance" in words else 0
            if {"remove", "delete"} & words and not any(value in {"remove", "delete"} for group in groups for value in group):
                score -= 12
            if score and (not groups or matched >= min(2, len(groups)) or score >= 1000):
                candidates.append((score, contract["id"], contract))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        result = [{key: item[key] for key in ("id", "summary", "access")} for score, identity, item in candidates[:min(limit, 3)]]
        if result:
            result[0] = self.describe(result[0]["id"])
        if not result and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\d[A-Za-z0-9_]*", query.strip()) and "asset.find_assets" in self.tools:
            result = [self.describe("asset.find_assets")]
            result[0]["arguments"] = {"folder_path": "/Game", "name": query.strip()}
        return result

    def describe(self, identity):
        """/** @param identity 工具 ID @return 单工具契约 */"""
        if identity in {"inspect_tasks", "control_task"}:
            from MCP.mcp_task_gateway import public_tools
            entry = next(item for item in public_tools() if item["name"] == identity)
            return {"id": identity, "summary": entry["description"], "parameters": entry["inputSchema"],
                "access": "read" if identity == "inspect_tasks" else "write", "world": "any", "completion": "observed", "direct": True}
        item = self.tools[identity]
        result = {key: item[key] for key in ("id", "summary", "parameters", "access", "world")}
        result.update({key: item[key] for key in ("scope", "completion", "version")})
        if item["dependencies"]:
            result["dependencies"] = item["dependencies"]
        result["environments"] = ["editor"]
        if item["access"] in {"read", "pie"} or item["world"] == "pie" or "dry_run" in item["parameters"].get("properties", {}):
            result["environments"].append("test")
        result.update(guidance(item, self.tools))
        return result

    def prepare(self, operations):
        """/** @param operations 完整批次 @return 已核验操作 */"""
        if not isinstance(operations, list) or not 1 <= len(operations) <= 16:
            raise ValueError("BATCH_SIZE")
        prepared = []
        issues = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict) or set(operation) != {"tool", "arguments"}:
                raise ValueError("OPERATION_SCHEMA")
            contract = self.tools.get(operation["tool"])
            if contract is None:
                raise ValueError("/operations/" + str(index) + "/tool: unknown tool")
            arguments = copy.deepcopy(operation["arguments"])
            try:
                validate_arguments(arguments, contract["parameters"], "/operations/" + str(index) + "/arguments")
            except ArgumentValidationError as error:
                issues.extend(error.issues)
                continue
            arguments = default_arguments(contract, arguments)
            access, world = resolve_access(contract, arguments)
            if contract["id"] == "asset.save_assets" and not arguments.get("asset_paths"):
                raise ValueError("SAVE_REQUIRES_EXPLICIT_ASSETS")
            targets, scoped = write_scope(contract, arguments, access, world)
            prepared.append({"contract": contract, "arguments": arguments, "access": access, "world": world, "targets": targets, "scoped": scoped})
        if issues:
            raise ArgumentValidationError(issues)
        return prepared
