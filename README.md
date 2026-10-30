# BBBUE MCP Tools

2026-10-30 持枪表现采样：现有移动探针增加 17 根最终骨骼的位置与四元数、枪口/左手目标事实、禁用曲线和链接层瞄准权重，保持只读。真实 FAL 两项 300 帧短对照完成并确认输入与时钟释放；语法及有限数值检查通过，不作为玩法验收。调用及采样边界见 Docs/BBBPresentationProbeMCP.md。

2026-10-29 手枪握持制作阻塞修复：左手动作烘焙直接使用正式制作源已保存的 `grip_in_hand_r`，拒绝缺失或无效输入，不再依赖缺轨参考动画求值。M1911 的 51 份制作源已按同一角色网格及参考路径核对，47 份缺失输入补齐为四份既有制作记录中完全一致的握持变换。语法与制作输入核对通过，未重写手枪动画或声称参考动画已恢复。

2026-10-29 动画数据恢复扩展：原生复制同骨架骨轨并回读，失败回退；骨架元数据可仅恢复平移重定向模式。恢复分支通过隔离原始动作、正式 Control Rig 制作源和故障前摘要核验后写回，保持曲线、通知、标记及压缩设置。量化边界和已保存同源根轨对齐分别记录严格证据，缺少根轨时仅补回已核验身体轨道并标记局部恢复。原生编译与正式包保存回读通过，未执行玩法或自动化验收。见 Docs/BBBAnimationMigrationMCP.md；具体资产恢复缺口以宿主项目 Docs/Animation/AnimationBoneRecovery20261029.json 为准。


2026-10-29 武器 MM 元数据批量核对：既有动画曲线检查入口补充只读动画设置与原生通知时间及 Pose Search 成本值，支持裁帧动作的元数据迁移前后比较，无需重启宿主。五项元数据防护与二十七项曲线处理检查通过，UE 宿主已回读标准转身标记。见 Docs/BBBGenericEditorMCP.md。
2026-10-29 现有双臂入口的_LeftHandMotion制作源分支完成三条MM1700样板原位保存：待机299、步行119、跑步74采样。官方瞬态烘焙仅写左臂旋转及左手辅助IK平移，保留根轨、手指、右臂和元数据；审核序列挂接同步当前FAL配置。已打开前台等待用户播放审核，未执行PIE或自动化验收。见Docs/BBBHandRetargetBatchMCP.md。

2026-10-28: 急转输入支持有限的大幅视角值与可选固定模拟步长 正常结束和取消均恢复原时钟。MM 探针增加根骨相对胶囊与控制朝向差。独立原版 GASP CMC 完整控制链对照核实了 Strafe 默认状态与输入增益 地面 360 度每秒限速会延迟大转向选片。原生编辑器编译成功 31 项探针与姿态检查器测试通过 项目完成 60 次急转采样。画面与双端结果以项目 Docs/Animation/UnarmedStrafeTurn20261028.md 为准。

UE5.8 编辑器操作与任务调度。AI 使用六个入口；工具契约按当前目标读取。

2026-10-28: MM 探针格式 8 增加手臂与手部骨骼 实际混合配置 原始步相曲线和逐帧 Delta Time。来源回放按录制步长运行并恢复原时钟。26 项离线检查通过。独立 GASP 对照 3079 帧事实零差异 三种平地移动的 12 项姿态基线比较通过 两边均保留帧间隔告警 不宣称稳定 60 FPS 验收通过。详见 Docs/BBBMotionMatchingRuntimeMCP.md。

2026-10-28：新增子弹表现预览窗口的打开与状态读取入口，使用编辑器预览世界与项目正式 Niagara 数据通道，不进入 PIE。编辑器源码编译、窗口打开与工具契约静态检查通过；运行中的服务目录需刷新后才能发现新增入口。

2026-10-28：精简发现契约、修复等待恢复动作，合并数据表行名重复入口。工作树及当前缓存目录下，87 条既有查询首项命中 85→87；扩展查询共 99 条全部首项命中；20 项隔离流水线通过。具体工具契约按任务查询。

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

零级最高，一级次之，二级默认。同级按提交顺序执行。零级可主动登记 `level=0`，面板也可授予；等级持续到逻辑会话结束。最后一个所属连接关闭时，干员进入收尾并在工作交接后释放。SDK 通过同一个 `conversation_id` 或私有 `client_key` 恢复所属批次，重新登记后开始新任务。每个聊天使用独立标识。Codex 中提供 `task` 时自动采用当前 `CODEX_THREAD_ID`，其它客户端可传入自己的 `conversation_id`。

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
    -PerformanceProfile Balanced
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认资源档位 `Balanced`：60 FPS、Normal 优先级。渲染与音频通过启动参数选择。

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

2026-10-27 僵尸血肉工具：`hit.rebuild_monster_blood_system` 增加碎肉网格及材质输入，生成近视点筛选的共享碎肉粒子层，保留已有血效公开参数。UE5.8 编辑器目标编译链接通过，重建后十个系统及发射脚本均为 UpToDate；未运行 PIE、自动化或视觉听感验收。接口见 `Docs/BBBHitReactionMCP.md`。

2026-10-26：FAL 已审核装备与换弹 LS 以官方 Sequencer 直接烘焙为 ANI_BBB_Rifle_01_CharacterEquip 与 ANI_BBB_Rifle_01_CharacterReload，并接入对应 UpperBody 蒙太奇。应用动画片段后调用既有原生 RefreshMontageLinks，按当前片段重建区段与通知链接，避免 LinkedSequence 缓存继续引用旧烘焙。两段骨轨回读误差0，既有3/6条通知及时间完全保持。确认旧两条 *_ManualEdit 无硬软引用后，以当前 SHA256 核验和原生删除清理；LS、Rig、原始动作及仍在使用的枪体动画保留。

2026-10-26：ManualAction 支持 sync_weapon_attachment_request=true，通过当前 Definition 的 SpawnOffset 重定基准。保留已有局部运动相对旧基准的残余变换及各通道关键帧时间，只改 Weapon 唯一变换段；默认值与关键帧共同更新，拒绝非九通道或时间不对齐的轨道，比较其它轨道摘要后保存并消费请求。最新手部握姿通过既有 grip_endpoints_request 指定同型号已应用 HandGrip 及左右 finger_sides，在首尾窗口匹配，保留换弹中段。FAL 换弹实际挂接默认值回读与配置一致，原两键时间保留，首尾位置误差0.000064厘米、角度误差0.038度，中段关键帧保留；仅更新制作序列，不烘焙或替换运行蒙太奇。

2026-10-26 僵尸二级破坏工具迁移为八区躯干毁伤与五处断肢。原生材质构建读取十三份正式配置并生成三档共享组织。群体生成与性能测量接收明确区域数和断臂参数并核对实际事实。跨端只读检查包含同一身份的八区强度和断点。七项伤口与十四项群体工具回归通过。UE 编译与六项原生毁伤回归通过。实际联机 / 截图与性能结果记录于项目 Docs/ZombieDestruction_20261025.md。调用边界见 Docs/BBBMonsterGoreMCP.md。

2026-10-26 动作匹配工具增加原生逐帧采集、独立 GASP 事实回放、固定姿态质量检查、精确旧状态机展开和原地序列索引根速度配置。格式 7 读取实际植足状态及最终骨骼，拒绝缺帧、空轨迹、缺少接触覆盖或全动作排除的假通过。项目空手六组 5526 帧与来源 5544 帧逐帧对照、333 项阶段比较及 FAL 841 帧回归通过；53 项 motion_matching 测试和 5 项曲线/重定向契约检查通过。来源夹具不保存外部资产，工具边界见 `Docs/BBBMotionMatchingRuntimeMCP.md`。

2026-10-25 修正步枪 MM 动画的锁根位置为 Zero。原动画首帧含数米偏移及不同朝向 使用 Anim First Frame 会在检索切片时造成网格跳变。372 个序列通过原生矩阵统一锁零点并保留根轨道 装备步枪的 PIE 静止采样 31.27 秒胶囊和根骨位移均为零 未新增原 PoseJump 警告。

2026-10-25 新增 `editor.configure_animation_root_motion_matrix`。使用引擎原生属性矩阵批量配置明确动画序列的根运动读取和锁根设置 保存回读并核对动画数据模型指纹不变 支持显示矩阵供人工查看。

2026-10-25 新增 `BBBMotionMatchingToolset`：构造标准 Pose Search Schema 与候选 Database 原生等待索引完成并核对姿态数和维度。支持动画层提供五组普通运动数据库 主线程候选库更新 线程安全轨迹与 MM 回调 合并普通状态和导管 以及精确清理旧图和变量。资产移动跳过已保存清洁包 并直接原生清理已确认完全空的原包。UE5.8 Editor 编译和数据库索引回读通过 工具边界专项检查通过 动画效果交由用户验收。调用边界见 `Docs/BBBMotionMatchingMCP.md`。

2026-10-25：时间轴新增原生实例核验。项目 UBBBSequencerViewEditorLibrary 按明确序列取得 ILevelSequenceEditorToolkit 的 ISequencer，使用 SetClampRange 与 SetViewRange(Immediate) 同时重置活动视图缓存，回读实际实例范围及播放区间。ManualAction 的 timeline_ui_request="instance_repair" 显式调用并比较通道摘要；inspect 同时报资产范围、实例范围及当前帧。此前只写 MovieScene EditorData 或同进程窗口重开，不能作为彻底修复证据。正式编辑器重启加载后 FAL 拔枪实例及窗口截图核验正常，延后多次回读有限；UE5.8 Editor 编译通过，四项时间轴专项检查通过。

2026-10-25：拔枪序列时间轴复发时使用分帧恢复。ManualAction 制作源 timeline_ui_request="close" 只调用共享修复器关闭窗口、恢复范围并保存，不在同次调用重开；待编辑器 Tick 后另批 open_in_sequencer，再设置 timeline_ui_request="inspect" 读取真实视图、工作范围和各轨边界。仅即时范围回读不能证明窗口恢复。FAL 拔枪实测同次重开后上界再次 NaN，分帧重开后独立回读为 -0.085 至 1.785 秒；播放区间与关键帧保持。三个时间轴专项检查通过。

2026-10-25：握持 manual_prepare 在加载 Rig 与准备预览前复用 repair_timeline_range。发现 NaN、无穷或倒置窗口范围时，关闭完整资产编辑器，按原播放区间重建视图与工作范围后保存重开，并立即返回；核验控制通道和播放区间不变，不进入握姿重建或运行配置写入。FAL HandGrip 实测将 NaN 视图结束值恢复为有限范围，两项时间轴回归通过。

2026-10-24 用户取消FAL手指修复，9条角色成品已从正式LS、人工握姿源及完整动作快照恢复并保存；非目标轨、位移缩放和元数据保持。现有指骨入口支持restore_sequences及restore_records明确来源恢复，官方烘焙仅用瞬态副本，不改正式LS或生成备份资产。详见 Docs/BBBFingerAnimationMCP.md。

