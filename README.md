# BBBUE MCP Tools

UE5.8 编辑器操作与任务调度。AI 使用五个入口；工具契约按当前目标读取。

## 调用

- 已知工具：直接 `submit_batch`。
- 新目标：`find_tools(query)` 返回最多三项，首项附带参数、默认值和完成条件。
- 参数细节：`describe_tool(tool)`。
- 短调用：提交响应包含结果和证据。
- 长调用：按响应的 `batch`、`revision`、`next` 继续。

```python
from MCP.mcp_call import McpSession

with McpSession() as session:
    result = session.submit_batch([
        {"tool": "editor.inspect_dirty_packages", "arguments": {}}
    ])
    if result["status"] in {"queued", "running"}:
        result = session.wait_batch(result["batch"])
    print(result)
```

`BBB_MCP_URL` 由启动器返回。连接层维护客户端归属、心跳和请求重放。

## 编辑与测试

编辑批次默认 `completion="save"`，按声明范围完成验证、保存与回读。分阶段保留改动使用 `completion="review"`。参数使用对象、数组和路径字符串；源控检查维护真实资产归属。

测试使用原项目的已保存资产：

```python
result = session.submit_batch(
    operations,
    environment="test",
    test_options={"map": "/Game/Maps/Acceptance"},
)
```

首次测试返回 `test_host`，后续批次携带该身份继续。默认容量两组；测试输出交付后使用 `control_task(action="close", batch=...)` 清理所属目录。共享宿主在任务、活动与资产交接完成后使用 `shutdown_host` 退出。

## 启动

环境：Windows、UE5.8、接入项目的编辑器模块、Python 与 `requests`。

```powershell
$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 `
    -ProjectPath '<uproject 绝对路径>' `
    -EnginePath '<UE5.8 根目录>' `
    -PerformanceProfile Economy
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认资源档位 `Economy`：30 FPS、低优先级。渲染与音频通过启动参数选择。

## 验收与维护

- [公开契约](Docs/UnrealMcpCanonical.md)
- [调度与恢复](Docs/BBBMcpTaskProtection.md)
- [项目依赖](Docs/ProjectDependencies.md)
- [第三方来源](Docs/BBBExternalMcp.md)

```powershell
python -B -m unittest discover -s Tests -p 'test_mcp*.py'
python -B Tests/benchmark_mcp_workflows.py --report '<本任务目录>/discovery.json'
python -B Tests/verify_mcp_workflows.py --url $hostInfo.Endpoint --project-root '<项目根>' --task-directory '<本任务新目录>'
```

## 更新

2026-10-13：统一连接登记与恢复存储、结构化契约、三项工具发现、短调用结果、按批次等待和验证保存。蓝图读取提供总览、逻辑与几何视图；资源配置使用 `runtime.configure_mcp_resources`。

更新 2026-10-13: `control_rig.configure_sequence_animation_source` 原位替换唯一角色源动作 按源长度同步播放区间和原全长轨道 保留已有控制器及局部附件区间 适用于切换矫正动作基底 随后须重新写入源姿势控制器并烘焙回读
