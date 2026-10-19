# BBBUE MCP Tools

2026-10-19 新增 `hit.rebuild_zombie_debug_gore_cuts` 以实际湿血材质参数原位重建调试靶九组无骨头断面 皮肤接缝不移动 内部生成非对称两层褶皱 保留物理与既有图集 不创建烘焙中间资产。八项工具边界检查与 32 项受击公共入口基线匹配通过。用户停止测试后仅继续静态编辑和保存 最终资源不标记为经过运行或画面验收。见 Docs/BBBHitReactionMCP.md。

2026-10-19 手部层完整封装到 Base 主图仅保留一个姿势 Layer 调用。握姿与空值门控在 Base 读取 两侧曲线通过线程安全主实例查询取得。配置入口原位删除旧三个接口参数及其独占主图依赖 不保留兼容入口。离线验收与表面采样从瞬态主实例提供曲线与握姿 并检验关联实例自身曲线不会被误用。

2026-10-19 新增独立调试靶表面图集和多断点构建 检查及重排工具 `hit.build_zombie_debug_gore_surface` `hit.inspect_zombie_debug_gore_surface` `hit.repack_zombie_debug_wound_atlas`。仅写调试目录 不启动 PIE。五项工具边界测试通过 固定 2048 图集使用 GPU 可读的 UV2 长肢体默认约束同步保存 避免恢复为 45 度。原生与资产检查结果以任务最终交付为准 参数与验收边界见 Docs/BBBHitReactionMCP.md。

2026-10-19 新增通用 editor.reparent_skeletal_mesh_socket：在保留参考组件变换的前提下，将已有自有网格插槽挂到实际机构骨，原生校验位置、角度和网格归属后保存。Shotgun01 的 LeftHand 已实际重挂 Pump_joint；独立回读参考位置误差 0.000000234cm、角度0，第三方共享骨架摘要不变，真实开火机构轨道位移6.522cm。这里只证明插槽和实际机构数据，未冒称完整运行时动画图验收；网格自有插槽分支已实际验证，继承插槽覆盖分支尚未做项目实测。详见 Docs/BBBGenericEditorMCP.md。

2026-10-19 明确资产删除与迁移空原包清理改为单次原生整组删除，全部SHA、精确路径、真实类型及组外硬软引用保护保持，逐文件核验，失败不重试；43项移动、5项整组删除和7项既有保护回归通过。此前61旧包冷清、8旧LS及Other首16项真实原生收口通过，新批量实现仍待统一重载后的独立实际验证。

同日前台宿主37312实际完成LMG01唯一Preview迁移和新实现16项Other整组移动清理，目标保存、旧文件及注册表清理、引用和脏包独立核验全部通过。新16项22秒，旧16项87秒，均保留真实报告；后续公共归整继续逐批核验，不把该小批结果扩张为全目录已完成。

随后Other1656项及独立延后1项已实际完成原生移动与全量核验；新增11个已获制作者交接的旧LS严格整组删除通过。Used244合并批次真实改名和429正式目标/引用者保存已完成，但循环蓝图占位类及旧包脏标记使自动终验失败，按精确原生重载和集中冷清理收口，不重复改名、不将该部分执行伪称自动成功。详见专用资产维护文档。

2026-10-19 原生普通删除与重定向器删除共用精确目标包动画控制器根引用释放 防止已改名动画的临时控制器阻止旧包原生清理。其它包及非控制器根引用保持不变 新增真实双包控制器自动化隔离回归待编译执行 Python迁移专项42项离线通过 实际自动迁移仍待统一加载验证。见 Docs/BBBAssetMaintenanceMCP.md。

同日原生构建与真实 `BBB.Editor.AssetRepair.ControllerRootScope` 隔离回归已通过 Rifle03剩9旧包严格摘要原生删除完成 18条最终独立核验旧文件 旧引用 重定向器及脏包均为零 DA和6蒙太奇实际引用正确 新自动执行器的完整移动验收另行记录。