2026-10-24 正常退出：control_task(action="shutdown_host") 使用宿主身份核验及延后退出小工具，先关闭蓝图窗口，再调用官方 quit_editor。请求失败恢复调度，退出前再次检查 PIE、活动和脏包；inspect_tasks 区分退出安排与实际进程退出。75项针对性检查通过；当前编辑器保持运行，真实退出待新版工具集加载后验证。

2026-10-24 自动整理改为调用原版 UE5.8 Graph Formatter 2.3.1 删除旧自研排列和自动注释布局 保留手动编辑 两个第三方插件源码不变 构建与调用核验通过 动画图视觉及重复排列稳定性未通过 已恢复目标图测试前坐标 详见 Docs/BBBGraphFormatterMCP.md

2026-10-24 故障接管：零级通过现有 recover 入口原子接管终态故障批次，转移归属并记录审计，原客户端控制权随之转移；迁移清单和资产核验流程继续使用原记录。60项针对性检查及3个改动Python文件语法解析通过。迁移恢复先读取实际目标、旧路径和引用核验；全部落盘且范围内脏包为空时沿只读证据完成交接。真实批次7bf8365513fe0b0b的1801项资产核验通过，1156项故障占用释放，当前资产占用与脏包均为零。

2026-10-24 迁移恢复：按包保留保存成功与失败阶段，故障批次接续目标与引用者保存及已核验迁空源包清理。control_task(action="recover", batch=...) 恢复所属故障批次，零级可接管其它会话的故障批次；干员收尾和 SDK 重连保留受限恢复入口。自动恢复达到四次故障记录后保留占用并交付原因，宿主代际变化保留迁移证据等待核验。 验证覆盖163项定向隔离检查，其中1项本机连接中断后单独复查通过；251个Python文件语法解析通过。

2026-10-24 按用户要求完整删除专用伤口预览窗口 手柄编辑及后台预览世界入口 不保留旧 API 转发 统一伤口工具只提供正式共享材质适配和资源检查 实际表现使用场景调试靶及正式 Mass 命中链迭代 预制组织不再被身体的投影遮罩重复裁剪 玩家采样在 PIE 意外退出或报告失败时也结束活动 防止旧采样占用宿主 十八项定向工具检查通过 不以接口检查代替表现验收 见 Docs/BBBMonsterGoreMCP.md 和 Docs/BBBHitReactionMCP.md

2026-10-23 修正指骨约束的绑定基准错误：共享Skeleton与实际手部网格的食指参考旋转相差约20度，旧数值通过不能代表网格正常。现从原生网格真实绑定建立中性基准，按明确网格的RAW重定向求值提取方向；MM_Shotgun_Reload 已重新保存24骨86采样并前台打开，非目标轨和元数据保持。当前效果待用户播放确认，详见 Docs/BBBFingerAnimationMCP.md。


2026-10-23 逐发后坐力清理: 项目用逐发姿态轨迹替代角色方向冲量 submit_character_diagnostic_inputs 不再接受 AimImpulseFact 不保留兼容分支 当前仅接受 Camera Unequip AimFact 原生端与公开参数同步移除旧包引用 项目 UE5.8 编译通过

2026-10-23 指根进一步限制为俯视平面内正负3度摆动，清除指根长轴扭转和大幅卷曲；逐帧使用动画实际骨长并去除展开后提取卷曲，修复重复处理漂移。MM_Shotgun_Reload 已原生重烘焙保存并前台打开，指根轴扭转与卷曲回读均小于0.00002度，最大俯视摆动0.4785度；非目标骨轨和元数据保持，用户播放验收待完成。详见 Docs/BBBFingerAnimationMCP.md。

2026-10-23 用户否决宽容指骨规则后，editor.process_animation_fingers 增加 geometry_chain 掌空间硬约束：四指共同前向，每节仅保留向掌心卷曲，清除反向弯曲、侧弯及扭转。指定 MM_Shotgun_Reload 的双手24骨、86采样已实际重建保存并前台打开；其他骨轨与动画元数据回读保持，效果待用户播放确认。四元数角距离先单位化；制作参数和证据保存在角色 Source/Animation/MM_Shotgun_Reload_FingerRepair.json.source，未重烘各武器离散动作。详见 Docs/BBBFingerAnimationMCP.md。

2026-10-23 指骨工具已完成前台注册和两条动画的原生只读采样、候选彩色三视图；未烘焙或修改人物动画。视觉检查后补入参考固定偏置保留、共同展开中心和检查方案摘要约束，八项离线边界通过；实际保存及最终观感仍待用户指定动画验收。用户明确后续由其指名动画，处理后打开前台窗口并根据其反馈修正，已取消额外排队校准。见 Docs/BBBFingerAnimationMCP.md。


2026-10-23 新增 animation_finish 事实动画变体配置 同骨架地面约束过渡烘焙和 PIE 骨骼数值采样 结构化分段只创建临时表现演员 不生成图片或视频 原生编译及三项 Mass 自动化通过 17 项针对性离线检查通过 最终移动复查 2037 帧 详细契约与边界见 [BBBAnimationFinishMCP.md](Docs/BBBAnimationFinishMCP.md)

2026-10-23 新增原生 AimOffset 布局复用 加法层接入与父节点资产覆盖工具 先混合加法结果再与唯一基础姿势合成 避免姿势输出分接断链 角色后坐力采样改读 GetRecoilAngles 姿势驱动变量改为 WeaponPoseOffsetAngles 不再重建 AimIK 目标偏移入口 接入方式与验证边界见 [BBBAimOffsetMCP.md](Docs/BBBAimOffsetMCP.md) 配套 42 项离线回归与三项原生 AimIK 响应测试通过


2026-10-23 增加动画曲线原始数据与骨轨道摘要读取 原位名称迁移及同长动画完整曲线复制工具 蓝图名称引用通过项目编辑器库同步 不创建备份 UE5.8 编译通过 22 项离线测试通过 已保存 230 份自有资产改名及 50 份同源动作曲线同步 52 份基准与目标的骨轨道摘要保持不变 共用动画层严格编译通过

2026-10-23 例行效率优化：保存按最多128包分组读取、编译核验、批量重存与回读；参数一次返回最多16项字段问题；所有终态交付已完成结果；到期资产恢复按干员等级与原提交顺序参与调度。性能和干员目标可直接发现，启动默认60 FPS、Normal。验证通过98项独立提交隔离检查、87条发现语料和228个Python文件语法检查；现用服务沿原进程运行。

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

2026-10-20 新增指定FK骨骼参考旋转恢复入口，保持父级与其它控制器并核验实际正向求解；SMG03右拇指三节第0/1帧恢复并保存，最大角度误差0.00000342度。未运行PIE或额外测试。

2026-10-20 新增已有Rig控制器局部关键帧写入入口，支持带骨骼父级的FK，仅写明确控制器和帧并回读位置、旋转、缩放，不修改偏移或放宽手指平移检查。

2026-10-20 新增 `control_rig.process_dual_arm_body_pose(action=prepare_action)`，按正式制作源分阶段保存装备或换弹动作的完整源轨迹、双臂 IK 与逐节手指 FK；使用 UE5.8 生命周期绑定，避免重复 Transform 轨导致偏移减半。枪体与旧、新弹匣预览读取当前配置及原生通知时间；显隐预览只归制作 LS。Rifle01 装备51帧、换弹67帧原生全帧对照及实际挂接回读通过，最大位置差小于0.000257厘米。准备入口不写运行配置，不覆盖已进入人工编辑的序列；尚未执行人工结果应用，未启动PIE。见 [BBBManualActionAuthoringMCP.md](Docs/BBBManualActionAuthoringMCP.md)。

2026-10-21 统一小怪出生工具接入：展示入口改用 BBBMonsterSpawnDefinition 和正式统一生成处理器；资产入口明确十六个配置并保留导演调度。UE5.8 编译、生成器与导演八项自动化、Python 三项契约测试及 BBBTest 十种各一只实际追逐攻击抽样通过。按用户要求取消耗时渲染重跑与多机验收，不宣称完整联机验收。详见 Docs/BBBMonsterSpawningMCP.md。

2026-10-21 人工动作 inspect 增加正式源摘要、实际改键范围和小数帧原生曲线加Rig求值诊断，分开报告整数帧烘焙一致性与手调小数帧保留。Rifle01 四个左手子帧键在30 FPS成品中相差12.34至3.35厘米，而相邻整数帧误差小于0.000061厘米；原生回读通过，没有修改用户资产，不宣称穿模已修复。入口与结果见 [BBBManualActionAuthoringMCP.md](Docs/BBBManualActionAuthoringMCP.md)。

2026-10-21 人工动作 bake 新增现有左手子帧修正的连续审核烘焙：纯瞬态移除窄峰基线、右手空间人工差值、保留起止姿态的平滑连接与120 FPS骨轨输出。Rifle01 201个采样全部原始骨轨回读通过，四处原人工点最大实际预览误差3.70毫米，原LS/Rig的SHA不变；成品已打开供用户审核，运行引用未变，不宣称穿模视觉验收通过。详见 [BBBManualActionAuthoringMCP.md](Docs/BBBManualActionAuthoringMCP.md)。


2026-10-21：人工武器动作prepare_action自动准备原生Additive偏移段并锁定原段，bake直接官方导出实际序列，移除自定义阶段插值；Rifle01中性输出零差、左手1厘米偏移与右手稳定验证通过，Rifle02自动准备通过。详见Docs/BBBManualActionAuthoringMCP.md。


2026-10-21：人工装备换弹制作入口自动使用完整手臂预览，原位保留角色绑定及所有手调通道；Rifle01换弹关键帧摘要一致、网格替换前后原生骨轨零差，肘部控制保持。详见Docs/BBBManualActionAuthoringMCP.md。

### 2026-10-21 换弹左侧原通用动作恢复

人工动作prepare_action支持制作源显式left_reference，原生瞬态副本核验后只恢复左臂、手腕与手指通道，清除左侧叠加偏移，保留右侧及附件。applied标志使重复打开不覆盖新手调。Rifle02全67帧官方导出核对最大位置差0.000174厘米，其他通道摘要和非左侧骨轨不变，重复调用通过；未跑PIE。详见Docs/BBBManualActionAuthoringMCP.md。

### 2026-10-21 公共离散动作输入与型号输出分离

新增BBBCommonActionSources，公共目录制作源通过既有双臂入口capture/inspect/finalize管理。ManualAction统一schema=2，分开公共身体animation、本枪finger_animation、output_animation与显式source_time_scale；去除旧schema和left_reference分支。原LS实际引用公共AS，先瞬态验证再刷新身体Absolute，保留原生Additive、手指和附件键。18个公共底稿、14把武器映射、27份制作要求原生检查通过；Rifle01/02四条LS接入完成，Rifle02装备官方烘焙回读差0，Rifle03装备从空要求准备完成。当前继续编辑Rifle02换弹，未跑PIE；详细契约见Docs/BBBManualActionAuthoringMCP.md。


