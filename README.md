# BBBUE MCP Tools

2026-10-18 握姿保存回读统一使用归一化四元数最短角度比较，消除配置浮点长度误差造成的旋转误报；保留原角度阈值，23 项制作回归及 Rifle01 实际烘焙回读通过。

2026-10-18 握姿 review 使用正式 LevelSequenceEditorBlueprintLibrary 打开制作序列并检查返回值，移除不存在的单资产编辑器调用；前台高速 UE5.8 宿主真实打开 Rifle01 底稿通过。

2026-10-16 新增 level.place_actor_from_class 按明确当前关卡校验原生类 标签与有限变换 创建后核对持久关卡归属并保存 不绕过资产范围校验 不启动 PIE

2026-10-16 恢复角色循环四向选片与原始 Lyra 方向扭曲 直接读取参考节点结构和输入配置 移除循环连续混合专用工具与变量 本轮仅编译保存 不进行运行或视觉验收

2026-10-16 动画浮点曲线替换支持 cubic_flat 原生三次插值与水平用户切线 曲线检查回读插值类型和切线 不使用密集线性关键帧冒充贝塞尔平滑 8 项单元测试通过 UE5.8 两份动画保存回读确认 RCIM_Cubic RCTM_User 水平切线及 0.72 秒恢复区间

2026-10-16 修复 PIE 混音导出完成检查缺少 Path 导入的问题 有效 WAV 导出后能正确释放录音活动

2026-10-16 扩展 editor.schedule_pie_actor_function 支持有界重复调用 每个游戏更新最多调用一次 通过公开 Actor API 稳定复现连续操作并记录实际调用时刻

2026-10-15 增加保留目录的动画库批次导入、审核模板的新源网格适配及全帧辅助 IK 和元数据只读验收；批次拒绝覆盖已有动画并逐项保存。

2026-10-15 动画原位导入支持显式 FBX 导入旋转并记录到导入数据；重定向检查增加参考骨骼位置及当前姿势偏移，用实际姿态核对坐标方向。

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

UE5.8 编辑器操作与任务调度。AI 使用六个入口；工具契约按当前目标读取。

## 调用

- 会话开始：`manage_operator(task="整理蓝图")`；默认二级，任务说明单行二十字以内。
- 当前同事：`inspect_tasks(operators=True)` 返回干员、等级、任务和状态。
- 会话结束：`manage_operator(action="finish")`。

- 已知工具：直接 `submit_batch`。
- 新目标：`find_tools(query)` 返回最多三项，首项附带参数、默认值和完成条件。
- 参数细节：`describe_tool(tool)`；SDK 复用同版发现契约，目录版本变化时更新缓存。
- 短调用：提交响应包含结果和证据。
- 长调用：`next` 为完整的 `{tool, arguments}` 调用或 `null`；按业务版本等待。
- 补充参数：`needs` 给出操作序号、字段路径与准确类型。
- 执行证据：终态保留结果、保存和回读；普通进度仅返回紧凑状态。

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

`BBB_MCP_URL` 由启动器返回，默认固定入口为 `http://127.0.0.1:8000/mcp`。连接层维护客户端归属、心跳、服务自动启动和请求重放。

## 干员与调度

零级最高，一级次之，二级默认。同级按提交顺序执行。零级可主动登记 `level=0`，面板也可授予；等级持续到逻辑会话结束。HTTP 连接关闭与短脚本退出保留身份，SDK 使用同一个 `conversation_id` 或私有 `client_key` 接续。每个聊天使用独立标识。Codex 中提供 `task` 时自动采用当前 `CODEX_THREAD_ID`，其它客户端可传入自己的 `conversation_id`。

高等级排队任务在可执行的操作边界优先进行。编辑批次先保存和回读再让行；同一资产的连续操作保持顺序。无关资产继续执行。运行中的原生调用在返回后进入调度边界。

零级控制：

```python
session.control_task("pause_operator", operator="干员ID", lease_seconds=60)
session.control_task("resume_operator", operator="干员ID")
session.control_task("cancel_blocker", batch="批次ID")
session.control_task("terminate_host", host="inspect_tasks 返回的宿主ID")
```

暂停默认六十秒，最多三百秒，到期自动恢复。定向终止由常驻服务核验进程代际并记录审计；宿主内存中的未保存修改随进程终止丢失。正常任务采用自动保存与回读交接。

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
- 公开控制支持批次取消、关闭、宿主退出及零级定向管理；结果交付与后台资产恢复各自推进。
- 补齐地图、外部包、导入和引用改写的写入范围，清理全局脏包与审阅阻塞。

## 2026-10-15 干员池与调用效率

六入口协议、逻辑会话归属、零至二级调度、限时暂停、定向取消与宿主终止。发现索引缓存区分读取与修改意图，补齐五十二个工具说明；自动收尾按蓝图实际编译状态执行编译。