Sniper02随后完整自动入口仍因同宿主空原包持有而如实失败 新目标与引用者已保存 按本次已批准流程集中保留原SHA待最终冷宿主严格原生清理 中途只精确丢弃已证空旧包的脏标记 不重复改名 不将旧残留未清零的状态标成迁移完成。详见上述维护文档的实际边界。

SMG03唯一弹匣预览的单项真实自动迁移已完整成功 新目标与旧HandEdit引用者均保存 旧文件 旧引用 重定向器和脏包独立核验为零 不建立第二份预览。该单项成功与上述特定旧资产仍需冷清理的边界分别如实记录。

2026-10-19 原生批量迁移补齐完全空原包的封闭收口：保存真实目标与引用者后，只对本次已改名且无子对象的原包执行原生重载，再按原文件SHA、真实类型和无组外引用约束原生删除。40项迁移回归通过；Rifle03两AS已分步恢复并通过最终磁盘、注册表、旧引用和脏包核验，新增自动收口仍待统一重载后验证。未扩大到未知空包，不直接删除包文件。详见 Docs/BBBAssetMaintenanceMCP.md。

2026-10-19 普通资产批量迁移在原生重命名后显式保存实际目标、引用者和原包，再刷新目录及验证；报告单独记录持久化结果，失败不自动重试。35项离线迁移回归通过，真实两动作迁移仍待工具重载后核验。原生 FixedArray 点路径已在实际 BlendSpace 两资产的32项设置和1D缩放字段中验证，逐项值相等且无脏包。详见 Docs/BBBAssetMaintenanceMCP.md 与 Docs/BBBGenericEditorMCP.md。


2026-10-19 专属动作支持显式掌空间指节卷曲、四阶段枪组件接触平移及操作后左指平滑回握；按实际骨架只写明确臂、辅助骨和手指，不进行握姿优化或参数搜索。74项针对性检查通过；Rifle02最终四动作405帧原生回读通过，最终换弹LS九阶段独立瞬态烘焙未检出骨骼差异，薄截面握匣与回握图由代理实际检查。真实插入对应顶点误差约0.0000669cm，拒绝的90度匣体旋转版本未合入。详见 Docs/BBBWeaponActionAuthoring.md。

2026-10-19 新增正式握姿彩色三视图 CLI、独立静态附件实际 RenderData LOD0 只读采样和显式动作绝对轨道写入入口。Rifle02 四条动作共405帧原生回读通过，双手静态图与实际取匣附件图已检查；69项针对性回归通过，涵盖视觉来源、动作数学、静态附件、瞬态审计和原有握姿制作。静态与动作共用父骨先于子骨的辅助骨同步，Rifle01/02真实三对手部辅助骨均在原0.001cm/0.02度内，修正后正式双手图已检查；没有把技术修正版冒充新一次人工accept。序列烘焙审计改用纯瞬态副本，四动作官方烘焙对照未发现超过阈值的差异，不再创建正式临时资产或写源LS；UE控制器暂存对象如实标为等待宿主退出，未冒称即时释放。详见 Docs/BBBGripVisualReview.md、Docs/BBBWeaponActionAuthoring.md、Docs/BBBControlRigAuthoringMCP.md；数字回读与图生成不替代自然握持或最终用户运行观感验收。

2026-10-18 四元数矩阵转换拒绝4×4齐次矩阵及非纯旋转，修复共享卷曲原型把目标组件矩阵与实际输出旋转混用的隐患；30项方向和制作回归通过，原型正在按实际姿势重新拟合，详见 Docs/BBBGripAuthoringMCP.md。

2026-10-18 握姿增加掌空间参考骨轴和当前双骨轴方向检查，捕捉局部角度未变但拇指整体向下、末节反向等问题；失败纳入正式保存门槛。四项方向回归与既有25项制作回归通过，真实候选与人工复核尚在进行，详见 Docs/BBBGripAuthoringMCP.md。