## 2026-10-21 干净Manny重定向公共动作

新增 Scripts/BBBActionRetargetTools.py，通过 control_rig.process_dual_arm_body_pose 的 *_RetargetActions.json.source 分派 capture/finalize/inspect。BBBNativeRetargetActions/schema1明确原始动作、原生RTG、网格、参考、输出和首尾帧窗口；write_paths必须等于全部输出。capture调用UE原生IKRetargetBatchOperation，校验非空op stack、精确目标和源摘要，拒绝覆盖未采纳输出。finalize只平滑明确首尾窗口并回读中段/首尾、保存摘要，inspect核对保存及轨迹。不解释人工Offset键，不产生备份或兼容跳转。

公共目录改按各baseline的finger_policy核验；新rifle装备/换弹保留源动画手指。ManualAction/schema2允许公共AS同时作为身体与手指来源，显式source_time_scale；准备时正确导入is_finger，并按本枪正式蒙太奇源验证弹匣预览，避免公共手指输入误当成本枪蒙太奇源。

实机静态验证：指定RTG生成两条新公共动作；原始输入不变，首尾最大位置误差0.00003305835cm，中段最大写入误差0.00009338207cm。目录18底稿/14武器/27制作要求通过；Rifle01/02四LS原生Additive空键、四成品与实际Sequencer导出误差0、正式蒙太奇读回正确、无PIE。入口prepare_action再次打开Rifle01装备第0帧。通用CurveSnapshot备份分支本轮未调用。


## 2026-10-21 现有装备指节异常修复

BBBActionRetargetTools在inspect中输出手指前段逐帧命名旋转、参考及骨架中性姿势；finalize支持正式源显式finger_repair.mode=bridge_hyperextended_distal_yaw和approval。该分支只原位修复装备非拇指02/03节超允许上限5度的连续Yaw异常段，用两侧现有安全帧连接，保持其他骨轨和关节Pitch/Roll、位置/缩放，不调用重定向。记录区间和摘要，重复调用核验当前摘要。

ManualAction的finger_repair_source通过prepare_action同步受影响源指节Absolute Rotation.Z键。写入前逐键与旧源比对，存在人工冲突即拒绝；回读并验证其他控制键及原生Offset摘要不变，再正常官方烘焙。实机：16轨266异常采样修复，Rifle01/02/03制作序列同步，Rifle01现有9个Offset通道保留，Rifle01/02成品与LS导出误差0、正式引用读回正确，换弹不变；未跑PIE、未重新重定向、未产生备份。


## 2026-10-21 动作制作控制器显示筛选

ManualAction正式源可用visible_controls显式限定视口控制器。prepare_action在原生Offset准备后同步Rig资产及当前Sequencer实例的shape_visible，核对精确可见集合，比较全部序列通道摘要以保证关键帧不变；不删除控制器、不改求解。Rifle01换弹实机回读只显示左手IK、左肘方向、左锁骨及15节左手指FK，共18个控制器；全部关键帧保存不变。无PIE、无备份、无临时资产。


## 2026-10-21 换弹右食指修复

finger_repair现归属RetargetActions每个jobs项，mode统一为bridge_hyperextended_finger_yaw，bones显式限定可修改骨轨；finalize逐动作核验或修复，sync按ManualAction.action匹配。正式源已迁移至唯一当前结构，不保留旧结构分支。inspect同时报告装备与换弹指节命名旋转及全轨迹最大Yaw。

实机检测换弹index_02_r在3–9、25–56帧反向上翘，峰值8.29799度；仅修这条骨轨39采样，修后最大Yaw为-0.33319度。其他骨轨、位置和缩放保持。Rifle01/02已准备换弹LS同步39个Rotation.Z源键，摘要验证其余控制键和Offset保留，Rifle01仍仅显示左侧控制器。无重新重定向、无PIE；当前左手编辑尚在进行，正式成品待用户完成后按既定流程统一烘焙，未将未完成左手编辑提前应用。


## 2026-10-21 复制Rifle01原生Offset关键帧

ManualAction正式源的offset_source_recipe显式指定同动作、同公共输入的源制作要求。prepare_action在目标已准备后，只复制唯一原生Additive层的通道默认值与关键帧，包括帧/子帧、值、插值模式、切线模式、切线权重模式及两侧切线/权重。源目标显示帧率与tick按有理数比较，段范围和通道集合必须一致。复制后完整回读对比，摘要证明其他层及武器/弹匣挂接轨道不变。结果记入offset_copy，后续打开直接保留用户继续修改，不自动重复覆盖。

用户明确只要求应用编辑键，禁止直接烘焙。已在当前上线步枪范围Rifle02、Rifle03的装备及换弹LS应用Rifle01的原生Offset；装备各73键/18带键通道，换弹各1950键/936带键通道（含源序列已有中性键）。Rifle03换弹先完成制作底稿准备。四条回读键值、时间、默认值和切线一致，底层与挂接不变，无正式AS烘焙、无运行引用修改、无PIE、无备份。窗口回到Rifle02装备供人工微调。

## 2026-10-21 Sequencer无效时间范围修复

prepare_action在恢复已有制作序列前检查view/work范围；只有NaN、无穷或倒置范围才按原播放区间及5%留白重建，正常缩放保持。修复保存并重开当前序列，比较全部通道摘要及播放区间，不改变动画内容。正式制作源timeline_ui_request=true可只执行范围修复并消费请求，不进入烘焙、源姿势同步或运行引用应用。

当前Rifle03换弹实机读取view结束为NaN，work正常；修复后view/work均为[-0.21666666666666667,2.35]秒。通道摘要及播放区间保持，保存后重开并求值成功。鼠标拖动由用户在前台确认，未运行PIE，未创建备份或临时资产。

## 2026-10-21 换弹11/33帧通知正式同步

ManualAction源的rifle_reload_timing是公共Rifle换弹时间约定（30 FPS，拔出11帧，插入33帧）。仅写源文件不会改变蒙太奇。先设置reload_timing_request=true，以prepare_action调用，write_paths精确列出DA实际配置的角色及武器换弹蒙太奇；该入口只同步通知，不切换编辑器，不写LS/Rig或用户控制键，完成后消费请求并记录reload_timing_applied。然后才以通常LS/Rig范围准备、烘焙和应用动作。

同步旧弹匣手持显示起点、枪体弹匣隐藏起止、新弹匣手持显示终点、装弹逻辑起点及出入音效；保留显示实例和实例上配置的变换、网格、速度参数。通过UE原生AddAnimationNotify(State)EventObject复用同一实例，核对事件数、实例身份、触发条件、过滤、服务端/跟随设置以及全部实际触发起止时间。不重建配置实例。生命周期、允许开火及其他未改轨道的时间保持；装弹逻辑持续时间保持。角色映射目前要求单片段、从0开始、1倍播放；枪体片段可不同速度，通知按蒙太奇时间修改，不能再乘枪体动画速度。

实际核对并修复Rifle01/02插入音效36→33帧、拔出音效→11帧；Rifle03双侧显示、装弹和音效10/36→11/33；当前SMG01双侧同样完成11/33（枪体片段速度0.454545，蒙太奇与角色仍为2.2秒）。四把枪均回读1.10000002384秒插入；通知原UObject实例保持，人工控制键未写。仅Rifle03已完成换弹及SMG01已确认参考装备执行官方直接烘焙、替换并显式保存正式蒙太奇，导出骨轨位置差0；SMG01换弹仍供人工编辑，未提前应用。前台保持LS_SMG01_CharacterReload。

其余型号仅核对、未批量改写：SMG02/03、LMG03、Sniper02/04仍需在各自制作轮执行此同步。LMG01角色旧动作2.833333秒与公共2.2秒不一致，必须先完成其正式制作时间映射，不能盲套秒数。Shotgun03使用弹壳/弹药手持表现，缺少普通旧/新弹匣对，不能套普通弹匣通知；该入口会拒绝。手枪、Minigun与逐发霰弹枪未写。当前SMG01制作预览的弹匣生命周期来自同步前的通知，需在用户编辑结束后的交接阶段仅同步显示时间，不重建或覆盖人工控制轨。

无PIE、无备份或兼容资产。本轮未清理Rifle03/SMG01历史制作资产，避免在用户编辑期间重现旧包删除故障；仅已完成动作的历史清理仍待独立收尾。

## 2026-10-22 公共换弹帧的时间比例

reload_timing_request使用time_space=common_source时，通知秒数按source_time_scale反向映射到型号制作/蒙太奇时间。LMG01原角色换弹2.833333秒、公共输入2.2秒，比例0.7764706；保持原有换弹时长、曲线/手指元数据输入采用当前本枪CharacterReload_Grip，公共身体动作按该比例采样。公共第11/33帧分别映射为蒙太奇0.472222/1.416667秒（30 FPS显示帧14.1667/42.5）。不是把33直接当成本枪显示帧。两侧通知保留原实例，枪体自身0.7764706播放速度保持，当前正式换弹引用仍待用户编辑结束后应用。LMG01装备已官方烘焙、替换保存；无PIE、无备份。

## 2026-10-22 LMG01正确Shotgun换弹基准（取代前述LMG01的Rifle时间映射）

用户明确指定原MM_Shotgun_Reload并要求迁入Used及首尾对齐。已原生迁移至/Game/_Project/Characters/BBBC_UA/Animation/UsedAnimation/shotgun/MM_Shotgun_Reload，旧包、重定向器及旧引用清零。唯一正式公共输入保留原名，不另建重复底稿；本轮误建的AS_Shotgun_ReloadFull_Base已核对当前哈希及无引用后原生删除。此前为这次派生源临时修改的工具源码已恢复，不保留额外入口或兼容分支。

正式Source/Animation/Shotgun_Reload_Alignment_RetargetActions.json.source记录原位首尾对齐（不重新重定向）：以MM_Rifle_Idle_Hipfire第0秒为基准，入口0–6帧、出口71–81帧，末尾4帧稳定。完整2.833333秒/86采样保持；6–71帧全部原骨轨位置和旋转验证保留，中段写入误差0.00001077cm，首尾最大误差0.00003306cm。检查结果original_source_unchanged=false是因为source与animation明确为同一个原位修改资产，不代表中段改变。四条IK/握姿抑制曲线按正式首尾窗口重建。

CommonActionBaselines中的shotgun.reload_full唯一引用上述MM资产（身体及手指），仅LMG01.reload映射改用该条目。LMG01制作源animation=finger_animation=上述Used/MM资产，source_time_scale=1；旧Rifle通知约定已移除，恢复原LMG01拔出0.3秒/第9帧、插入1.5秒/第45帧，原通知实例、配置及其它时序保持。修正前只读检查原生Additive层无人工关键帧，故清除错误底稿并原位重建LS；已重新打开LS_LMG01_CharacterReload第0帧及原生Offset层。新底稿全帧原姿势回读误差0.000106cm；正式运行换弹仍待用户编辑完成后烘焙应用。装备已应用不变。未跑PIE，无备份，无临时文件遗留。

