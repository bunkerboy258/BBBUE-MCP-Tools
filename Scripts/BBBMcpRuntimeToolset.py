import ctypes
import json
import os
import re

import unreal

from BBBMcpCapabilities import mcp_tool, usage_routes
from toolset_registry.registration import Registration


_PROFILES = {
    "Speed": {"max_fps": 120, "priority": 0x20},
    "Balanced": {"max_fps": 60, "priority": 0x20},
    "Economy": {"max_fps": 30, "priority": 0x4000},
    "GamingBackground": {"max_fps": 15, "priority": 0x4000},
}
_PRIORITY_NAMES = {0x20: "Normal", 0x4000: "BelowNormal"}
_active_profile = "Unconfigured"
_configured_max_fps = None


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
    def inspect_mcp_performance() -> str:
        """
        /**
         * 只读检查当前宿主配置与低速风险
         * @return 性能状态 JSON
         */
        """
        return json.dumps(_snapshot(), ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def configure_mcp_performance(profile: str = "Speed", max_fps: int = -1) -> str:
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
    def get_mcp_usage_guide() -> str:
        """
        /**
         * 返回 AI 最小调用指南 包含实际可选档位与工具选型入口
         * @return 使用指南 JSON 完整参数以目标工具集的描述为准
         */
        """
        import BBBMcpBootstrap

        toolset_name = BBBMcpBootstrap.get_toolset_name
        return json.dumps(
            {
                "document_path": os.path.join(BBBMcpBootstrap.get_repository_root(), "Docs", "UnrealMcpCanonical.md"),
                "dependency_document_path": os.path.join(BBBMcpBootstrap.get_repository_root(), "Docs", "ProjectDependencies.md"),
                "project_root": os.path.realpath(unreal.Paths.project_dir()),
                "dependency_tool": "inspect_mcp_dependencies",
                "profiles": _profile_options(),
                "performance_toolset": toolset_name("BBBMcpRuntimeToolset"),
                "gaming_arguments": {"profile": "GamingBackground", "max_fps": -1},
                "speed_arguments": {"profile": "Speed", "max_fps": -1},
                "discovery": ["list_toolsets", "describe_toolset", "call_tool"],
                **usage_routes(toolset_name, unreal.ToolsetRegistry),
                "result_contract": {"failure_fields": ["success=false", "error 非空"], "batch_atomic": False, "automatic_retry": False},
                "rules": [
                    "先核对项目与宿主 只描述目标领域的工具集 不盲读全部描述",
                    "仓库目录不再代表项目目录 先核对 project_root 再检查 inspect_mcp_dependencies 缺失原生依赖的动作不得继续写入",
                    "同一宿主会话复用已确认参数 工具变化后重新发现 不缓存资产状态",
                    "现有工具无法解决时先核对与组合 确认能力缺口后优先拓展旧工具或新增最小通用工具 注册 文档与实际调用验证必须同步完成 不用临时 py 脚本绕过",
                    "工具扩展必须遵循 Law 与已批准范围 权限 文件锁和规则冲突不是可绕过的能力缺口 超出计划先说明命名与影响并请求批准",
                    "ProgrammaticToolset 使用前必须读取 get_execution_environment 和目标工具结构",
                    "content 文本先解析 JSON 字符串 returnValue 按输出结构再解析",
                    "协议 error 工具 isError 项目结果 success 为 false 或根 error 非空均需检查并报告",
                    "写入资产先独占签出 写入失败不自动重试 批量调用不是回滚事务",
                    "后台游戏档不自动提速 重资源操作需告知用户 并协调其他会话",
                    "切换档位后回读 inspect_mcp_performance 不把帧率上限当作实测帧率",
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @mcp_tool
    @staticmethod
    def inspect_mcp_dependencies() -> str:
        """
        /**
         * 只读报告独立仓库位置 接入项目和工具原生依赖
         * @return 依赖与实际加载位置 JSON
         */
        """
        import BBBMcpBootstrap

        return json.dumps(BBBMcpBootstrap.inspect_dependencies(), ensure_ascii=False)


def configure_startup_performance():
    """
    /**
     * 从启动参数读取档位 默认速度优先 配置失败明确报警
     * @return 无返回值
     */
    """
    command_line = unreal.SystemLibrary.get_command_line()
    profile_match = re.search(r"(?i)(?:^|\s)-BBBMcpPerformanceProfile=([^\s]+)", command_line)
    fps_match = re.search(r"(?i)(?:^|\s)-BBBMcpMaxFPS=([^\s]+)", command_line)
    profile = "Speed"
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
