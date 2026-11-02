import ctypes
import json
import os
import re

import unreal

from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


_PROFILES = {
    "HighThroughput": {"max_fps": 120, "priority": 0x20},
    "Balanced": {"max_fps": 60, "priority": 0x20},
    "Economy": {"max_fps": 30, "priority": 0x4000},
    "GamingBackground": {"max_fps": 15, "priority": 0x4000},
}
_PRIORITY_NAMES = {0x20: "Normal", 0x4000: "BelowNormal"}
_active_profile = "Unconfigured"
_configured_max_fps = None
_scene_gpu_profile_settings = None


def _profile_options():
    """
    /**
     * 从唯一档位定义生成工具发现信息 避免说明与配置分离
     * @return 可用档位和默认配置
     */
    """
    return {
        name: {
            "max_fps": options["max_fps"],
            "priority": _PRIORITY_NAMES[options["priority"]],
        }
        for name, options in _PROFILES.items()
    }


def _performance_settings():
    """
    /**
     * 获取编辑器性能设置的内存默认对象 不保存用户配置
     * @return 性能设置对象
     */
    """
    settings_class = unreal.load_class(None, "/Script/UnrealEd.EditorPerformanceSettings")
    if settings_class is None:
        raise RuntimeError("编辑器性能设置类不可用")
    return unreal.get_default_object(settings_class)


def _process_api():
    """
    /**
     * 仅访问当前 Windows 宿主的进程优先级 不操作其他进程
     * @return 当前进程句柄与 Windows API
     */
    """
    if os.name != "nt":
        raise RuntimeError("当前项目的 MCP 性能档位仅支持 Windows 宿主")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
    kernel.GetPriorityClass.restype = ctypes.c_ulong
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.SetPriorityClass.restype = ctypes.c_int
    return kernel.GetCurrentProcess(), kernel


def _snapshot():
    """
    /**
     * 返回当前宿主的实际配置 不将配置帧率冒充实测帧率
     * @return 性能状态对象
     */
    """
    handle, kernel = _process_api()
    priority = kernel.GetPriorityClass(handle)
    if not priority:
        raise ctypes.WinError(ctypes.get_last_error())

    settings = _performance_settings()
    max_fps = unreal.SystemLibrary.get_console_variable_float_value("t.MaxFPS")
    throttle = bool(settings.get_editor_property("bThrottleCPUWhenNotForeground"))
    idle = unreal.SystemLibrary.get_console_variable_int_value("t.IdleWhenNotForeground")
    command_line = unreal.SystemLibrary.get_command_line()
    warnings = []
    if max_fps <= 0:
        warnings.append("帧率未限制 CPU 与 GPU 消耗可能明显增加")
    if throttle:
        warnings.append("后台 CPU 节流开启 MCP 可能降到每秒三次调度")
    if idle:
        warnings.append("失去前台时引擎空闲策略开启 MCP 可能暂停处理")
    if 0 < max_fps < 30:
        warnings.append("帧率上限低于三十 MCP 串行调用延迟会累积")
    if not re.search(r"(?i)(?:^|\s)-(?:NullRHI|Unattended)(?:\s|$)", command_line):
        warnings.append("当前是交互式宿主 全部窗口隐藏时仍可能触发编辑器节流")

    matches_configured_settings = False
    if _active_profile in _PROFILES and _configured_max_fps is not None:
        matches_configured_settings = (
            abs(max_fps - _configured_max_fps) < 0.01
            and priority == _PROFILES[_active_profile]["priority"]
            and not throttle
            and not idle
        )
        if not matches_configured_settings:
            warnings.append("实际设置已偏离最近应用档位 请协调其他会话后重新配置")

    if _active_profile == "GamingBackground":
        warnings.append("后台游戏档只约束持续调度 编译 导入 烘焙与截图仍可能产生资源峰值")
        if not re.search(r"(?i)(?:^|\s)-NullRHI(?:\s|$)", command_line):
            warnings.append("当前宿主启用渲染 后台游戏档不保证 GPU 低负载或显存下降")

    return {
        "process_id": os.getpid(),
        "profile": _active_profile,
        "available_profiles": _profile_options(),
        "configured_max_fps": _configured_max_fps,
        "matches_configured_settings": matches_configured_settings,
        "max_fps": max_fps,
        "priority": _PRIORITY_NAMES.get(priority, "Other"),
        "priority_code": priority,
        "background_cpu_throttle": throttle,
        "idle_when_not_foreground": idle,
        "null_rhi": bool(re.search(r"(?i)(?:^|\s)-NullRHI(?:\s|$)", command_line)),
        "unattended": bool(re.search(r"(?i)(?:^|\s)-Unattended(?:\s|$)", command_line)),
        "warnings": warnings,
    }