工具详情按需附带三类短路线：属性配置、蓝图注释排版、武器运行时验收。每类说明所需输入、相近工具区别与完成证据。

异步采样与玩法输入分开提交。采样启动批次完成后继续注入输入，再等待所属活动并读取采样事实：

```python
session.wait_activity("weapon:probe", batch=test_host)
# 随后提交 animation.sample_weapon_handling_runtime 的 action=status 读取实际证据。
```

`test_host` 使用首次独立测试返回的身份。共享编辑器可携带采样批次身份。等待按业务版本推进，并核验宿主连接与所属活动。

固定五十条、自然表达二十条和独立验证十条均首项命中。自然表达经历一次改进；十条独立验证在改进后首次测试。实际注册目录为 728 项；各组发现响应中位数约 0.9 KB。搜索命中率受语料范围影响。

二十类完整任务通过本机 HTTP 与模拟 UE 执行端比较：可省往返场景 30→20 次请求，整体 52→41 次，返回体积约下降 33%，实际保存调用 10→10 次。覆盖参数修正、双会话资产交接、无关脏包、执行中断核实、图表快照过期和长任务结果。指标衡量协议往返与上下文体积；AI 思考时间及真实 UE 操作耗时由实际客户端时间线衡量。

```powershell
python -B Tests/benchmark_mcp_pipeline.py --profile candidate --report '<本任务目录>/pipeline.json'
python -B Tests/benchmark_mcp_workflows.py --catalog '<当前目录缓存>' --suite validation --report '<本任务目录>/validation.json'
```

2026-10-15 交接验收：协议 6 常驻服务上线，原 UE 进程自动接回；真实双客户端验证默认二级、高级任务先执行、暂停排队与到期自动恢复、契约缓存及准确补参。面板恢复在线，等级授予回读通过。隔离检查为 172 项 MCP、5 项启动及 2 项面板检查。

2026-10-16 修正编辑器自动接入心跳的服务协议校验为当前协议 6，消除在线服务被反复判为待恢复；7 项启动检查通过，直接使用 UnrealEditor.exe 与 uproject 路径打开项目的真实接入及只读调用通过，支持自动登记与当前宿主复用。

2026-10-16 干员生命周期：登记、使用、收尾、剔除由服务统一维护；最后一个传输连接关闭自动发起释放，五分钟空闲租约自动回收，心跳仅续连接。现有批次、保存恢复、PIE 和持续活动完成交接后删除登记，默认池清除离线记录。SDK 的一次会话覆盖完整任务。面板固定显示等级，指定云端站点通过专用等级接口修改并回读，管理会话每次操作结束释放。本轮按用户要求完成静态检查。

2026-10-16 启动地图：删除共享编辑器启动命令固定指定的 Entry 地图，编辑器按项目 EditorStartupMap 启动；独立测试宿主直接使用 test_options.map 指定的地图，省去先启动 Entry 再切换的流程。本轮完成静态检查。

2026-10-16 控制绑定写键统一使用组件空间减初始控制偏移后写入无父级欧拉通道，并逐帧回读，消除 Sequencer 预览演员位置污染。17 项序列生命周期检查通过；Rifle_01 装备抓握 55 帧烘焙回读的位置和旋转误差均小于 0.001，身体、右手及手指局部姿势保持。扩展运行 41 项控制绑定检查，另有并行网络探针的 bHidden 模拟数据缺项失败，未修改该模块。

2026-10-16 曲线编辑直接遵守资产写入网关和本地文件可写权限，不再查询 Perforce 独占签出，也不生成动画或 JSON 备份。仍保留未保存修改保护、有限数值与范围校验、写入后和保存后逐键回读，以及真实 Cubic 插值和水平切线检查。无备份边界及三次曲线的 8 项专项检查通过。

2026-10-16 权限与资产协调：执行判定集中到 MCP/mcp_decision.py；任务范围内原有脏包由服务核对占用后定向保存回读，再派发原操作。移除 ASSET_SAVE_REQUIRED 人工交接分支；零级明确管理动作统一校验权限，批次占用内部保留完整包集，默认返回八项摘要。保存与回读失败保留范围恢复证据。7 个修改或新增 Python 文件通过 AST 静态检查，服务命令行加载通过，7 项轻量隔离检查通过；真实 UE/PIE 验收按本轮要求省略。

2026-10-17 角色使用动作与特效制作完成实机验收：UpperBody 多片段与真实循环、F/G 和鼠标原始输入、跨 PIE 世界角色探针、ControlRig 逐键写入、Niagara 真实模拟年龄与世界时间录制、无引用自有资产清理及缺失通知实例恢复。65 项定向检查和 12 项 UE 战斗回归通过，双端使用与迟加入通过。112 格流体在 720p 高画质四枚并发的预热采样 GPU 中位数 12.07 ms、峰值 15.76 ms，首次运行卡顿及编辑器整帧范围单独记录；不宣称整项目或打包版本稳定 60 FPS。详见 Docs/BBBConsumableAuthoringMCP.md。