2026-10-18 新建握姿 Rig 改用现行 SetTransformItemArray，修复旧集合节点与裸 Items 数组契约不匹配导致控制器已写键但骨骼仍为参考姿势；25 项制作回归通过，Rifle02 原生替换节点后求解、烘焙及全部原生回读通过（人工握姿另行确认），详见 Docs/BBBGripAuthoringMCP.md。

2026-10-18 控制绑定组件目标复用已存在的九通道写键辅助函数并展开欧拉角，修复官方复数接口真实 varying-key 验证中的帧值重复；保留初始偏移、全部帧真实回读和原拒存门槛，移除逐键预览切时；20 项生命周期检查及真实 UE5.8 的 2040 个变动关键帧写入回读通过，耗时 2.832 秒，详见 Docs/BBBControlRigAuthoringMCP.md。

2026-10-18 握姿接触增加按骨命名的中节和末节指腹独立门槛，校验实际顶点和蒙皮权重，防止整指接触数量掩盖局部悬空；24 项制作回归通过。

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

## 工具动态

2026-10-19 双管装填三视图允许两个实际 Notify 实例以不同 `instance_id` 共用一份同SHA原生StaticMesh，并分别显示重叠窗口内的真实挂接；缺失或重复实例仍拒绝歧义。新增两项防错后视觉检查24项通过，见 [BBBGripVisualReview.md](Docs/BBBGripVisualReview.md)。

2026-10-19 分段换弹动作可通过明确的 `entry_hold_release_frame` 从静态握持释放，循环和结束段不被错误识别为重新入场；拒绝非正与非有限帧。必要分段回归及既有动作检查共16项通过，详见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。

2026-10-19 动作附件改握以 `hand_attachment_grip_changes` 的原/当前局部刚体和显式阶段统一反补腕目标，保持匣体世界轨迹；实际证据支持的小角度机构修正可另用枪空间 `contact_transforms`。拒绝缩放、非法四元数、窗口重叠及重复机构来源，空程不改原轨迹。3项必要刚体回归与既有动作检查共15项通过；自然程度仍须实际原生蒙皮看图，详见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。

2026-10-19 显式机构平移支持有序不重叠的 `contact_translation.phase_windows`，把同一已证平移分别用于取旧匣与插新匣，中间身体取匣空程不改变；禁止同一修正同时指定单窗及多窗。2项必要防错与既有动作检查共12项通过，见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。

2026-10-19 动作附件三视图支持旧匣与新匣在不重叠的原生通知窗口共用同一真实StaticMesh样本，保持各自挂接变换；拒绝窗口重叠、同网格摘要冲突及任意源帧。新增两项必要回归后22项视觉工具检查通过，见 [BBBGripVisualReview.md](Docs/BBBGripVisualReview.md)。

2026-10-19 动作三视图支持从正式动作源读取实际武器蒙太奇播放倍率，严格按角色秒数乘该倍率选择真实武器源帧，不接受任意不同时间或非法倍率；未指定仍要求同秒数。一项新增回归覆盖真实非一倍速映射及错误帧、零值、负值、非有限值拒绝，20项视觉工具检查通过。见 [BBBGripVisualReview.md](Docs/BBBGripVisualReview.md)。

2026-10-19 右腕路径真实验收完成：正式 AimIK 前增量节点配置与六个动画蓝图编译保存通过 五个瞬态原生 ModifyBone 预览场景的父空间左乘误差均零 零偏移与禁用装备完整姿势一致 非交换错误乘法偏差约 46.8736 度 每次输出 2716 个手部顶点且无项目脏包。Rifle01 制作 LS 的源引用已通过仅替换入口切到等价私有序列 其它片段参数和轨道保持 旧公共源无引用。范围与证据见 [HandPoseLayer.md](Docs/HandPoseLayer.md)。