## 2026-10-22 Shotgun换弹末节上翻修复

用户要求原位修复当前UsedAnimation/shotgun/MM_Shotgun_Reload。全轨检测30指节后，按既有中性伸展上限及超过5度规则，限定pinky_03_l、ring_03_l。小指异常区间4–7/21–26/42–45/66–69共18采样；无名指6–11/17–29/42–47/65–70共31采样，峰值43.64793度。仅用两侧安全采样平滑连接异常局部Yaw，位置、缩放、Pitch/Roll及其余骨轨回读保持；未重定向。

修后全轨最大Yaw小指-0.11819度，无名指11.27020度，分别不超过0/12.89972度上限。首尾腕/前臂与参考误差保持原值。正式Alignment源记录修复前后摘要及49个修改采样，catalog更新正式摘要；LMG01通过sync_finger_repair仅同步Absolute层49个Rotation.Z键，逐键旧值核验并摘要确认其他控制键与人工Offset不变。当前序列已保存并刷新至第0帧；未烘焙未完成的人工作品、未改正式运行引用、无PIE、无备份或临时资产。

## 2026-10-22 当前序列全部反向手指：基础轨与无键默认偏移同时核验

inspect_manual增加全部30指节的源/实际Sequencer导出最大Yaw和非零未打键手指Additive默认值报告。实际LMG01发现42个未打键手指旋转默认值作用于全段，左无名指第二节额外Yaw43.935度，使源最大-8.117度在最终序列变成+35.818度。此前仅修源动画不足以修复当前结果。最初尝试FK全局/局部空间互换没有消除此误差，已恢复原图全部GlobalSpace及生成方式，不保留这项无效变更。

ManualAction源可显式reset_unkeyed_finger_offsets_request=true，通过普通prepare_action作用于当前序列。仅清零没有任何关键帧的fk_*旋转默认值；记录全部原值，并核对所有关键帧的时间/子帧/值以及其他通道默认值不变。当前左手IK位置7/8/8键、旋转各8键、左肘各2键均保持，不清除手动控制轨，不改Rig求解逻辑。完成后消费请求，记录finger_offset_repair。

基础动画另以既有bridge_hyperextended_finger_yaw规则扩查双手24个非拇指指节。显式extension_limit_basis=reference_pose时上限采用max(0,正确参考Yaw)，minimum_excess_degrees=0.1，不再将骨架中性姿势的过伸容差当作最终可接受范围。新增修复左食指末节17采样、左中指末节19、左无名指末节40、右食指末节56，共132。只修Yaw，保持其余骨轨、位置/缩放和首尾参考。拇指全部检查，保留正常对掌角度，不把其旋转正号等同于异常。

源修复后通过原生finger同步仅写上述Absolute Rotation.Z键，其他键与人工Offset摘要不变。最终120 FPS官方瞬态导出341采样：42个无键默认偏移已清零，左侧四指全部指节最大Yaw均小于0，右食指末节最大1.574482度与正式参考一致；源与序列手指位置差0，旋转四元数点积最小0.999999938。当前LS_LMG01_CharacterReload已保存并刷新，未提前烘焙用户尚未完成的正式动画、未运行PIE、无备份或临时资产。

## 2026-10-22 LMG03也使用正式Shotgun完整换弹

用户明确指定LMG03换弹同样使用已迁移/基准对齐/完整指节修复的UsedAnimation/shotgun/MM_Shotgun_Reload。修改前只读确认当前LMG03换弹Additive无人工关键帧且没有非零手指默认偏移，故原位重建错误Rifle底稿。catalog中仅LMG03.reload改为shotgun.reload_full，身体与手指均引用唯一MM_Shotgun_Reload，原速2.833333秒/86采样。没有新增或复制公共资产。LS已保存、打开第0帧，原生Offset已选中。

LMG03原枪体片段2.2秒，通过现有retime_single_action_montage将枪体蒙太奇调整至2.833333秒、DefaultSlot保持、片段速度0.7764706，制作枪体预览据此同步。普通Rifle的11/33约定已从本枪制作源移除；两侧弹匣通知使用Shotgun9/45帧及原实例，预览已同步。手调完成后须使用正式配置蒙太奇入口把角色片段改为新2.833333秒（当前运行片段仍为旧2.2秒，不能使用只允许等长的替换接口），并同步换弹生命周期、阻火结束、允许开火至2.8秒。此待办已明确记录本枪源runtime_apply_requirement，未提前应用未完成的角色手调。

真实prepare全帧源姿势位置误差0.000106cm，源摘要为5be6e85aacbb8cbbb72cffb513a956e0bdc204376f4ca9bd800e791ebe881f77；指节继承同一个已修复Shotgun输入。无PIE、无备份和临时资产。

## 2026-10-22 LMG03装入弹匣改为第47帧并完成应用

用户确认手调完成，明确本枪插入改为47帧。LMG03普通弹匣通知范围本轮为9/47帧（30 FPS）；角色新弹匣结束、武器显隐结束、装弹逻辑开始和插入音效均原实例同步到1.5666667秒，出弹0.3秒保持。继承Shotgun完整2.833333秒而非旧2.2秒，生命周期与阻火结束、允许开火统一2.8秒/84帧。手指使用已修复的唯一公共Shotgun基准。

新增显式ManualAction apply_baked_request：prepare_action以唯一角色蒙太奇write_paths应用已有成功bake_result，只改当前单片段的动画引用、源起止与1倍速度，按烘焙输出更新时长，不重建蒙太奇或重设混合/通知。实际LMG03从旧2.2秒改为新2.833333秒，UpperBody保持，原blend_in0.25和blend_out0.4回读保持。正式动画341采样、官方直接烘焙全轨位置差0，蒙太奇保存与片段引用回读正确。普通同步入口支持显式reload_end_seconds联动生命周期/阻火/允许开火尾点，其余通知和实例参数保持。

新增preview_timing_request：以通常LS/Rig/Preview范围prepare_action，只更新现有OldMagazine/NewMagazine生命周期及枪体显隐预览，保留绑定和全部人工控制/附件Transform键。LMG03旧弹匣[9,17)、新弹匣[25,47)显示帧；全部控制及Transform通道摘要保持，最终当前LS与已应用AS再次官方导出比对误差0，existing_output_matches_preview=true。制作源runtime_applied=true，时长交接待办标为完成。源保留magazine_timing=9/47，不扩大修改其他型号。未运行PIE，无备份、无兼容跳转或临时资产。

## 2026-10-22 Sniper02正式右腕角度的制作预览

用户要求当前Sniper02装备序列应用已手调的右腕角度。真实读取DA的right_hand_grip_rotation_offset，其四元数为[0.1193930358,0.1331199110,-0.1653194875,0.9698937535]，与握姿制作源校准一致。运行Base对hand_r施加ParentBoneSpace加法旋转，因此不能将同一角度直接烘焙进原动作再由运行时重复施加。

ManualAction可显式runtime_right_wrist_preview=true。prepare在当前Rig已有IK求解及ik_hand_r拷贝之后、手指FK之前，读取hand_r局部变换，使用RigVM QuaternionMul按D*LocalRotation写回局部旋转，保持局部位置缩放及上臂/前臂求解。未改控制器键、DA、武器挂接或公共动作。LS保存BBB_RuntimeRightWristPreview四元数标签；原生_export在瞬态动画中逆乘D以还原raw hand_r旋转，正式运行再由既有右腕节点应用一次。该标签是明确的运行预览语义，不是旧资产兼容。当前Sniper02装备与后续换弹制作源均启用，其他型号未批量写入。

初始准备阶段复用含该预览节点的Rig时暂时关闭其Weight；重建LS清除预览标签，在manual_edit_ready阶段恢复Weight1并写入当前实际DA角度。重复打开同一角度及Weight1时不累计添加节点或修正。当前装备实际生效，所有通道键摘要保持；前后官方120 FPS瞬态导出、扣除运行预览D后的全骨轨位置误差0.0000992cm，旋转/缩放通过原有比较；重复prepare再次通过。未运行PIE、未烘焙未完成的用户手调、未改正式运行引用，无备份与临时资产。

## 2026-10-22 霰弹枪分段换弹只对齐外侧端点

BBBNativeRetargetActions 的每项 entry_frames、exit_frames 可显式为 null；至少指定一侧。单侧入口复用原 finalize，仍校验原资产摘要、帧数和窗口，使用最短弧旋转平滑，只核对所指定端点与参考一致；另一端及窗口外全部骨轨位置、旋转、缩放回读保持。四条 IK/握姿抑制曲线在入口结束后保持禁用，在出口对齐完成时恢复，末尾稳定段保持零。已对齐资产重复调用只核验摘要，不重复累加。

Shotgun01 公共 AS_Shotgun_ReloadStart_Base 仅入口0–6帧对齐 MM_Rifle_Idle_Hipfire，6–25帧保留；AS_Shotgun_ReloadEnd_Base 仅出口3–13帧对齐，0–3帧及装填接口保留，最后4帧稳定。正式源为角色 Source/Animation/Shotgun_PhasedReload_Alignment_RetargetActions.json.source，catalog 采纳两条新摘要并保存参考及制作源。单发 AS_Shotgun_ReloadInsert_Base 未写入，catalog 全部19基准/14武器/27制作要求通过。双臂外侧端点最大差0.00003494cm，开始→装填、循环、装填→结束最大差0.00005251cm，旋转最大0.000108度；源输出长度和骨轨数量保持。专属运行成品仍待各枪人工制作后烘焙应用，本轮未切换其运行引用。

手枪保持自己的完整动画组，已打开 LS_Pistol_CloseHold_BodyPose 供用户修改第0帧双臂基准；当前挂接与 DA 一致。原生纯瞬态 Sequencer 导出与正式 AS_Pistol_01_HandGrip 第0帧比较无差异，未改控制键或 Rig。临时播放器直接读取曾返回未刷新骨骼缓存，不作为预览姿势错误或 IK 权重失效的证据；实际图使用直接双臂求解，不受该旧权重字段控制。用户确认新基准前不重烘整组手枪动作，不重跑已有 result 的旧任务。未运行PIE，无备份、兼容包或重新重定向。

## 2026-10-22 逐发换弹原生Offset制作

ManualAction/schema2 增加 reload_start、reload_insert、reload_end，继续使用 process_dual_arm_body_pose 的原有 prepare_action/bake/inspect 入口。ACTION_MONTAGE_FIELDS 明确对应角色及枪体配置字段：开始/结束读取各自 start/end 蒙太奇，单发装入读取 reload_montage；应用成品使用同一字段映射，不猜测资产名称。公共目录按相同阶段键验证源和时长，LS、Rig及必要枪体预览AS仍归本型号原有目录。普通reload的旧/新弹匣完整性检查保持，三段逐发换弹不套普通11/33帧约定。