def _configure(profile, max_fps):
    """
    /**
     * 应用运行时档位并检查实际结果 失败恢复调用前配置
     * @param profile\t性能档位名称
     * @param max_fps\t帧率上限 负一使用档位默认 零不限制
     * @return 应用后的实际配置
     */
    """
    global _active_profile
    global _configured_max_fps
    if profile not in _PROFILES:
        raise ValueError("性能档位只能为 {}".format(" ".join(_PROFILES)))
    if not isinstance(max_fps, int) or isinstance(max_fps, bool) or max_fps < -1 or max_fps > 240:
        raise ValueError("帧率上限只能为负一或零至二百四十的整数")

    requested_fps = _PROFILES[profile]["max_fps"]
    if max_fps >= 0:
        requested_fps = max_fps

    before = _snapshot()
    settings = _performance_settings()
    handle, kernel = _process_api()
    try:
        if not kernel.SetPriorityClass(handle, _PROFILES[profile]["priority"]):
            raise ctypes.WinError(ctypes.get_last_error())
        settings.set_editor_property("bThrottleCPUWhenNotForeground", False)
        unreal.SystemLibrary.execute_console_command(None, "t.IdleWhenNotForeground 0")
        unreal.SystemLibrary.execute_console_command(None, "t.MaxFPS {}".format(requested_fps))
        after = _snapshot()
        if after["background_cpu_throttle"] or after["idle_when_not_foreground"]:
            raise RuntimeError("后台节流配置未生效")
        if abs(after["max_fps"] - requested_fps) > 0.01 or after["priority_code"] != _PROFILES[profile]["priority"]:
            raise RuntimeError("帧率或进程优先级配置未生效")
    except Exception:
        settings.set_editor_property("bThrottleCPUWhenNotForeground", before["background_cpu_throttle"])
        unreal.SystemLibrary.execute_console_command(None, "t.IdleWhenNotForeground {}".format(before["idle_when_not_foreground"]))
        unreal.SystemLibrary.execute_console_command(None, "t.MaxFPS {}".format(before["max_fps"]))
        restored_priority = kernel.SetPriorityClass(handle, before["priority_code"])
        unreal.log_error("[BBBMcpPerformance]配置失败 已恢复控制台与后台设置 优先级恢复结果 {}".format(bool(restored_priority)))
        raise

    _active_profile = profile
    _configured_max_fps = requested_fps
    after = _snapshot()
    unreal.log("[BBBMcpPerformance]{}".format(json.dumps(after, ensure_ascii=False)))
    for warning in after["warnings"]:
        unreal.log_warning("[BBBMcpPerformance]{}".format(warning))
    return after


