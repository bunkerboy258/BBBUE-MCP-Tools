# BBBUE MCP Tools

UE5.8 编辑器工具与任务调度。固定入口默认 `http://127.0.0.1:8000/mcp`。

## 调用

| 入口 | 用途 |
| --- | --- |
| `manage_operator` | 登记任务、更新等级、结束会话 |
| `find_tools` | 搜索目标；首项提供参数 |
| `describe_tool` | 查询单项契约 |
| `submit_batch` | 提交一至十六项操作 |
| `inspect_tasks` | 查询占用、进度与结果 |
| `control_task` | 收尾、恢复与宿主管理 |

已知工具 ID 直接提交。新目标先搜索。短调用读取 `results` 与 `proof`；长调用按返回的 `next` 继续。`needs` 提供待修正字段与类型。`detail=true` 展开完整证据，`operators=true` 展开干员池。

```python
from MCP.mcp_call import McpSession

with McpSession(task="核对资产") as session:
    result = session.submit_batch([
        {"tool": "editor.inspect_dirty_packages", "arguments": {}}
    ])
    if result["status"] in {"queued", "running"}:
        result = session.wait_batch(result["batch"])
    print(result)
```

聊天通过独立 `conversation_id` 恢复归属。Codex 在提供 `task` 时采用 `CODEX_THREAD_ID`。登记任务为单行二十字以内，默认二级；零级最高，同级按提交顺序调度。会话结束使用 `manage_operator(action="finish")`。

## 执行

编辑批次自动校验、编译、保存、回读并释放资产。同一资产保持操作顺序，独立资产继续执行。故障范围由网关后台恢复；结果记录与资产占用独立维护。

测试批次使用 `environment="test"` 和 `test_options={"map":"/Game/Maps/Acceptance"}`。测试宿主直接读取原项目已保存资产，默认容量两组。后续批次携带返回的 `test_host`；完成后用 `control_task(action="close", batch=...)` 回收所属测试。

正常关闭共享编辑器使用 `control_task(action="shutdown_host")`。零级支持 `pause_operator`、`resume_operator`、`cancel_blocker` 和 `terminate_host`；暂停默认六十秒，上限三百秒。

## 启动与更新

环境为 Windows、UE5.8、项目编辑器模块、Python 与 `requests`。项目 Python 搜索路径指向本仓库 `Scripts`，由 `init_unreal.py` 接入独立常驻服务。

```powershell
.\Scripts\MCP\Start-BBBMcpService.ps1 -ProjectPath '<uproject绝对路径>' -InstallAtLogon

$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 `
    -ProjectPath '<uproject绝对路径>' `
    -EnginePath '<UE5.8根目录>' `
    -PerformanceProfile Balanced
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认档位为 60 FPS、Normal。手动打开项目共用 `BBBMcpEditorStartup.start_editor_mcp()` 接入链。

源码版本变化返回 `TOOLSET_UPDATE_REQUIRED`。`restart` 指出待更新的 `service` 或 `host`；先交接已接收批次，再重启对应进程，回读 `source.current=true` 后继续。源码巡检间隔一秒，注册前后执行完整核验。

## 参考

- [公开契约](Docs/UnrealMcpCanonical.md)
- [调度与恢复](Docs/BBBMcpTaskProtection.md)
- [项目依赖](Docs/ProjectDependencies.md)
- [第三方动作](Docs/BBBExternalMcp.md)

## 本轮更新

2026-11-03：全目录与缓存统一校验范围声明；参考回放补齐会话范围。声明错误在发布前独立记录，参数范围错误返回补参字段；当前地图单独核验已保存包，打开地图合并当前与目标范围并支持 Entry 和临时空地图。源码及原生目录静态覆盖、专项契约检查通过。

2026-11-03：复用目录版本、精确 ID 直达、源码指纹增量巡检、客户端身份轻量加载；版本失配返回明确重启范围，状态版本包含源码变化。地图查询与打开分别统一为 `scene.get_current_level` 和 `scene.load_level`；补齐写入范围并移除编辑器目录中的技能管理与文件写入入口。静态语法、范围覆盖与引用检查完成。

2026-11-04 普通关卡构建: 新增保留源材质的原生 HLOD 单簇构建 光照有效性检查 纹理流送组件构建和反射捕获入口 模块编译通过 DeadCity 已保存 17 簇 纹理流送未构建组件为 0 远景截图已核对 最终 Production 光照进行中 详见 Docs/BBBLevelBuildMCP.md