预览从真实 BBBCharacterHeldObjectDisplayAnimNotifyState 读取 ObjectMesh、HandBoneName、HandObjectTransform 及原生起止时间，在 held_objects 中记录并建立可选择附件；与 magazines 分开保存。实际挂接校验覆盖手持物体，不改运行通知实例或武器代码。三段均继承显式 runtime_right_wrist_preview，原生导出扣除运行右腕旋转以避免重复应用。尚未完成的阶段只保留正式制作要求，不提前烘焙。

实机完成Shotgun01装备官方120 FPS烘焙并保存正式蒙太奇引用，骨轨误差0。新 LS_Shotgun01_CharacterReloadStart 从已对齐的公共开始基准准备26采样，原生Offset已选中，右腕预览扣除后的导出误差小于0.00012cm，全部控制键摘要保持；HeldObject_0在30 FPS第12–24帧显示，变换来自原通知，附件实际回读通过。枪体存在显隐状态，明确保留 ReloadStart_AuthoringPreview 作为有效制作输入。开始动作尚待用户手调，未应用运行成品；未运行PIE，无备份或旧路径兼容。

## 2026-10-22 开始换弹末姿衔接原生装填循环

reload_insert 的正式ManualAction可显式指定 reload_start_recipe，要求同武器、已准备的reload_start源及唯一原生Offset层。match_reload_insert_offset用原生通道evaluate_keys在Start末帧求值，将非中性偏移作为循环整段常量（0帧和末帧相同线性键）写入目标Offset；保留原装填底层轨迹和附件，不自行解释人工中间阶段。UE原生Additive的缩放通道中性值同样为0，只有Weight为1。已有非中性目标人工编辑会拒绝覆盖；reload_insert_handoff记录成功结果后再次准备不重复拷贝。

先在纯瞬态副本上试写并通过官方120 FPS导出，核对双肩、肘、腕和30指节的循环首尾与Start末帧，再写正式LS；比较源完整通道摘要及目标非Offset摘要，保证Start用户键、底层和附件保持。未提前应用循环成品。瞬态副本统一通过_copy_sequence保留BBB_RuntimeRightWristPreview标签，防止公共底轨验证和探针遗漏右腕逆补偿；副本使用不与导出目标冲突的名称。原生Offset段已保存但制作源尚未保存的中断恢复会补齐阶段事实，再执行实际偏移探针，不重建段或覆盖关键帧。导出缺少唯一角色绑定时明确报告序列与网格路径。

Shotgun01人工Start官方烘焙101采样、0.833333秒、全轨误差0，原角色开始蒙太奇引用已保存。Insert接收13个末帧非中性通道：左手IK位置/旋转和左拇指逐节旋转；真实循环两端对Start末帧最大位置差0.000054994cm、旋转差0.037144度，底层和附件摘要保持，Start通道摘要f08453c826632bc79a63c9c24908c94fe6dd7155374e8dd1c21fa22ddff2ee8c保持。LS_Shotgun01_CharacterReloadInsert已打开第0帧及原生Offset层供用户审核，runtime_applied=false；未改通知时间、未跑PIE，无备份或临时Content资产。



## 2026-10-22 循环装填应用与结束段原生衔接

phase_handoff_recipe及phase_handoff统一表达分段换弹的相邻制作源和成功事实，仅接受同武器Start→Insert、Insert→End。既有Insert源已原位迁移字段，不保留旧字段兼容。Insert继承整段常量；End显式handoff_release_frames=[3,13]，原生线性键在0/3帧保持继承值，13/末帧归零。用户可直接在Sequencer编辑，未添加自定义插值算法。成功记录存在时不重复覆盖；非中性人工目标编辑仍拒绝覆盖。

结束段先在瞬态副本核验入口与Insert末帧一致、出口与中性Offset目标末帧一致，再写正式LS，保持源键、非Offset底层和附件摘要。中性与实际输出统一120 FPS官方导出比较，避免以初始化导出最后一帧作为正式末帧。Shotgun01 Insert已按用户批准烘焙45采样/0.366666675秒，全轨误差0，角色ReloadInsert蒙太奇引用保存且原混合设置保留。End继承13通道，入口/出口最大位置差0.000041657cm、角差0.040551度，原生Offset探针左手0.999999cm、右手0；正式LS已打开供手调，结束段尚未应用运行成品。未改通知、配置或运行IK；未跑PIE，无备份和兼容资产。

## 2026-10-22 一次式手持弹药换弹预览

普通reload预览按真实通知接受完整OldMagazine/NewMagazine组合，或无弹匣通知且存在有效HeldObject的换弹；缺少表现输入和仅一侧弹匣通知仍拒绝。不再将一次换弹等同于可拆卸弹匣换弹，不新增配置开关。Shotgun03实际两条手持弹药通知通过现有物体网格、骨骼、变换和生命周期读取，原生Offset制作序列准备完成67帧，公共身体预览误差0.000335cm以内，右腕实际修正预览保留；未改通知或运行玩法，未运行PIE。装备已官方直接烘焙201采样、1.666667秒、全轨误差0并保存角色装备蒙太奇引用。

## 2026-10-22 原生帧段拼接通用单次装弹

BBBNativeRetargetActions的capture可使用每个job的source_frame_ranges（闭区间）直接从同骨架原动作采样，不经过IK重定向；按源顺序拼接，新增明确输出，拒绝原位覆盖和非连续接缝。保存前逐骨核验接缝组件空间位置/角度、全部输出位置/旋转/缩放以及源摘要。输出去除原通知和曲线，之后由既有finalize建立明确首尾窗口及抑制曲线；已有成功输出只回读核验，不重复裁切或覆盖。

用户明确纠正Shotgun03的原动作必须是Shotgun01来源BigLocomotionPack的anim_shotgun_aim_reload，而非Lyra MM_Shotgun_Reload。原完整73采样/2.4秒资产已原生迁入UsedAnimation/shotgun，旧路径和重定向器清零。新增AS_Shotgun_ReloadSingle_Base取原0–25及55–72帧，44采样/1.433333秒，接缝位置差0、最大旋转差0.042760度，全轨位置写入误差0，完整源保留。入口0–6及出口29–39对齐Rifle参考，最后4帧稳定，首尾最大位置误差0.000033059cm。Shotgun03制作源/catalog已切换，正式LS原位重建并打开原生Offset；公共身体预览误差0.000139cm以内。两发手持弹药的原网格和局部变换保留，角色通知显示区间调整到首次装入的0.4–0.8秒；角色运行动画尚待人工完成后烘焙引用，枪体装入/结束通知同步留待该次应用完成。未运行PIE，无临时Content资产、备份或兼容入口。

## 2026-10-22 单把动作固定右腕显示角度

ManualAction显式freeze_right_wrist_rotation_request通过prepare_action将当前第0帧显示右腕方向保持到整段。仅写hand_r_ik_ctrl的三个原生Offset旋转通道，保留底轨、位置缩放、左手和附件全部键。计算包含现有右腕预览旋转的父空间补偿，原生导出回读实际手骨角度和位置；在瞬态候选通过全帧检查后写正式LS。请求成功消费，不在每次准备时重新锁定用户编辑；输出仍是可直接编辑的原生键，无运行时代码链条和自定义时间插值。

Shotgun03当前44帧换弹已执行，原生导出显示右腕方向固定检查通过（误差上限0.1度），左右腕及左臂原位置保持（上限0.02cm），非目标通道时间/值/默认值摘要保持；具体实际误差保存在正式制作源right_wrist_rotation_hold。没有改公共Single底稿或武器DA，尚未烘焙应用，未运行PIE。无备份、兼容资产或本次临时Content输出。

## 2026-10-22 单次装弹成品应用与角色/枪体通知同步

既有sync_reload_timing支持显式single_reload_application_timing：要求已应用的正式烘焙成品，按held_object_frames/load_frame和成品长度同步一次式手持弹药换弹。保持真实通知实例、全部可编辑属性及事件元数据，保留通知数量与轨道归属；装入结算仍恰好一次。枪体唯一完整片段通过播放速率同步成品总长，其余表现事件按原蒙太奇归一化时间缩放，枪体显隐结束/装弹音与实际装入时间一致。阻止开火与允许开火安排在结束前一显示帧，生命周期到成品结束；不增加玩法代码。普通弹匣流程保持原有11/33等显式时序，单次手持弹药不套旧新弹匣完整性要求。读取并核验保存后通知原生时间、实例身份、元数据以及两侧实际蒙太奇长度。

Shotgun03用户确认成品已官方120 FPS烘焙173采样/1.433333278秒，全轨误差0；UpperBody引用当前ManualEdit、原混合配置保留。枪体DefaultSlot保持本枪原1秒动作，速率0.697674453，总长同为1.433333278秒。两发手持弹药0.4–0.8秒；唯一LoadAmmo通知0.8–0.833333秒，装入音0.8秒；允许开火1.4秒，Lifecycle结束1.433333秒。九个枪体通知及两个角色通知实例保留，全部时间范围回读通过。正式制作源runtime_applied=true，weapon_timing_sync_pending=false。未改武器DA、公共底稿或手调序列键，未运行PIE；无备份、兼容资产和本次临时Content输出。

## 2026-10-22 经明确授权共享开火底稿挂接平移

当用户明确要求两套姿势共用开火底稿新挂接时，可在原HandGrip制作源设置share_fire_attachment_request，再由原manual_apply_fire入口分保存边界推进。读取FireGrip附件Transform通道第0帧实际值，不依赖切换序列后尚未刷新的Actor或骨骼缓存；保留开火所有通道摘要。将新平移写回未开火LS，保持已应用未开火AS和指骨不重烘，按真实WeaponGrip_R插槽旋转补偿LeftHandIKOffset以保持手位，写正式共用标定，更新基准签名后重新打开FireGrip。最后一次调用仍执行完整非指骨、冻结右臂、挂接和烘焙回读检查。请求消费后不会自动接纳后续编辑；此入口仅允许平移，挂接旋转/缩放变化明确要求回未开火阶段，不降低原默认检查。

Shotgun01用户主动调整挂接后明确选择两者共用。正式SpawnOffset平移回读[-8.772383773,3.707190574,-3.933614135]cm；左手IK补偿为[7.207152215,-2.846411012,-9.833188199]cm，右腕和左手IK旋转保持。新挂接及开火指骨成品应用成功，rightArmPreserved=true；原FireGrip通道摘要在共享步骤保持。已打开Shotgun03未开火LS继续人工流程，未运行PIE，无备份或兼容资产。

## 2026-10-22 原位刷新枪体预览动画

ManualAction制作源可显式设置refresh_weapon_animation_request，由既有prepare_action读取当前DA的角色/枪体蒙太奇及实际播放速率，复用_weapon_preview_animation把最新枪体骨轨和实际显隐区间写入本型号正式AuthoringPreview，并替换唯一有内容的Weapon动画轨；空动画轨不参与唯一性计数。刷新前后全部控制与Transform通道摘要一致，不重建绑定、不清空人工Offset或附件位置。消费请求后继续原生Offset准备并打开第0帧。

