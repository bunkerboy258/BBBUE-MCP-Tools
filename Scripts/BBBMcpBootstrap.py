import importlib
import os
import sys

import unreal

import BBBMcpCapabilities
from BBBMcpCapabilities import TOOLSET_ROUTES, HELPER_MODULES


def get_repository_root():
    """
    /**
     * 从加载文件确定唯一源码仓库位置 不依赖游戏项目目录
     * @return 仓库绝对路径
     */
    """
    return os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def get_toolset_name(module_name):
    """
    /**
     * 按官方命名方式读取实际工具类包名 不猜测迁移后的命名空间
     * @param module_name	工具模块名称
     * @return 精确注册名称
     */
    """
    module = sys.modules[module_name]
    definition = getattr(module, module_name)
    package_path, class_name = definition.static_class().get_path_name().rsplit(".", 1)
    parts = package_path.strip("/").split("/")
    if not parts[-1].endswith("_PY"):
        return parts[-1] + "." + class_name
    if "Python" in parts:
        parts = parts[len(parts) - parts[::-1].index("Python"):]
    parts[-1] = parts[-1][:-3]
    return ".".join(parts + [class_name])


def inspect_dependencies():
    """
    /**
     * 只读报告项目宿主和实际原生依赖 不将项目专用工具声明为完全通用
     * @return 依赖与加载位置报告
     */
    """
    repository_root = get_repository_root()
    modules = {}
    for module_name in TOOLSET_ROUTES:
        module = sys.modules.get(module_name)
        requirements = {}
        tools = {}
        for tool in BBBMcpCapabilities.source_index(module_name)["public_tools"]:
            tool_requirements = BBBMcpCapabilities.native_requirements(module_name, tool)
            tools[tool] = BBBMcpCapabilities.dependency_status(tool_requirements, unreal)
            for native_name, methods in tool_requirements.items():
                requirements.setdefault(native_name, set()).update(methods)
        status = BBBMcpCapabilities.dependency_status(requirements, unreal)
        loaded = module is not None
        registered = False
        name = None
        source_path = None
        if loaded:
            name = get_toolset_name(module_name)
            source_path = os.path.realpath(module.__file__)
            registered = bool(unreal.ToolsetRegistry.is_toolset_registered(name))
        modules[module_name] = {
            "toolset_name": name,
            "source_path": source_path,
            "registered": registered,
            **status,
            "tools": tools,
        }
        if module_name == "BBBExternalToolset" and loaded:
            modules[module_name]["actions"] = module.inspect_actions()
    return {
        "repository_root": repository_root,
        "project_root": os.path.realpath(unreal.Paths.project_dir()),
        "process_id": os.getpid(),
        "engine_version": unreal.SystemLibrary.get_engine_version(),
        "modules": modules,
        "warnings": [
            "原生依赖保留在接入项目 本仓库不包含游戏 C++ 或 UE 引擎源码",
            "仅相关原生动作受缺失依赖影响 执行前检查所属工具集诊断 不静默跳过失败",
        ],
    }


def _register_repository_toolsets():
    """
    /**
     * 从当前仓库注册工具并检查模块归属
     * @return 注册与依赖报告
     */
    """
    scripts_root = os.path.join(get_repository_root(), "Scripts")
    external_root = os.path.join(scripts_root, "MCP", "ThirdParty", "GenOrca")
    if not unreal.ToolsetRegistry.is_available():
        raise RuntimeError("官方工具注册表不可用 请启用官方 UE MCP 插件")
    runtime_loaded = "BBBMcpRuntimeToolset" in sys.modules
    for path in (external_root, scripts_root):
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    importlib.invalidate_caches()
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        names = ("BBBMcpCapabilities", "BBBAssetWritePolicy") + HELPER_MODULES + tuple(
            name[:-3] for name in os.listdir(external_root) if name.endswith("_actions.py")
        ) + TOOLSET_ROUTES
        for module_name in names:
            expected_root = external_root if module_name.endswith("_actions") else scripts_root
            expected_path = os.path.realpath(os.path.join(expected_root, module_name + ".py"))
            module = sys.modules.get(module_name)
            if module is not None and os.path.realpath(module.__file__) != expected_path:
                raise RuntimeError("MCP_MODULE_ORIGIN: " + module_name)
        for module_name in TOOLSET_ROUTES:
            expected_path = os.path.realpath(os.path.join(scripts_root, module_name + ".py"))
            if not os.path.isfile(expected_path):
                raise RuntimeError("MCP 工具源码缺失 " + expected_path)
            module = importlib.import_module(module_name)
            if os.path.realpath(module.__file__) != expected_path:
                raise RuntimeError("MCP_MODULE_ORIGIN: " + module_name)
            definition = getattr(module, module_name)
            if not unreal.ToolsetRegistry.is_toolset_class_registered(definition):
                unreal.ToolsetRegistry.register_toolset_class(definition)
            if not unreal.ToolsetRegistry.is_toolset_registered(get_toolset_name(module_name)):
                raise RuntimeError("工具类注册失败 " + module_name)
        if not runtime_loaded:
            sys.modules["BBBMcpRuntimeToolset"].configure_startup_performance()
        report = inspect_dependencies()
        for module_name, status in report["modules"].items():
            if not status["native_dependencies_ready"]:
                unreal.log_warning("[BBBMcpBootstrap]原生依赖缺失 {} {}".format(module_name, (status["missing_native_classes"] + status["missing_native_functions"])))
        unreal.log("[BBBMcpBootstrap]注册完成 {}".format(get_repository_root()))
        return report
    except Exception as error:
        unreal.log_error("[BBBMcpBootstrap]注册失败 请检查模块归属与依赖 {}".format(error))
        raise
    finally:
        sys.dont_write_bytecode = previous_bytecode


def register_mcp_toolsets():
    """
    /**
     * 注册唯一源码仓库的工具 已加载的同源模块不重复重载
     * @return 注册与依赖报告
     */
    """
    return _register_repository_toolsets()
