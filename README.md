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

- 2026-10-12: 相机持枪配置构图读取当前姿态的纵向保留比例 不受空中冲量与回零倍率改变 用于分别控制镜头持续爬升和自动回落部分

- 2026-10-12: `animation.sample_weapon_handling_runtime` 同帧记录控制视角 实际镜头 FOV 物理 BBBMuzzle 插槽方向 AimIK 目标方向 动画层偏移 生命比例 IK 权重和待机小动作状态 输出 35 列轨迹 用于区分后坐力 镜头跟随 近处射线落点与姿势切换造成的实际准星变化 缺失枪口保留空值 不修改玩法或资产

- 2026-10-11：角色连续循环构图入口 `animation_graph.configure_character_continuous_locomotion` 从装备层已有动画与角色移动配置生成站立、跑步和蹲伏速度混合，仅更新基础继承层 Cycle 和主状态机的急转最低速度规则，保持主 AnimGraph 姿势组合。测试网关允许取消已经路由但尚未执行的自有测试批次，取消权限仍由原调度队列核验。

- 2026-10-11：`animation.start_pie_character_motion_capture` 与状态查询工具提供正式角色图的跨帧骨骼和截图观察；采样不修改输入、姿势、时钟或源资产，可与同宿主真实输入序列同时执行。

### 2026-10-11

碎肢只读诊断新增刚体位置 线速度 角速度 重力与质量. 玩家武器跨帧采样可显式启用碎肢诊断 验证实际抛飞 碰撞与落地残留 不改变玩法或物理状态.

后坐力镜头图表移除暂停回正设置 配合持续平滑回正。持枪运行采样新增实际枪口准星屏幕坐标和视口尺寸 直接读取项目 HUD 查询用于验证连射稳定性。

持枪采样作为只读观察活动 不阻塞同批次的输入序列 允许先开始采样 再执行开火 最后读取结果。

渲染测试宿主的启动等待上限改为十五分钟 容纳隔离缓存的首次着色器编译 无渲染宿主保持三分钟 超时仍回收所属进程。

统一五个公开接口、稳定工具 ID 和服务端批次调度。连接层维护归属，异步活动按实际完成证据续跑；占用查询按需展开，工具契约按目标加载。工具注册统一由 Bootstrap 完成。

宿主 Law 改为共享资产编辑与按需测试。测试直接读取原项目，采用 Windows 受限令牌、独立输出、端口和资产版本核验；支持两个测试批次并行，交付关闭后清理所属输出。

PowerShell 文件保留 UTF-8 BOM，Windows PowerShell 正确显示中文状态与错误。

僵尸共享命中血效重建改为十六个方向血滴、两张小尺寸喷溅和一张低透明度血雾，使用可见持续时间及年龄淡出，具体参数见命中反馈文档。

### 领域工具

- [通用编辑器](Docs/BBBGenericEditorMCP.md)：资产读取、动画通知、实例缩略图和编辑操作。
- [命中反馈](Docs/BBBHitReactionMCP.md)：玩法采样与实际角色表现检查。

本次同步保留领域更新：相机后坐力回正延迟、动画通知实例索引、运行时材质缩略图。

2026-10-11: 工具世界分类按完整 PIE 单词识别 修复 copies 被误判为运行世界的错误 资产副本合并继续遵守编辑器写入预检与批次归属。
