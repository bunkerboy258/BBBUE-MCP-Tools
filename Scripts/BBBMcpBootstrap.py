import importlib
import os
import sys

import unreal


_TOOLSET_MODULES = (
    "BBBAnimationMigrationToolset",
    "BBBExternalToolset",
    "BBBGenericEditorToolset",
    "BBBLevelEditingToolset",
    "BBBBlueprintGraphToolset",
    "BBBRigidPartToolset",
    "BBBControlRigAuthoringToolset",
    "BBBMcpRuntimeToolset",
    "BBBAssetMaintenanceToolset",
    "BBBAnimationPreviewToolset",
    "BBBAnimationGraphToolset",
)
_HELPER_MODULES = (
    "BBBAnimationMotionTools",
    "BBBAnimationTrajectoryTools",
    "BBBArmTwistTools",
)
_NATIVE_DEPENDENCIES = {
    "BBBAnimationMigrationToolset": ("BBBBlueprintEditorLibrary", "BBBPIEInputEditorLibrary"),
    "BBBGenericEditorToolset": ("BBBBlueprintEditorLibrary", "BBBPIEWindowEditorLibrary", "BBBAssetThumbnailEditorLibrary", "BBBNiagaraEditorLibrary"),
    "BBBLevelEditingToolset": ("BBBBlueprintEditorLibrary",),
    "BBBBlueprintGraphToolset": ("BBBBlueprintEditorLibrary",),
    "BBBControlRigAuthoringToolset": ("BBBBlueprintEditorLibrary",),
    "BBBAssetMaintenanceToolset": ("BBBAssetRepairEditorLibrary",),
    "BBBAnimationPreviewToolset": ("BBBBlueprintEditorLibrary", "BBBAnimationGraphEditorLibrary"),
    "BBBAnimationGraphToolset": ("BBBAnimationGraphEditorLibrary",),
}


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
    for module_name in _TOOLSET_MODULES:
        module = sys.modules.get(module_name)
        required = _NATIVE_DEPENDENCIES.get(module_name, ())
        missing = [name for name in required if getattr(unreal, name, None) is None]
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
            "required_native_classes": list(required),
            "missing_native_classes": missing,
            "native_dependencies_ready": not missing,
        }
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


def _load_toolsets(force_reload):
    """
    /**
     * 仅替换本仓库工具注册 保留官方工具与实际性能设置
     * @param force_reload	是否重新加载已经来自本仓库的模块
     * @return 注册结果
     */
    """
    scripts_root = os.path.join(get_repository_root(), "Scripts")
    external_root = os.path.join(scripts_root, "MCP", "ThirdParty", "GenOrca")
    if not unreal.ToolsetRegistry.is_available():
        raise RuntimeError("官方工具注册表不可用 请启用官方 UE MCP 插件")
    previous_runtime = sys.modules.get("BBBMcpRuntimeToolset")
    previous_performance = None
    if previous_runtime is not None:
        previous_performance = previous_runtime._snapshot()
    for path in (external_root, scripts_root):
        while path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)
    importlib.invalidate_caches()
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        auxiliary_names = _HELPER_MODULES + tuple(
            name[:-3] for name in os.listdir(external_root) if name.endswith("_actions.py")
        )
        for module_name in auxiliary_names:
            module = sys.modules.get(module_name)
            if module is not None:
                expected_root = scripts_root
                if module_name.endswith("_actions"):
                    expected_root = external_root
                expected_path = os.path.realpath(os.path.join(expected_root, module_name + ".py"))
                if force_reload or os.path.realpath(module.__file__) != expected_path:
                    importlib.reload(module)
        module_names = list(_TOOLSET_MODULES)
        registered_classes = {}
        for definition in unreal.ObjectIterator(unreal.Class):
            module_name = definition.get_name().split("_0x", 1)[0]
            if module_name in module_names and unreal.ToolsetRegistry.is_toolset_class_registered(definition):
                registered_classes.setdefault(module_name, []).append(definition)
        for module_name in module_names:
            expected_path = os.path.realpath(os.path.join(scripts_root, module_name + ".py"))
            if not os.path.isfile(expected_path):
                raise RuntimeError("MCP 工具源码缺失 " + expected_path)
            module = sys.modules.get(module_name)
            needs_reload = force_reload
            if module is not None:
                needs_reload = needs_reload or os.path.realpath(module.__file__) != expected_path
                if needs_reload:
                    for definition in registered_classes.get(module_name, ()):
                        unreal.ToolsetRegistry.unregister_toolset_class(definition)
                    importlib.reload(module)
            if module is None:
                module = importlib.import_module(module_name)
            if os.path.realpath(module.__file__) != expected_path:
                raise RuntimeError("工具加载到错误位置 " + module_name)
            definition = getattr(module, module_name)
            if not unreal.ToolsetRegistry.is_toolset_class_registered(definition):
                unreal.ToolsetRegistry.register_toolset_class(definition)
            if not unreal.ToolsetRegistry.is_toolset_registered(get_toolset_name(module_name)):
                raise RuntimeError("工具类注册失败 " + module_name)
        runtime = sys.modules["BBBMcpRuntimeToolset"]
        if previous_performance is not None:
            runtime._active_profile = previous_performance["profile"]
            runtime._configured_max_fps = previous_performance["configured_max_fps"]
        if previous_performance is None:
            runtime.configure_startup_performance()
        report = inspect_dependencies()
        for module_name, status in report["modules"].items():
            if not status["native_dependencies_ready"]:
                unreal.log_warning("[BBBMcpBootstrap]原生依赖缺失 {} {}".format(module_name, status["missing_native_classes"]))
        unreal.log("[BBBMcpBootstrap]注册完成 {}".format(get_repository_root()))
        return report
    except Exception as error:
        unreal.log_error("[BBBMcpBootstrap]注册或更新失败 部分注册可能已完成 请重新发现并检查 {}".format(error))
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
    return _load_toolsets(False)


def reload_mcp_toolsets():
    """
    /**
     * 使用官方注册生命周期重载本仓库工具 不重启宿主
     * @return 注册与依赖报告
     */
    """
    return _load_toolsets(True)


if __name__ == "__bbb_editor_script__":
    import BBBMcpBootstrap

    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        importlib.reload(BBBMcpBootstrap)
        BBBMcpBootstrap.reload_mcp_toolsets()
    finally:
        sys.dont_write_bytecode = previous_bytecode