Rifle02运行枪体弹匣骨轨已清理，但LS仍使用旧AuthoringPreview，本轮已刷新。预览Magazine_joint全段位置保持安装姿势，11–33帧仅使用缩放隐藏，33帧恢复；骨轨长度和每帧显隐缩放由原生回读核对。LS刷新及后续准备成功、dirty为空，人工控制键/附件摘要保持。未重新烘焙角色成品、未运行PIE，无备份或兼容资产。

## 2026-10-22 弹匣预览显隐帧边界

枪体AuthoringPreview的显隐窗口改为源采样帧闭开区间，以ceil(seconds*fps-0.0001)转换开始/结束，和附件生命周期采用相同的浮点帧对齐语义。避免通知11/30秒存储为0.3666666746而第11帧采样为0.3666666667时漏隐藏。保存制作源weapon_preview_frame_boundaries，来自输出骨轨实际缩放回读。Rifle02实测10帧scale=(1,1,1)、11与32帧=(0,0,0)、33帧=(1,1,1)，现有控制键和Transform摘要保持，正式通知时间未改。未运行PIE，无备份或兼容资产。

2026-10-22：set_sequence_spawn_range 在出现帧之前显式写入隐藏键，避免布尔通道将首个 True 反向延伸到序列开头；返回 spawnKeys 供核验。LMG01 换弹旧弹匣采用 0=false、11=true、20=false，新弹匣采用 0=false、30=true、40=false。

2026-10-23：修复 ManualAction 时间轴范围修复不彻底的问题。repair_timeline_range 先通过 AssetEditorSubsystem.close_all_editors_for_asset 关闭目标的完整资产编辑器，再重设有限视图/工作范围、保存并重新打开；仅 close_level_sequence 不能销毁原 Sequencer 的异常窗口状态。结果新增 closed_asset_editors，原有控制通道摘要与播放区间不变检查保留。两项专项回归通过；LMG01 旧换弹 LS 实际关闭、磁盘重载、重开后范围有限，再次关闭重开后鼠标拖至第32帧正常。本次未完成整个 UE 进程重启验证（共享宿主有并行资产迁移，shutdown_host 返回 HOST_BUSY）；不将资产重载等同于进程重启。UE5.8 的 MovieScene.h 将 ViewStart/ViewEnd/WorkStart/WorkEnd 标为 Transient，因此保存资产后的即时范围回读不能替代窗口重开验收。

2026-10-23：ManualAction prepare_action 支持显式 native_offset_request，只为已有制作序列建立或选中原生 Additive Offset 段并锁定基础段；消费请求后立即返回，不刷新附件、不改公共底稿、不应用运行时动作。LMG01 的 LS_BBB_LMG_01_CharacterReload_Grip 已实际建立两段：基础及原生 Offset；零偏移导出位置差0cm，瞬态副本左手1cm探针位移1.000004707cm、右手0cm。正式层保持零偏移，原基础键保持。

### 骨骼网格明确导入缩放（2026-10-23）

`skeletal_import.reimport_skeletal_mesh` 新增 `import_uniform_scale`，为相对 FBX 源文件的有限正数。重导入前同步已有 FBX 导入数据，临时关闭 Interchange FBX 接管并在结束时恢复；保存前核验实际 FBX 导入缩放。保留已有骨架和按槽名匹配的材质，不导入动画、材质、纹理或物理资产。

Sniper04 已通过原位 FBX 重导入保存为 0.9，回读为 0.899999976；材质仍为 MI_Modern_Weapons_Sniper_04，骨架及物理资产引用保留，已打开 LS_Sniper_04_HandGrip。此次未运行 PIE。验证中确认仅传 FbxImportUI 的缩放不足以覆盖已有 FBX 设置，因此工具同时更新已有导入数据并检查实际值。

### 明确同步未开火新握姿至开火底稿（2026-10-23）

用户明确要求同步后，可在未开火制作源设置 `rebase_fire_request=true`，通过 `manual_prepare_fire` 消费请求。入口先确认当前未开火结果已应用，再按正式 AS 同步开火骨轨，保留已有开火右食指三节局部姿势；重建原开火 Rig 的静态编辑基准，更新共同挂接和基准签名。随后仍需 `manual_apply_fire` 完成非指骨、冻结右臂、共同挂接及烘焙回读检查。没有请求时旧基准保护保持。

Sniper04 实际完成未开火应用、开火新基准同步及开火应用；右臂冻结和烘焙回读通过。两套共用新挂接，装备制作 LS 的 Weapon 预览挂接及制作源已同步；已打开原生 Offset 装备序列第0帧，保留已有装备编辑键，未烘焙装备动作、未运行 PIE。

### 动作首尾同步已应用握姿（2026-10-23）

ManualAction 制作源可显式设置 `grip_endpoints_request`，包含同型号正式握姿 `animation` 和四个显示帧 `frames=[起帧,离手过渡结束,回握过渡开始,末帧]`。既有 `prepare_action` 入口只在原生 Additive 层写左手 IK 与左手指 FK 的首尾修正，保留中段关键帧、身体底轨及附件轨道。首尾手掌目标按参考握姿相对右手的完整变换求得，包含显式启用的运行右腕预览；过渡由 UE 原生 AUTO 关键帧曲线完成。正式修改前先在瞬态候选中用官方 Sequencer 导出核验手掌与全部左指局部角度，不创建备份资产。请求成功后消费，后续打开不会重复覆盖。

占用范围为目标 LS；启用 `runtime_right_wrist_preview` 时同时列入原 Rig。Sniper04 以当前 AS_Sniper_04_HandGrip 修正 0/6/60/66 帧范围，首尾位置最大误差 0.000032915cm、旋转最大误差 0.04047度。正式换弹重新烘焙265采样、2.2秒，与实际序列导出误差0，已应用原角色换弹蒙太奇并保留原混合设置；窗口留在 LS_Sniper04_CharacterReload。未运行 PIE。

### 换弹实际编辑器预览核验（2026-10-23）

ManualAction 明确设置 `inspect_editor_grip_request=true` 后，原 `prepare_action` 入口读取当前已经打开的编辑器绑定实例、组件世界骨骼、附件局部变换和 Rig 手骨。只读取当前 Sequencer 实例，不创建第二播放器、不在采样时重新求值；要求 LS 已打开并给编辑器完成一轮正常求值。结果返回实际 Root_joint 缩放，避免仅用经过重定向的 AnimPose 数据判断枪体动画尺寸。请求在读取后消费。

Sniper04 定位出两个实际预览问题：临时播放器结束后共享预览组件与 Rig 状态不一致，需关闭实际资产编辑页后重开；枪体换弹根骨原始缩放仍是1.0，而重导入网格参考根骨为0.9，AnimPose 重定向采样会掩盖这种原始骨轨差异。已将正式 ANI_BBB_Sniper_04_Reload 和正式 AuthoringPreview 的67个根骨采样统一为实际网格参考根骨，其他骨轨及显隐不变。重开后直接读取编辑器组件，根骨缩放0.899999976，左手组件与Rig位置一致，左手首帧[-8.712429,40.746600,143.908958]cm与已确认握姿一致。只核验前台组件及骨轨，未运行PIE；窗口留在换弹第0帧。

### 开火枪体原始根轨缩放核验（2026-10-23）

`inspect_editor_grip_request` 可为含 `root_tracks` 数组的对象，明确列出同型号 Animation/Sequence 动画；原入口同时返回原始首骨轨各采样的位置、四元数和缩放，不经过 AnimPose 重定向。便于保留位置和旋转，仅用既有 replace_animation_bone_tracks 改写必要缩放。

Sniper04 正式 equipment_fire_montage 指向 AM_BBB_Sniper_04_Fire，其唯一序列 ANI_BBB_Sniper_04_Fire 的13个原始根采样缩放均为1.0，与当前网格参考根0.9不一致。已原位将这13个采样的缩放统一为实际网格参考根[0.899999976,0.899999857,0.899999857]；回读全部13采样一致。保留根骨位置和旋转方向，其余枪机骨轨、通知、蒙太奇引用及角色握姿未改。未运行PIE。

### 逐发换弹开始只修入口握姿（2026-10-23）

`grip_endpoints_request.frames` 支持两帧 `[0,入口过渡结束]`，只对齐开始姿势，不把逐发换弹开始段的末帧改回握枪，保留装填阶段衔接。四帧首尾窗口继续使用原契约。`finger_sides` 显式指定 l/r，默认仍仅左手；双侧时使用同一正式握姿的局部指骨旋转。仍通过原生 Additive AUTO 键过渡，候选先由官方 Sequencer 导出并核验，未通过不写正式序列。

Shotgun01 换弹开始按已应用 AS_Shotgun_01_HandGrip 修正入口0–6帧、双手指骨；入口手掌位置误差0.000028325cm、指骨及手腕最大旋转误差0.03544度。保留第6帧后的原编辑和末帧装填衔接，完整人物预览继续使用 Sk_CombinedMesh。此次修改制作LS，未提前烘焙角色运行动画，未运行PIE。

可显式提供 `grip_recipe_path`，限定同型号、已应用且动画引用一致的人工握姿制作源；掌间完整变换及指骨旋转直接采用已确认人工 solution，避免 AnimPose 重定向后姿势替代人工标定。最终 Shotgun01 入口候选位置误差0.000030595cm、最大旋转误差0.03536度；重开后直接回读编辑器当前帧为0、角色组件与Rig一致。仅修改当前制作序列，未烘焙运行成品。编辑器曾发生Slate崩溃，已恢复前台编辑器后重新核验保存结果。

### 人工左臂稀疏关键姿势连续化与审核烘焙（2026-10-23）

ManualAction 的 `smooth_left_request` 由既有 prepare_action 执行。apply=false 返回关键点、插值类型和旋转跳变检查；apply=true 通过 UE SMART_AUTO 原生键重建左侧位置/旋转切线。include_base 可纳入原绝对层。consolidate 明确采纳当前手部人工关键点为锚点，在原帧号及子帧上求原绝对层与叠加层总值，将左手、左肘、左锁骨和实际存在的对应左臂源控制器合并为稀疏原生叠加键；常量部分仍在原绝对层。不引入自定义时间插值，不重建绑定。核验每个人工锚点的控制总变换保持，右侧、身体其余通道和附件轨道不变；以120 FPS官方导出对比腕部及肘部轨迹。

Shotgun01 ReloadStart 现有人工锚点含6.535、11.4175、16.845、20.6325、25.97625等小数帧。仅切换自动切线不能消除底稿与偏移叠加产生的中间突变，因此按人工关键姿势合并左侧运动后再用UE原生曲线连接。最初/最终手腕峰值加速度90614.89/11218.66 cm/s2，左肘39149.05/24809.39 cm/s2；关键姿势控制总值回读通过。结果已烘焙为 ANI_BBB_Shotgun_01_CharacterReloadStart_Smooth 独立审核动画，未改原运行蒙太奇引用。

