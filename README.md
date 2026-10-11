# BBBUE MCP Tools

UE5.8 编辑器工具。多个 AI 客户端共用原项目的资产编辑宿主，测试批次按需使用独立宿主。通过五个接口发现工具、提交批次和读取结果。

## 使用顺序

1. `inspect_tasks` 查看宿主、占用者和可执行工作。
2. `find_tools` 搜索当前目标，最多返回八项。
3. `describe_tool` 读取选中工具的参数。
4. `submit_batch` 提交有序操作，立即取得 `batch`。
5. `inspect_tasks(batch=..., detail=true)` 读取结果；完成后 `control_task(action="close", batch=...)`。

工具 ID 使用 `领域.函数`，例如 `blueprint.inspect_blueprint_graph`。参数、权限和世界约束以实际描述为准。

## 启动

需要 Windows、UE5.8、项目编辑器模块、Python 和 `requests`。项目的 `Content/Python/init_unreal.py` 加载 `Scripts/BBBMcpBootstrap.py`。

```powershell
$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 `
    -ProjectPath '<项目的 uproject 绝对路径>' `
    -EnginePath '<UE5.8 根目录>' `
    -Port <公开端口>
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

启动器核对原项目宿主与网关，已有匹配宿主时复用。默认隐藏 NullRHI；截图使用 `-EnableRendering`，音频使用 `-EnableAudio`，混音验收可同时使用 `-MuteAudioOutput`。

## Python 客户端

在 Python 模块搜索路径中加入本仓库 `Scripts`。

```python
from MCP.mcp_call import McpSession

with McpSession() as session:
    state = session.inspect_tasks()
    candidates = session.find_tools("inspect_dirty_packages")
    tool = candidates[0]["id"]
    session.describe_tool(tool)
    batch = session.submit_batch(
        [{"tool": tool, "arguments": {}}],
        label="读取待保存包",
    )["batch"]
    result = session.wait_batch(batch)
    print(result)
    session.control_task("close", batch)
```

`BBB_MCP_URL` 来自启动器。长连接自动维护归属和心跳。重连使用原 `client_key`，由连接层私有保管。

命令行跨进程操作使用当前客户端专属 `--client-state` 文件。文件放在本任务临时目录，连接与批次完成后按项目清理规则处理。

```powershell
python -B .\Scripts\MCP\mcp_call.py inspect_tasks '{}'
```

## 调度

- 同步 UE 调用顺序执行；批次最多十六项。
- 异步活动等待期间让出执行槽，只读批次可继续。
- PIE 归发起客户端维护；其他客户端可查询并排队，前一轮结束后启动下一轮。
- `environment="test"` 在原项目启动受限测试宿主；默认最多两组测试并行，编辑宿主继续工作。
- `test_options` 指定已保存地图，可选择渲染、音频、玩家数量与网络模式。
- 测试结果记录地图依赖、显式输入和代码配置的文件版本；输入变化时标记 `TEST_INPUT_CHANGED`。
- 首次测试返回 `test_host`。PIE 与采样活动期间，后续批次使用该身份继续操作；测试流程结束后回收宿主。交付输出后关闭首次批次，清理对应任务目录。
- 明确目标包的编辑按范围核对；场景与范围待定操作核对完整基线。
- 已完成范围、失败证据和待保存包进入 `review`；所属客户端回读、处理后确认。
- 业务状态变化更新 `revision`，客户端可按版本等待。
- 全部批次、PIE、活动和待保存内容完成后，通过 `control_task(action="shutdown_host")` 退出宿主。

```python
batch = session.submit_batch(
    operations,
    label="玩法测试",
    environment="test",
    test_options={"map": "/Game/_Project/Maps/TestMap"},
)["batch"]
result = session.wait_batch(batch)
```

## 验证与源码

- [调用契约](Docs/UnrealMcpCanonical.md)
- [调度与恢复](Docs/BBBMcpTaskProtection.md)
- [项目依赖](Docs/ProjectDependencies.md)
- [第三方来源](Docs/BBBExternalMcp.md)

```powershell
python -B -m unittest discover -s Tests -p 'test_mcp*.py'
powershell -NoProfile -File Tests/Test-Startup.ps1
python -B Tests/verify_live_mcp.py --url $hostInfo.Endpoint --project-root '<项目根目录>'
python -B Tests/verify_mcp_task_protection.py --url $hostInfo.Endpoint --project-root '<项目根目录>' --run-pie
python -B Tests/verify_mcp_parallel_tests.py --url $hostInfo.Endpoint --project-root '<项目根目录>'
```

真实 PIE 验收使用专用空闲窗口。领域参数的复杂 JSON 结构保存在对应专用文档，按目标读取。

## 更新日志

### 2026-10-11

统一五个公开接口、稳定工具 ID 和服务端批次调度。连接层维护归属，异步活动按实际完成证据续跑；占用查询按需展开，工具契约按目标加载。工具注册统一由 Bootstrap 完成。

宿主 Law 改为共享资产编辑与按需测试。测试直接读取原项目，采用 Windows 受限令牌、独立输出、端口和资产版本核验；支持两个测试批次并行，交付关闭后清理所属输出。

### 领域工具

- [通用编辑器](Docs/BBBGenericEditorMCP.md)：资产读取、动画通知、实例缩略图和编辑操作。
- [命中反馈](Docs/BBBHitReactionMCP.md)：玩法采样与实际角色表现检查。

本次同步保留领域更新：相机后坐力回正延迟、动画通知实例索引、运行时材质缩略图。
