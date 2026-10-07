import ast
from functools import lru_cache, wraps
import inspect
from pathlib import Path

from MCP.mcp_result import require_business_success


TOOLSET_ROUTES = {
    "BBBTraversalToolset": "攀爬资产与运行验收",
    "BBBAnimationMigrationToolset": "动画项目流程",
    "BBBExternalToolset": "第三方领域动作",
    "BBBGenericEditorToolset": "通用项目资产校验",
    "BBBLevelEditingToolset": "项目关卡操作",
    "BBBBlueprintGraphToolset": "蓝图排版与项目图表",
    "BBBRigidPartToolset": "刚性部件流程",
    "BBBControlRigAuthoringToolset": "ControlRig 项目流程",
    "BBBMcpRuntimeToolset": "MCP 宿主诊断",
    "BBBAssetMaintenanceToolset": "资产维护与修复",
    "BBBAnimationPreviewToolset": "动画与群体预览",
    "BBBAnimationGraphToolset": "动画构图与校验",
    "BBBHitReactionToolset": "骨骼物理受击配置与校验",
}
HELPER_MODULES = (
    "BBBBlueprintLayout", "BBBBlueprintAnnotations", "BBBAnimationMotionTools",
    "BBBAnimationTrajectoryTools", "BBBArmTwistTools", "BBBWeaponHandlingTools",
)
OFFICIAL_ROUTES = {
    "对象属性": "editor_toolset.toolsets.object.ObjectTools",
    "资产查询": "editor_toolset.toolsets.asset.AssetTools",
    "蓝图基础编辑": "editor_toolset.toolsets.blueprint.BlueprintTools",
    "ControlRig 基础编辑": "animation_toolset.toolsets.controlrig.ControlRigTools",
    "Sequencer 基础编辑": "animation_toolset.toolsets.sequencer.SequencerTools",
    "批量工具编排": "editor_toolset.toolsets.programmatic.ProgrammaticToolset",
}
SCRIPTS_ROOT = Path(__file__).resolve().parent


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


def _walk_native_requirements(module_name, function_name, visited):
    """
    /**
     * 追踪静态原生引用和本仓库辅助调用 动态业务条件仍由工具预检
     * @param module_name	源码模块
     * @param function_name	工具或辅助函数
     * @param visited	当前递归路径
     * @return 原生类到所需函数名称集合
     */
    """
    key = (module_name, function_name)
    if key in visited:
        return {}
    visited.add(key)
    index = source_index(module_name)
    function = index["functions"].get(function_name)
    if function is None:
        return {}
    requirements = {}
    aliases = {}
    call_targets = {id(node.func) for node in ast.walk(function) if isinstance(node, ast.Call)}
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "unreal":
            if node.attr.startswith("BBB") or node.attr == "MCPythonHelper":
                aliases[ast.unparse(node)] = node.attr
                requirements.setdefault(node.attr, set())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and ast.unparse(node.args[0]) == "unreal" and isinstance(node.args[1], ast.Constant):
                name = node.args[1].value
                if isinstance(name, str) and (name.startswith("BBB") or name == "MCPythonHelper"):
                    aliases[ast.unparse(node)] = name
                    requirements.setdefault(name, set())
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and ast.unparse(node.value) in aliases:
            for target in node.targets:
                aliases[ast.unparse(target)] = aliases[ast.unparse(node.value)]
    for node in ast.walk(function):
        if isinstance(node, ast.Attribute) and ast.unparse(node.value) in aliases:
            owner = aliases[ast.unparse(node.value)]
            if id(node) in call_targets or owner.endswith("Library") or owner == "MCPythonHelper":
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
        if child:
            for name, methods in _walk_native_requirements(*child, visited).items():
                requirements.setdefault(name, set()).update(methods)
    return requirements


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


def usage_routes(get_toolset_name, registry):
    """
    /**
     * @param get_toolset_name	实际项目工具集名称解析函数
     * @param registry	当前官方注册表
     * @return 可用路由与未注册路由
     */
    """
    routes = dict(OFFICIAL_ROUTES)
    routes.update({label: get_toolset_name(module) for module, label in TOOLSET_ROUTES.items()})
    unavailable = {label: name for label, name in routes.items() if not registry.is_toolset_registered(name)}
    return {"routes": {label: name for label, name in routes.items() if label not in unavailable}, "unavailable_routes": unavailable}


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
        status = dependency_status(requirements, unreal)
        if not status["native_dependencies_ready"]:
            raise RuntimeError("原生依赖不可用: " + str(status))
        result = function(*args, **kwargs)
        require_business_success(result)
        return result

    invoke.__signature__ = inspect.signature(function)
    return toolset_registry.tool_call(staticmethod(invoke))