@unreal.uclass()
class BBBMcpRuntimeToolset(unreal.ToolsetDefinition):
    """
    /**
     * 提供 MCP 宿主运行时性能档位与只读诊断 不修改资产或持久配置
     */
    """

    @mcp_tool
    @staticmethod
    def inspect_mcp_resources() -> str:
        """
        /**
         * 只读检查当前宿主配置与低速风险
         * @return 性能状态 JSON
         */
        """
        return json.dumps(_snapshot(), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def profile_scene_gpu(action: str = "capture") -> str:
        """
        /**
         * 请求原生单帧 GPU 分析 结果由引擎日志交付 不改变画质或保存截图
         * @param action	capture 请求分析 restore 恢复分析器显示设置
         * @return 请求帧号与日志路径 请求成功不代表分析已经完成
         */
        """
        global _scene_gpu_profile_settings
        if action not in ("capture", "restore"):
            raise ValueError("GPU 分析只接受 capture 或 restore")
        if action == "restore":
            if _scene_gpu_profile_settings is None:
                return json.dumps({"status": "idle"})
            for name, value in _scene_gpu_profile_settings.items():
                unreal.SystemLibrary.execute_console_command(None, "{} {}".format(name, value))
            restored = {
                name: unreal.SystemLibrary.get_console_variable_int_value(name)
                for name in _scene_gpu_profile_settings
            }
            if restored != _scene_gpu_profile_settings:
                unreal.log_error("[BBBMcpGpuProfile]分析器设置恢复回读不一致")
                raise RuntimeError("GPU 分析器设置未完整恢复")
            _scene_gpu_profile_settings = None
            unreal.log("[BBBMcpGpuProfile]已恢复分析器显示设置")
            return json.dumps({"status": "restored", "settings": restored})
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
        if world is None:
            raise RuntimeError("GPU 分析要求当前 PIE 世界")
        if _snapshot()["null_rhi"]:
            raise RuntimeError("GPU 分析要求启用渲染")
        if _scene_gpu_profile_settings is not None:
            raise RuntimeError("上次 GPU 分析尚未恢复 请先执行 restore")
        values = {"r.ProfileGPU.ShowUI": 0, "r.ShowMaterialDrawEvents": 1, "r.EmitMeshDrawEvents": 1}
        _scene_gpu_profile_settings = {
            name: unreal.SystemLibrary.get_console_variable_int_value(name) for name in values
        }
        for name, value in values.items():
            unreal.SystemLibrary.execute_console_command(world, "{} {}".format(name, value))
        unreal.SystemLibrary.execute_console_command(world, "ProfileGPU")
        frame = int(unreal.SystemLibrary.get_frame_count())
        unreal.log("[BBBMcpGpuProfile]已请求单帧 GPU 分析 Frame={}".format(frame))
        pipeline = {
            name: unreal.SystemLibrary.get_console_variable_int_value(name)
            for name in ("r.EarlyZPass", "r.EarlyZPassOnlyMaterialMasking", "r.StencilForLODDither")
        }
        return json.dumps({"status": "requested", "frame": frame, "pipeline_settings": pipeline,
                           "log_directory": unreal.Paths.project_log_dir(),
                           "next_action": "检查引擎日志中的 GPU 分析结果后执行 restore"}, ensure_ascii=False)


    @mcp_tool
    @staticmethod
    def configure_mcp_resources(profile: str = "Balanced", max_fps: int = -1) -> str:
        """
        /**
         * 选择当前宿主的运行时性能档位 不保存用户配置
         * @param profile\tSpeed Balanced Economy
         * @param max_fps\t帧率上限 负一使用默认 零不限制
         * @return 生效配置 JSON
         */
        """
        return json.dumps(_configure(profile, max_fps), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_mcp_dependencies(tool: str) -> str:
        """
        /**
         * 只读报告独立仓库位置 接入项目和工具原生依赖
         * @return 依赖与实际加载位置 JSON
         */
        """
        from BBBMcpCapabilities import TOOL_DOMAINS, source_index, native_requirements, dependency_status
        domain, function = tool.split(".", 1)
        modules = [name for name, label in TOOL_DOMAINS.items()
                   if label == domain and name.startswith("BBB")
                   and function in source_index(name)["public_tools"]]
        if len(modules) != 1:
            raise ValueError("TOOL_UNKNOWN")
        status = dependency_status(native_requirements(modules[0], function), unreal)
        return json.dumps({"tool": tool, "process_id": os.getpid(), "project_root": os.path.realpath(unreal.Paths.project_dir()), **status}, ensure_ascii=False)


def configure_startup_resources():
    """
    /**
     * 从启动参数读取档位 默认速度优先 配置失败明确报警
     * @return 无返回值
     */
    """
    command_line = unreal.SystemLibrary.get_command_line()
    profile_match = re.search(r"(?i)(?:^|\s)-BBBMcpPerformanceProfile=([^\s]+)", command_line)
    fps_match = re.search(r"(?i)(?:^|\s)-BBBMcpMaxFPS=([^\s]+)", command_line)
    profile = "Balanced"
    max_fps = -1
    try:
        if profile_match:
            profile = profile_match.group(1)
        if fps_match:
            max_fps = int(fps_match.group(1))
        _configure(profile, max_fps)
    except Exception as error:
        unreal.log_error("[BBBMcpPerformance]启动性能配置失败 {}".format(error))
        raise


_registration = Registration([BBBMcpRuntimeToolset])