2026-10-19 新增只读 `editor.sample_hand_handling_surface` 在瞬态 EditorPreview 世界实际执行正式双手握姿与按正式已保存配置复制的原生右腕节点 按显式动作秒数和装备右腕快照输出实际 local/component 骨骼及原生 LOD0 CPU 线性蒙皮 用于既有彩色三视图。主玩法图 枪口瞄准与左手 FABRIK 目标未注入时明确不作为这些路径验收 不保存正式资产。原生构建及真实节点求值待统一验证 见 [HandPoseLayer.md](Docs/HandPoseLayer.md)。

2026-10-19 新增 `editor.configure_right_hand_grip_rotation` 在明确 AimIK 前配置共享右腕增量 采用父骨骼空间 AddToExisting 独立装备门控 零偏移停用 不使用手指 Disable 曲线。角色配置和动画事实链同步提供线程安全查询 四项保存边界检查通过 原生构建与真实图求值另行验收。见 [HandPoseLayer.md](Docs/HandPoseLayer.md)。

2026-10-19 新增 `control_rig.replace_sequence_animation_references`，以显式映射仅替换已有骨骼动画片段引用，等长同骨架且每项实际匹配后才写入。保留停用状态、时间范围、完整其他片段参数和制作轨道，不调整播放长度或重烘焙。6 项独立离线检查通过；真实 UE 制作序列回读另行记录，调用细节见 [BBBControlRigAuthoringMCP.md](Docs/BBBControlRigAuthoringMCP.md)。

2026-10-19 原生 handling 视觉校验对已通过单位范数门槛的右腕四元数归一化后比较方向，保留原 `0.02` 度角差门槛。真实 float32 同方向快照回归与其余四项 handling 检查通过，错误方向仍拒绝。

2026-10-19 动作工作器新增明确 `forearm_roll` 窗口，将指定旋前/旋后分配给真实前臂与皮肤扭转骨，保持已求解腕组件目标和骨长；仅声明并校验此字段时允许新增该扭转轨。两个必要专项及现有动作共十八项检查通过，正式自然性仍由实际原生前臂蒙皮视图验收。调用与有限角度边界见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。

2026-10-19 增加显式 `finger_pose_windows`，在真实持物窗口混入本枪完整十五指骨局部旋转，保持骨长、缩放和腕轨迹，避免原动画中段指形漂移使鼓匣穿掌。入口拒绝不完整、非法四元数、越界及重叠窗口；两个必要回归覆盖动画源指形不同仍保持同一握物形状、零权重精确保留及非法输入拒绝。完整原生保存、显示窗口逐帧诊断和实际前臂/双手看图仍由制作任务执行，见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。

2026-10-19 固定指姿和有界阶段声明的唯一验证提取到纯标准库 `BBBWeaponActionPolicy.py`，避免编辑器包装导入 NumPy 工作器；保留明确 `boundary_hold` 规则。新增真实 `python -S` 导入检查，正式编辑器 dry_run 与保存仍需单独回读。

2026-10-19 动作工作器支持明确人工左腕组件关键姿态 `left_wrist_component_keys`，先计算枪空间接触和附件改握反补，再覆盖指定段，严格匹配已经修正与反补后的首尾目标。二十六项动作回归通过，包含非轴对齐反补后七厘米边界保持、中段腕旋转覆盖及旧边界拒绝；接口保留唯一可复建制作输入，原生视觉与机构验收保持独立。

2026-10-19 `editor.inspect_animation_notifies` 从既有编辑器库原生读取 `GetTriggerTime/GetEndTriggerTime/GetDuration` 及触发偏移，新增 `nativeTriggerTime/nativeEndTriggerTime/nativeDuration/triggerTimeOffset/endTriggerTimeOffset`；按通知实例和数组位置校验对应关系，禁止通过 Python 双精度相加推测通知结束。八项通知检查通过，包括真实浮点边界保留与数组错位拒绝；C++ 构建及实际通知回读由统一宿主重载验收，见 [BBBAnimationNotifyMCP.md](Docs/BBBAnimationNotifyMCP.md)。

