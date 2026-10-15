# BBBUE MCP Tools

2026-10-15 新增 editor.refresh_montage_links 通过 UE 原生 UpdateLinkableElements 重建蒙太奇区段与通知链接 避免保留被替换动画的缓存引用 不改变通知时刻与片段播放配置

2026-10-15 新增已有 FK 重定向器配置：明确同名身体与手指链、自动姿势对齐、无独立 root 的骨盆根处理，以及七个目标辅助 IK 骨跟随，不导出动画。

2026-10-15 补齐外部重定向链创建和自动映射工具的明确资产写入范围，避免网关以 ASSET_SCOPE_REQUIRED 拒绝合法配置。

2026-10-15 骨骼动画集合导入支持独立网格加动画文件；数字开头的动作名自动加 AN_ 前缀，避免重复导入首个文件并统一复用源骨架。

2026-10-15 新增 Niagara 活动参数检查与批量值参数配置 用于 3D 流体的一次性效果调校 保留明确类型和保存回读。

2026-10-15 新增可复用的精灵爆发层配置与自有资产属性配置 GPU 特效拍摄改为真实帧推进 可在独立测试宿主执行。

2026-10-14 测试动作全部执行后可核实临时丢失的宿主完成证据 接续仅恢复核验 不重放操作 输入资产变化仍强制重跑。

2026-10-14 独立测试宿主显式应用网络模式 玩家数与独立服务端口 多玩家验收不再只依赖命令行配置覆盖。

2026-10-14 资产范围检查排除 UEDPIE 临时包 运行中演员调用不再误查不存在的磁盘包 正式地图仍按保存资产核对版本。

2026-10-14 近战装备创建与登记适配 Actor 类数组 Catalog 从默认对象读取 Definition 校验重复标识 不再构造旧的 CatalogEntry。

2026-10-14 保存与审阅阻塞返回可执行提示；同一客户端可用明确的脏包保存请求恢复自身审阅流程，参数错误给出缺失字段与契约查询步骤

2026-10-14 PIE Actor 定时调用可绑定明确的输入序列运行标识 从实际首个注入帧开始计时 排除外部请求排队对动作阶段的影响

2026-10-14 已完成测试子批次的结果由外层保留 内层历史结果回收后不再重复访问已删除记录 避免长时间 PIE 验收触发 KeyError 并关闭宿主

2026-10-14 场景性能评估新增只读 `runtime.inspect_scene_frame_metrics` 返回真实 Game Render GPU 帧耗时与玩家机位 标记 NullRHI 与零 GPU 数据不可用于验收 现有宿主资源配置支持独立测试宿主 详见 Docs/BBBScenePerformanceMCP.md

2026-10-14 测试队列容量只统计未结束批次 已完成与恢复的历史结果继续保留 不再阻止空闲项目启动新测试

2026-10-14 独立测试可显式启用 scene_performance 恢复项目游戏渲染设置 临时固定玩家机位通过 runtime.configure_scene_test_view 设置 不修改源场景或项目配置

2026-10-14 数据资产配置支持明确结构数组 枚举与类引用 蓝图函数更名可直接修复节点 基础动画层可按安全布尔事实平滑叠加骨骼分支姿势 派生层仅提供序列配置

2026-10-14 子层姿势叠加保留既有骨骼控制链 蓝图默认值写入统一使用 Perforce 写入策略 同时支持独占签出与已打开添加的新蓝图

2026-10-14 近战装备登记改用独立装备 Catalog 角色运行快照通过公开查询返回主手实例 使用序号 快捷选择和各格数量 翻越检查同步使用新版持有物品接口

2026-10-13 资产属性只读检查支持点分隔的嵌套字段 自动遍历结构数组并保留顺序 用于拆分目录前完整读取静态资源

2026-10-13 持枪运行时采样新增表现对象时间线 只读记录手持弹匣 物理弹壳寿命 池化特效状态与弹匣骨隐藏 不将组件数量误认为射击次数