bake 可显式启用 preserve_authored_end，若人工叠加键晚于源动画末采样，在纯瞬态输入中保持源末姿势延长到覆盖该子帧的完整源帧，副本段末端延长一导出采样以避免末帧失效。原动画和用户LS播放区间不改；曲线通过同长度瞬态输入复制。审核版105采样、0.866667秒，原生骨轨回读误差0，预览网格沿用实际制作网格 Sk_CombinedMesh，动画编辑窗口已打开。实际未运行PIE；并行会话测试占用时按调度等待。

### 武器制作序列完整人物预览（2026-10-23）

握姿（未开火与开火）、装备和换弹制作入口统一通过 BBBWeaponSequencePreview 显示 Sk_CombinedMesh。计算网格保持，显式绑定映射用于烘焙；逐序列先做瞬态官方导出对比，再保存原角色模板，保留所有关键帧与挂接。已有制作源可用 full_character_preview_request 仅更新预览，不重做人工动作。详细契约见 Docs/BBBWeaponSequencePreviewMCP.md。专项绑定与时间轴检查8项通过；14把武器113个工作序列已核验为完整人物预览，各修改项导出骨轨位置误差0。

### 原位重置制作序列为公共基础动作（2026-10-23）

ManualAction制作源显式设置reset_base_request=true，通过prepare_action执行，write_paths只允许当前LS。重新从data.animation采样全部源骨骼、双臂控制器和逐节FK，清空原生Additive层关键帧并将位置、旋转、缩放增量归零；保留原绑定、附件、完整人物模板和可编辑叠加段。候选先进行官方导出及全源帧骨骼对比，通过后才保存正式LS，不改公共动画或运行引用。原生Additive缩放的中性增量是0，绝对层缩放才是1，已有专项检查保护。Shotgun01 ReloadStart实际还原26个源采样，全骨骼组件姿态位置最大误差0.000082889cm，手部IK辅助骨按既有约定排除；保留武器附件，清除旧端点、去抖及烘焙记录并回到第0帧。

### 更新逐发装填循环的已有衔接（2026-10-23）

开始段重新编辑后，match_reload_phase_offset比较源通道摘要，仅在源变化时按新旧继承偏移差调整装填循环的既有默认值和关键帧值，保留中间手工修改与时间。两端手指按新源末姿势重新对齐；候选通过肩、臂、手及30根指骨的首尾比较后才写入。源序列按自己的计算网格导出。带释放窗口的结束段不走此循环重基准分支。Shotgun01新开始段烘焙101采样、0.833333秒并应用；装填循环实际接缝位置误差0.000055174cm，旋转误差0.035194度，原基础层和附件保持，源关键帧不变。未运行PIE。

### 位置对齐禁止覆盖手指（2026-10-23用户更正）

动作首尾对齐默认finger_sides为空，逐段换弹衔接一律排除fk_通道。位置修正前后独立比较全部指骨通道摘要，若指骨关键帧或默认值变化则拒绝保存。撤销误加的手指覆盖可显式设置restore_action_fingers_request={frames:[0,6]}，仅更新指定帧的指骨旋转偏移，不触碰手部IK、武器挂接及其它轨道；可明确提供animation作为还原参考。Shotgun01开始换弹0/6帧已还原公共基础手指，持续装填0/11帧已还原先前正式成品的手指，保留两段手部位置及挂接；回读最大指骨旋转误差分别0.038049与0.036429度。已回到LS_Shotgun01_CharacterReloadStart。位置变化不影响指骨保护摘要、指骨变化会触发摘要差异的专项检查通过。

### 整段恢复原指骨输入并核对实际视口（2026-10-23）

恢复指骨默认采用data.finger_animation，而非公共身体data.animation。显式restore_action_fingers_request={entire_clip:true}将全部30根指骨从原输入按120FPS采样写回绝对层，同时清除叠加层的全部指骨键及默认增量；独立比较非指骨通道摘要，保留手部IK、附件与其它轨道。官方导出逐采样比较完整指骨局部姿态，通过后保存；不保存动画成品或替换运行引用。身体底稿重置也从独立指骨输入取手指。inspect_editor_grip_request={verify_fingers:true}直接读取当前编辑器实际角色组件的骨骼局部姿态与原指骨输入比较。Shotgun01 ReloadStart修复前与原输入的最小旋转余弦仅0.755912；整段恢复后101采样局部位置误差0cm、旋转误差0.038459度，非指骨摘要保持，指骨叠加键为0。重新打开后实际视口第0帧30骨最大旋转误差0.038448度。两项已有专项检查通过，未运行PIE。

### 2026-10-23 换弹结束段衔接

持续装填修改后，结束段按既有 release_frames 窗口更新继承偏移，保留末段与人工残余编辑；窗口变化时明确报错。grip_endpoints_request.end_only 仅重写末尾握持窗口，不删除入口关键帧。两条路径均保留手指通道。实际验收：Shotgun01 Insert 原生烘焙 45 个采样并应用；End 接续位置误差 0.000042 cm，尾姿对齐误差 0.000039 cm / 0.0151 度，手指摘要保持一致，时间轴范围有效。

### 2026-10-24 资产迁移恢复的内部引用者

迁移恢复跳过已经一同改名的旧引用者包；对应对象由正式目标列表负责保存，避免旧包清理后再次加载已不存在的原路径。新增重叠引用者场景核验，9 项迁移恢复测试通过；保留源文件摘要、目标类型与外部引用者的原有验证。

# 2026-10-24 后坐力屏幕探针

新增 `animation.sample_recoil_runtime` 使用项目编辑器库在游戏视口绘制结束时观察本地实际准星 保留游戏帧号 相机 枪口与视口证据。只在主动测试时运行 不扫描特效或弹壳 不参与装备玩法。支持统计与原始数据分页 异常投影及漏采显式报告。25 项探针与相关契约及 AO 检查通过 UE5.8 完整编译链接通过。主项目关闭小怪自动生成后完成原配置及新配置的完整弹匣对照 腰射 单发 点射和新实例加载回归。实测约 30/60/75.5 FPS 不把 120 FPS 上限当成实际帧率。使用说明见 `Docs/BBBRecoilProbeMCP.md`。

## 僵尸两份主配置与内联分区

Monster 版本只编辑逻辑与表现两份主配置。`monster_gore.inspect_monster_presentation` 核对分区所有权 `save_monster_presentation` 验证后保存 `import_monster_hit_profile` 将制作模板的参数导入主配置内部分区且不保留模板引用。伤口材质与血液工具改为接收表现主配置。普通与断肢喷血的四项倍率经既有批量通道传递 不逐命中创建系统。旧迁移入口已移除。7 项专项工具边界与 5 项公共契约检查通过。UE5.8 完整编译链接通过 原生配置 调试靶 受击连射 出生 动画和声音共 12 项检查通过。两套血粒子系统的 16 个脚本均为 UpToDate。未将这些结果当作主观表现或帧率验收。使用说明见 `Docs/BBBMonsterGoreMCP.md`。

2026-10-24 移动只读探针统一输出到 Saved/temp/LocomotionRuntimeProbe；当前网关要求 PIE 已运行后调用启动入口，不自动启动或停止 PIE，结束后停止探针并清理本次报告。

2026-10-24 blueprint.copy_reference_graph_nodes 从明确外部动画蓝图复制已有函数体或指定节点集合。局部复制必须显式映射所有边界节点。完整复制保留目标函数接口和参考布局 并映射自有成员与完整 Property Access 路径。默认仅预检 正式应用要求无 PIE 和项目资产写入权限 严格编译后保存。参考图不修改 不产生资产备份。

2026-10-24 blueprint.set_blueprint_comment_text 按明确图表 节点标识和原文替换说明正文 保留节点位置和连线 无 PIE 时执行 在可视编辑器验证保存与回读。参考图复制已通过两个实际动画蓝图的无警告编译及五项保存边界测试 项目原生模块编译成功。

2026-10-25 动画库导入采样率: `editor.import_animation_library_batch` 的每条请求支持 `sample_rate` 整数 1 至 240 默认 30。导入器使用明确自定义采样率并在回执中返回 `sampleRate` 供核验。源 FBX 存在 30 fps 半帧结束时间时可使用 60 fps 保留完整时长 不依靠裁剪或时间拉伸。无效采样率在访问或修改资产前拒绝。六项动画库导入与边界测试通过。

2026-10-25 士兵运动库重定向准备: `retarget.configure_fk_retargeter` 对脊柱和颈部采用插值映射，保留源 root 轨迹与高度、原名浮点曲线，并从目标实际手脚生成辅助 IK 骨；缺少唯一 FK、根骨或曲线操作时拒绝完成保存。官方 Slate Snapshot 按只读会话处理，Click、Type、PressKey 按 UI 会话处理，可直接切换重定向预览动作。20 项专项与相关契约测试通过，可视 UE5.8 两套源到士兵的配置保存与代表动作预览通过；尚未批量导出或建立 MM 数据库，速度特征须从最终目标骨轨计算。调用和边界见 `Docs/BBBRetargetPreviewMCP.md`。

2026-10-25 士兵双手距离修正: `retarget.configure_hand_contact_retargeters` 只写明确自有重定向器和专用目标 Rig，只读复用源 Rig。以实际源手骨建立全局目标，保留目标手腕骨轴，以右手为锚执行双臂 Limb IK，最后重建辅助骨；保留当前重定向姿态、根运动和曲线。六段样本共 816 帧的源目标双手向量偏差最大 0.02121 cm，根、骨盆及脚九点位置对比未变化。新增实际 FAL 独立挂枪预览，未替换运行时动画或进行 PIE。调用约束、数据证据和视觉审核边界见 `Docs/BBBRetargetPreviewMCP.md`。

2026-10-25 动作匹配运行时探针: motion_matching.start_runtime_probe / inspect_runtime_probe / stop_runtime_probe 有界记录实际查询轨迹 命中动画及根运动方向误差。定位并修复角色与网格相差 90 度时的轨迹坐标错误 空手四向误差由约 90 度降至 0 到 1.11 度 步枪 750 个输入游戏帧复测通过 平均方向误差 0.633 度。UE5.8 编辑器编译 原生十二组坐标回归及 23 项 Python 测试通过。接口和验收边界见 Docs/BBBMotionMatchingRuntimeMCP.md。

2026-10-26 角色基础姿态收敛: `motion_matching.consolidate_character_base_pose` 通过原生入口将 GASP 普通 MM、静态地面姿态和站立／蹲姿起身汇入公共根骨、脚部处理和 Pose History。帮扶显式选择空手 GASP 蹲姿库；装备修正在地面、恢复和帮扶期间绕过。角色只发布生命阶段及经过时间等事实，工作线程派生恢复与打断。删除旧角色攀爬、倒地四向及帮扶状态机构图入口；四个通用 Motion Warping 资产工具保留。48 项 Python 边界与 MM 相关回归通过，资产无警告编译保存；表现与操作由用户执行验收。调用约束见 `Docs/BBBMotionMatchingMCP.md`。