2026-10-19 分段换弹的明确 `boundary_hold` 使腕附件反补和十五指姿窗口最多跨动作前后各一帧，保持 Start/Loop/End 实际边界握姿连续；未声明时继续严格限制。完整动作二十三项检查通过，包括真实七厘米腕反补及固定指姿跨三个片段保持、正常退出和非法越界拒绝。接口见 [BBBWeaponActionAuthoring.md](Docs/BBBWeaponActionAuthoring.md)。同轮原生通知时间入口已在八个真实蒙太奇的三十六条通知上独立回读成功，证实 SMG 旧匣应第十七帧退出及 LMG01 第四十五帧恢复枪匣，未以双精度和替代原生结束。
2026-10-19 动作原生回读的满回握检查按该帧声明的机构平移、刚体接触和握匣反补计算实际目标，避免把仍有效的接槽窗口误算为静态握姿误差；退出窗仍回到静态目标。专项回归同时验证正确枪空间接触通过，以及错误轨道虽然与保存动画一致仍被目标检查拒绝。原生资产未因此重烘，视觉验收保持独立。

2026-10-19 公共目录迁移最终核验：Other1657全部原生迁移闭合，Used242及2个Items输入的244旧源在新宿主按真实引用顺序严格SHA冷清理后独立核验通过；Base重新编译，Main/Base/ALI及四层实际全部BS_UP_TO_DATE。另66个完整骨轨公共可编辑LS同名迁入Used/hold并独立核验通过，全部边界dirty为空。保留前次同宿主部分失败记录，不冒称自动链一次成功，也不将制作底稿归属证明当作成品全帧等价。详见Docs/BBBAssetMaintenanceMCP.md。

2026-10-19 新增参考姿势相对的前臂 Swing/Twist Rig 制作、可选原生蒙皮参数审计和正式 AnimGraph 节点插入入口。正式双侧 Rig 与主图已编译保存；用户停止测试后采用左右0.5基准，不宣称最佳参数或完整运行验收。48场景七档RigVM调用在停止指令前已结束，非目标局部变换保持；正式单节点原生求值入口本轮未执行。详见 [BBBControlRigAuthoringMCP.md](Docs/BBBControlRigAuthoringMCP.md)。

2026-10-19 经用户批准恢复完整FABRIK握持应用与原右腕配置工具，manual_apply恢复角度写回，删除位置双骨IK腕部换算工具、注册与记录。UE5.8完整编译及六个动画蓝图编译保存通过，14把握姿/配置已回读，28份人工LS/Rig哈希不变；未执行PIE或额外测试。

2026-10-20 新增只读 `level.audit_static_scene_components` 统计明确演员的组件 材质 碰撞 实例与 LOD0 几何估计 UE5.8 宿主核验 115 个楼体 1881 个组件 219202 个实例且无脏包 新增 `level.create_static_actor_mesh` 保留原材质 所有源 LOD 和碰撞 创建时可一次生成保留完整回退几何的精确 Nanite 真实渲染宿主的 11 栋创建与保存回读已通过 六向碰撞采样发现 2 栋复杂碰撞差异且合并没有帧率收益 已恢复来源并清理候选 新增 `level.set_static_mesh_nanite_settings` 一次性提交原网格 Nanite 精度与回退几何设置 默认只预检 语法和真实宿主重建通过 23 个硬表面及 2 个树木试验无帧率收益 已恢复原 Nanite 配置 材质与 BodySetup 引用不变 派生数据由引擎重算 同时补全官方 `scene.remove_from_scene` 的明确演员写入范围 300 FPS 完整验收仍在进行 约束见 `Docs/BBBSceneOptimizationMCP.md`