2026-10-17 动画层动作配置：新增 `editor.configure_animation_montage_selector` 为继承的无参纯函数配置同骨架蒙太奇固定返回值。拒绝非纯函数 不匹配返回类型及已有连线返回逻辑 编译成功后保存。`editor.configure_action_montage` 保留目标已有的 UpperBody 或 UpperBodyAdditive 槽位 并拒绝其它动作槽位。本轮按用户要求不运行自动化或 PIE 验收。

2026-10-17 新增 animation.replace_animation_bone_tracks，通过动画数据控制器替换显式局部轨道，校验有限数值、单位四元数、帧数和变换修正冲突，逐帧回读后保存。制作数据导出移到 Saved/temp/任务名。低功耗 NullRHI 宿主完成空手投掷 68 条轨道、每条 30 帧的实际写入、逐帧回读和保存，蒙太奇、通知和 IK 曲线回读成功；按用户要求不启动 PIE 或自动验收。
2026-10-17 新增批量左手握持重定向：复用 Rifle_01 Control Rig 序列模板，按显式接触帧和右手局部握持变换生成独立序列；官方烘焙只写入左臂白名单，逐帧核对其余骨骼，并核验 Root Motion、Additive、曲线关键帧与通知。隐藏 NullRHI 中档宿主完成 Idle 251 帧与 Reload Additive 67 帧序列生成、烘焙和保存回读；38 项相关静态检查通过。样本握持偏移仍待按 Rifle_01 实际握把校准，详见 Docs/BBBHandRetargetBatchMCP.md。

2026-10-17 左手序列制作改用官方 Sequencer 通道写入控制器关键帧，避免逐次写键反复求值；旋转跨越 ±180° 时保持相邻帧连续，保留最多 1200 帧的高采样率源数据，内部时间刻度匹配源采样率。修正复制 AnimNotifyState 时错误比较实例路径的问题；支持指向自身动画的 Selected Anim Frame 加法基准，并将新输出的自身参考同步更新。制作姿势使用有限左锁骨旋转处理手臂可达性，不改变骨长或项目 IK 配置。无截图运动采样不再阻塞触发动作的输入，也不修改游戏时间倍率。67 条实际基础动作的 5178 帧握持回读、214 个同步标记核对及 4 条专属动作烘焙完成；21 项针对性单元检查通过，剩余运行时画面由用户自行验收，接口和边界见 Docs/BBBHandRetargetBatchMCP.md。

2026-10-17 动画轨道替换增加已烘焙源模式：保留目标资产和原路径，源与目标帧率、骨架、事件及曲线一致时原位写入完整骨骼轨道，支持 1200 帧，逐帧回读后保存。拒绝元数据差异、骨骼缺失和源目标相同；4 项源模式检查通过。使用边界见 Docs/BBBHandRetargetBatchMCP.md。 Rifle01 的 67 项实际原位写入及 5178 帧轨道回读通过，元数据保持一致。

2026-10-18 Rifle01 双手握姿样板：新增真实 LOD0 蒙皮采样、带全指面清除约束的离线接触拟合和闭合组件深度审计；新增正式双手 Linked Layer 配置及 EditorPreview 实际求值工具。UE5.8 Development Editor 构建、49 项相关 Python 检查、正式 Base 六个独立权重场景通过；无曲线长源可直接烘焙短静态样板，并拒绝意外新增曲线。Rifle01 制作样板已本地保存，PIE 与自然程度等待用户人工验收。详见 Docs/HandPoseLayer.md、Docs/BBBGripPoseFitting.md。

2026-10-18 握姿制作流程规范化：新增唯一入口 `grip.author_weapon` 和型号 `Source/Animation` 正式制作配置，支持初始化、依赖核对、掌面平移校准、保骨长腕部求解、手指接触拟合、邻指约束、制作保存、真实回读和人工审核交接。输入变化使旧结果失效，求解及烘焙回读两道检查通过后才接入武器配置；重复保存和采纳有明确状态。邻指检查包含共面三角面分离轴及边边距离。手部截图新增独立目标腕骨、跨帧预热、状态回读及 -6 至 +6 档线性亮度补偿；同参数重复图像像素差为零，+1 档前景平均亮度实测提高约 13%。75 项相关数学与制作检查、15 项 MCP 契约检查通过；Rifle01 实际底稿的 68 个控制器和 136 个关键帧回读通过，扩大邻指检查发现左手两对局部交叉并阻止继续写入，保留既有外观。完整调用方法、低思考深度会话指令与验收边界见 [BBBGripAuthoringMCP.md](Docs/BBBGripAuthoringMCP.md)。