2026-10-26 外部参考资源读取使用项目编辑器的独立命名空间与 UE 包实例化映射 动画曲线与配置检查共用加载边界 正式项目的挂载及资源登记在读取前后核对。标准编辑器完整构建及原生十二项隔离断言通过 实际动画检查与曲线复制只读预检前后资源目录一致 脏包为空。

2026-10-26 同源裁帧动画曲线复制：`editor.copy_animation_float_curves` 在同采样率且首尾相差最多八帧时，通过原始骨盆逐帧确定时间偏移并独立核对根轨，再平移完整曲线键，保留有效插值、切线和元数据。未核验尾段通过报告交由数据库限制采样范围；骨轨不对应、非有限变换或回读不一致时拒绝保存。蓝图默认对象读取支持 `AnimBlueprint`。29 项曲线与配置定向测试通过，UE5.8 实际完成两组共 1,406 条序列的保存和骨轨不变回读；没有执行动态游戏验收。调用边界见 `Docs/BBBAnimationCurveTransferMCP.md`。

2026-10-26 角色生命动作改为蒙太奇：motion_matching.configure_character_montage_graph 仅清理明确主动画图的生命阶段采样与计时分支 保留普通 MM 及内部图 将 FullBody 槽位后置到最终惯性化之前并持续更新源姿态。倒地等待 接受救援 帮扶和站蹲起身使用蒙太奇 引擎 Disable Root Motion 通知屏蔽动作根运动。接受救援自然完成的逻辑通知只向直接角色提交带操作和倒地轮次的内部输入 计时器不再结算成功。旧构图入口删除 无兼容别名。19 项定向工具单元测试通过 原生构建通过 资产与动态验收状态见项目 Docs/Animation/CharacterBasePose.md。

2026-10-26 正式动作库原位重定向：`retarget.retarget_sequences(..., overwrite=True, preserve_target_metadata=True)` 临时烘焙后将包括 Root 的全部骨轨写入既有动画，逐条回读并保存；原曲线、通知、同步标记、根运动及根锁设置保留。Root 差值单独报告。详见 `Docs/BBBRetargetAssetAuditMCP.md`。

2026-10-26 连续举枪:`animation_graph.create_weapon_aim_additive` 制作无曲线静态参考与上半身 Local Space 加法 避免 MM 接触曲线被相减。`animation_graph.configure_weapon_aim_additives` 复用既有 FullBodyAdditives 在原有后震前合成连续举枪 工作线程蓝图制造举枪与独立 IK 权重。主图和接口没有新增调用。八份蓝图无警告编译保存 十六份正式资产从磁盘重载回读 四份加法的下半身及位置缩放差分为零。UE5.8 原生构建与十一项工具边界和结构契约检查通过 两项新增工具参数与基线一致 未运行 PIE。调用约束见 `Docs/BBBWeaponAimMCP.md`。

2026-10-27 毁伤运行美术交付: 人工通过后的制作源通过 ExportTorso.py 生成单槽 / 单 UV / 36536 三角面运行网格与共享 4K 颜色 / 法线 / ORM。十一份组织和十三份表现配置完成主编辑器导入与回读。原生材质整体重建同步清除旧输出引用并复用匹配表面。参考姿势法线区分正背面 深层腔壁使用二值顶点标记 最高胸椎高度保护颈肩连接。UE5.8 编译链接通过 毁伤七项原生回归通过。百只完好与八区加断臂短批次完成 预算开启时整帧 GPU 中位为 17.61 / 20.98 ms。临时 PIE 每轮结束自动停止。调用及制作约束见 Docs/BBBMonsterGoreMCP.md。

2026-10-27 持枪地面过渡: 重量感调校的三项改动现已全部撤销。Get_MMBlendTime 恢复原有 15 个节点 连续地面返回 0.5 秒 刚落地与空中时间保持原值。额外支撑 承重响应及专用工具已移除。仅清理指定函数 没有覆盖后续角色动画改动。记录见项目 Docs/Animation/WeaponWeight20261027.md。

2026-10-27 内嵌曲线编辑: `editor.configure_data_asset` 的结构体值支持 `structType` 与 `structText` 组合 使用 UE 原生结构文本导入后保存目标资产。目标仍须通过资产写入权限检查 可用 `object.get_properties` 回读键值。已在 30 份枪械配置上写入并逐键核对内嵌连续曲线 未进行 PIE 表现验收。

2026-10-29 左臂原位烘焙逐条保存后释放 Sequencer 瞬态对象并执行垃圾收集，避免长批次耗尽编辑器 UObject 数量。实际批处理多组完成；全库处理及引用核验仍在进行。详见 Docs/BBBHandRetargetBatchMCP.md。

2026-10-29 左手原位烘焙修复辅助骨与最终手骨不一致的问题，以逐帧父空间重建并校验；对候选动画先验证并拒绝未完成的控制关键帧底稿。864 条校准完成，15 条锁骨不可达的瞄准动作恢复原左臂；879 条各五点辅助骨回读最大误差 0.00903 cm。具体边界见 Docs/BBBHandRetargetBatchMCP.md。

## AimIK 前端枪姿势稳定工具（2026-10-29）

新增 animation_graph.configure_stable_aim_pose。它在公共装备层的 AimIK 输入前组合既有静态参考与举枪加法，按 spine_01 分支与 MM 输入姿势混合，使用现有 WeaponAimAlpha，并编译保存公共层和装备子层。项目 UE5.8 Development Editor 构建成功；工具批次保存 6 份动画蓝图，磁盘重载后公共层 BS_UpToDate、图表 54 节点，步枪/手枪/霰弹枪站蹲引用回读正确。动态观感由用户验收。

2026-10-29 左手制作入口支持按 job_index 独立处理并保留同批次已保存结果；可选预览模型与武器定义的挂接变换用于生成对应武器的制作底稿。M1911 864 条完成原位烘焙及五点回读，15 条站立瞄准超限保留原轨；正式握姿参考资产缺轨仍需单独恢复。未进行 PIE 或人工观感验收。

2026-10-29 切枪端枪覆盖修复：稳定姿势权重同时检查站立/蹲伏加法与参考四份素材；动作槽接管、无枪口或素材失效时立即归零，正常瞄准转换保留渐变。configure_stable_aim_pose 可重建既有配置的权重函数，不重复添加姿势节点。实际保存六份蓝图，磁盘重载后 BS_UpToDate，权重图回读含两份参考有效性检查和立即归零选择。未运行 PIE，动态切枪由用户复查。

## 2026-10-29 武器动画骨轨恢复

新增三个 animation_graph 原位恢复入口，恢复正式握姿解、复制同骨架空轨目标及重建举枪加法；双臂制作允许恢复元数据一致的空输出，原生动作导出和比较拒绝空骨轨。稳定端枪分支排除左右手，保留专属握姿。实际静态编辑完成 14 装备、16 换弹、28 握姿、14 后坐力与公共举枪基准恢复；85 份目标磁盘重载回读无空轨，45 份 Lyra AimOffsets 样本磁盘重载后各 68 骨轨。六个动画层编译保存，手枪后坐力原有静态求值器通过；未执行自动化动态验收。详见 Docs/BBBAnimationPoseRecoveryMCP.md。

## 2026-10-30 持枪近战与三倍 Lyra 射击加法

既有双臂制作 bake 支持 scaled_additive 任务，明确源基准帧、当前角色基准、旋转空间与幅度，逐帧回读三倍姿势差后保存。14 份正式近战从各型号已有 LS 烘焙恢复，元数据及控制曲线保持；14 份专属角色后坐力由原始 Lyra 三类射击加法重建。31 份成品及输入磁盘重载回读各 68 骨轨，定义引用保持，无 PIE 或自动化动态验收。用法见 Docs/BBBAnimationPoseRecoveryMCP.md。

2026-10-30 资产移动恢复：只读核验返回明确的未通过结果时，网关继续执行原批次恢复；其他异常仍中止。对编辑器重启后原路径与目标均存在的已执行移动，先核对原文件摘要、目标类型和无脏包，再用引擎原生合并更新引用。角色动画蓝图 20 个资产已实际合并、编译并清除无引用旧重定向器；135 个受影响包的依赖回读无缺失，持枪采样使用新动画层路径。未运行 PIE。

## 2026-10-30 FAL 手调曲线与双臂预览

现有双臂制作入口支持明确的 AnimationMetadata 正式源，以完整 UE FloatCurve 文本恢复曲线与同骨架预览，逐项验证骨轨和通知等设置保持。配置元数据源的 ManualAction 已有成品导出保留当前手调曲线及预览，新建输出才从正式元数据源初始化，避免公共输入曲线覆盖。FAL 装备四条历史曲线与换弹两条有证据曲线已恢复；换弹左右姿势覆盖保留现值并标明历史缺口。十二份动画磁盘重载回读通过，九份角色动画按用户澄清使用完整角色 Sk_CombinedMesh 预览，空轨收枪成品从正式 LS 恢复。未执行 PIE 或自动化验收，正常再烘焙分支仅语法和代码检查。见 Docs/BBBAnimationPoseRecoveryMCP.md。

## 2026-10-30 投掷姿态对齐保留手调曲线

现有首尾参考对齐入口支持正式源 preserve_curves，保持用户当前曲线并在保存前核对完整语义；自动保存参考读取在返回前完全加载包以释放文件读取锁。用于本次手雷投掷恢复与 Rifle01 参考衔接，具体静态保存及回读证据见项目 Docs/Animation/GrenadeTossRecovery20261030.md，未运行 PIE 或自动化验收。

## 2026-10-30 SG550 统一 FAL 基准审核样例

曲线恢复按引擎规范文本比较，避免显式零值被省略导致误报；姿态对齐中段回读报告归一化旋转误差，并按实际帧率选取检查时刻。SG550 换弹已应用 FAL 最新四条人工曲线、统一首尾持枪基准和五根指骨定向反向修复，正式样例使用 FAL 实际挂接偏移，等待用户审核。未运行 PIE 或自动化验收，其他武器尚未批量写入。见 Docs/BBBAnimationPoseRecoveryMCP.md。


### 2026-10-30 十三武器批量基准制作

原位动作制作支持完整骨轨指纹登记、分段装填单侧窗口与插入段保持、局部加法副层自身参考归零、实际播放范围裁切、边界指节定向桥接及无异常结果。元数据曲线按目标原生时间分辨率核对，保留用户完整键和有效插值。已对68份角色动作执行保存回读，SG550样例先经用户通过；无PIE或自动化验收。参数与阶段顺序见 Docs/BBBAnimationPoseRecoveryMCP.md。

分段接缝及加法副层的回读明确使用各项指定参考动画与帧，保留共同FAL整体端点的独立制作阶段；实际Mossberg接缝的0/44帧引用及保存指纹回读通过。