2026-10-13 临时 PIE 演员嵌套组件配置只修改对象内部属性 不回写只读组件指针 值类型结构仍回写副本

2026-10-14 新增通用 PIE Actor 定时反射调用 按游戏时间触发公开 API 并回读实际时刻 用于准确验证动画阶段中断 不将网络往返延迟计入玩法阶段

2026-10-14 PIE 对象反射调用先确认所有者类型 再与 PIE World 比较 避免动画实例与组件被错误转换成 World 可用于只读核对实际蒙太奇

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

`BBB_MCP_URL` 由启动器返回，默认固定入口为 `http://127.0.0.1:8000/mcp`。连接层维护客户端归属、心跳、服务自动启动和请求重放。

## 编辑与测试

编辑批次自动完成验证、保存、回读和资产释放。异常结果由网关自动核实；保存故障按资产后台恢复，独立资产继续执行。结果记录独立保留。参数使用对象、数组和路径字符串；源控检查维护真实资产归属。

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

首次配置常驻服务：

```powershell
.\Scripts\MCP\Start-BBBMcpService.ps1 -ProjectPath '<uproject 绝对路径>' -InstallAtLogon
```

之后手动打开项目即可自动接入。`inspect_tasks` 显示服务、编辑器连接和进程清单；编辑器关闭后服务持续在线。已有服务切换安排在任务交接完成后。

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

- 2026-10-15：独立常驻服务、进程登记与自动重连；客户端自动启动服务；保留原测试进程并核验恢复归属。正式入口在任务交接窗口切换。

- 2026-10-15 `editor.set_pie_player_view` 设置当前 PIE 的临时玩家相机 保持原场景光照与画质 用于可视编辑器内从指定机位核验表现

- 2026-10-13: 新增 `editor.create_monster_director_assets` 与只读 `editor.validate_monster_director_assets` 经项目原生编辑器库创建并回读九个副本小怪导演基础资产 写入范围要求完整的明确路径数组 已有目标拒绝覆盖 使用方式见 `Docs/BBBMonsterDirectorMCP.md`

- 2026-10-13: `editor.run_automation_tests` 正确归为运行控制 可在公开网关登记的独立测试宿主执行 自动化前缀仍需明确 测试期间继续拒绝资产写入

2026-10-13：统一连接登记与恢复存储、结构化契约、三项工具发现、短调用结果、按批次等待和验证保存。蓝图读取提供总览、逻辑与几何视图；资源配置使用 `runtime.configure_mcp_resources`。

更新 2026-10-13: `control_rig.configure_sequence_animation_source` 原位替换唯一角色源动作 按源长度同步播放区间和原全长轨道 保留已有控制器及局部附件区间 适用于切换矫正动作基底 随后须重新写入源姿势控制器并烘焙回读

- 2026-10-13：新增只读 `editor.inspect_skeletal_mesh_skinning`，通过官方临时 modifier 读取网格实际父空间参考姿势和完整 LOD0 源顶点权重。拒绝 dirty 目标，缺插件明确不可用，不编辑、归一化、提交或保存；使用边界见 `Docs/BBBGenericEditorMCP.md`。

- 2026-10-13：新增只读 `editor.inspect_material_statistics`，读取明确材质的代表着色器指令、采样与插值统计。NullRHI 或不完整结果明确不可用，不作为零成本；读取可能等待引擎着色器编译。使用边界见 `Docs/BBBGenericEditorMCP.md`。

## 2026-10-15 自动协调

- 写入统一自动保存与回读，结果记录与资产占用分开管理。
- 异常结果由网关自动核实，保存故障按资产退避恢复；客户端离开后继续收尾。
- 公开控制动作统一为 cancel、close、shutdown_host；结果交付与后台资产恢复各自推进。
- 补齐地图、外部包、导入和引用改写的写入范围，清理全局脏包与审阅阻塞。
