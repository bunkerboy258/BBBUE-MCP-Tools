# BBBUE MCP Tools

武器预览与烘焙使用迁移后的 `/Game/_Project/Characters/Items/Equipment/`。迁移故障收尾分批读取已保存的包并核验蓝图状态。收尾期间保留写入槽 宿主状态轮询可继续。

2026-11-21 四指几何修复逐帧限制指根、中节和末节仅向掌心屈曲，清除侧摆和轴向扭转。UE 5.9 已烘焙并回读 SG550 换弹对照副本的 24 条指骨旋转与 265 个采样。详见 [手指动画修复](Docs/BBBFingerAnimationMCP.md)。

换弹审核应用从已保存的 Sequencer 读取新旧弹匣偏移，并在保持通知实例和时序的前提下写回角色蒙太奇。打开审核时保持人工编辑的弹匣偏移。换弹烘焙和后坐力检查分别返回结果。

装备和换弹底稿支持本型号独立右腕预览，替换 Rig 前后核对关键帧与烘焙补偿。已有开火握姿关卡序列支持直接烘焙和交接装备审核。详见 [Control Rig 动画编辑](Docs/BBBControlRigAuthoringMCP.md)。

武器审核交接使用本型号的运行配置核对预览枪、右腕和手持弹匣，打开装备与换弹序列前校验公共握姿。UE 5.9 已验证 UMP45 换弹序列交接和 AKM 专属投掷动作复制、保存与配置回读。AKM 手调后的重新烘焙等待审核。

武器动作审核分开核对目标武器接触和公共握姿交接，正式应用前按现有 `DisableLeftHandIK` 曲线验证交接帧。UE 5.9 已对 UMP45 装备和换弹运行瞬态候选检查，四个端点相对 FAL 基准的位置误差均小于 0.001 cm。详见 [Control Rig 动画编辑](Docs/BBBControlRigAuthoringMCP.md)。

`control_rig.review_weapon_action` 对装备和换弹底稿读取目标武器握点 校正明确的枪体接触区间 并把审核应用与下一份打开合为一步。UMP45 装备已在 UE 5.9 核对 51 帧 校正后最大误差 0.143 cm 与 0.04°。详见 [Control Rig 动画编辑](Docs/BBBControlRigAuthoringMCP.md)。

`control_rig.bake_control_rig_animation` 更新已有动作时先做瞬态烘焙，再按正式帧时刻写入骨骼轨道。UE 5.9 已对 AKM 装备和换弹回读 51 与 67 帧，原曲线、蒙太奇片段和通知一致。

`control_rig.prepare_weapon_action_review` 从同类武器的已审底稿建立独立动作序列。核对样板关键帧、挂接变换、显隐轨道和播放区间，更换目标枪体及明确映射的配件。UE 5.9 已从 SG550 建立 AKM 装备底稿，回读 47820 个角色关键帧，并在四处采样核对枪体显隐及手部位置。操作见 [Control Rig 动画编辑](Docs/BBBControlRigAuthoringMCP.md)。

2026-11-05 新增 `cinematic` 通用入口. 在当前可见编辑器创建带原生摄影机切换的推进序列并通过宿主内 Movie Render Queue 输出 PNG 同时提供顶点染色标题与普通二维媒体 UI 材质. 八个序列与两项材质创建保存回读通过 第一镜实际输出 60 帧 4K PNG. 使用与证据范围见 [摄影序列](Docs/BBBCinematicMCP.md).

2026-11-05 骨轨复制入口新增 `match_source_timing` 显式选项 支持无曲线 通知及标记的同骨架动画原位同步源帧数与帧率 不删除资产或断开引用。保存前核对全部骨轨与元数据 实际资产回读结果见工具返回。不以此替代 PIE 视觉验收。接口说明见 [动画迁移](Docs/BBBAnimationMigrationMCP.md)。

2026-11-04 新增 `monster_gore.import_special_infected_gore`。按身体 内部组织 分批断点和配置四阶段交付已批准的 Blender 烘焙资源 保持原骨架与绑定。支持每变体共享图集父实例及八区制作遮罩 不修改玩法或动画配置。十一项毁伤入口边界检查通过 四种特感正式导入保存回读均为 ready 未执行 PIE 或战斗画面验收。见 Docs/BBBMonsterGoreMCP.md。

2026-11-12 特感毁伤导入按当前高模批准摘要核验来源。每个变体读取自己的八区遮罩 三档内部组织保留内壁与器官分区 继续使用一份内部组件。见 Docs/BBBMonsterGoreMCP.md。

2026-11-04 材质不可达节点清理统一使用 `editor.prune_unused_material_expressions`. 原 `material.delete_unused_expressions` 不再公开. 仅遍历明确自有材质的输出依赖 解除不可达表达式及其图节点的根引用 从表达式集合移除并迁入瞬态包 避免 UE5.8 原生删除接口的根引用断言. 保留可达节点及全部输入连接 编译后保存并回读节点数量. UA 皮肤与衬衫分别清理 6 和 5 个不可达节点 已完成编译 保存及回读 未运行 PIE 或画面验收.

2026-11-04 新增 `runtime.apply_scene_quality`。在 PIE 通过实际 GameUserSettings 应用画质并回读设置类及渲染参数 不保存用户配置或资产。已同步入口 契约与工具基线。UE5.8 实机三档回读通过 项目设置类正确应用 TAA TAA TSR 和 1 1.5 2 毫秒动画预算 全部 33 个感染者表现网格接入预算。1080P 为输出尺寸 低中高内部渲染比例分别为 75 85 100。未以编辑器采样宣称打包帧率。

2026-11-04 几何表面采样路径校验支持中文资产目录和包名，保持明确 Game 包路径及任务临时输出限制；用于读取实际服装在正式持枪姿势下的蒙皮表面。语法检查通过，资产采样结果随调用回读。

UE 5.9 编辑器工具与任务调度。固定入口默认 `http://127.0.0.1:8000/mcp`。

2026-11-21：已有武器动作的左手重烘焙直接读取制作序列，以现有成品的骨轨与时长导出，按原曲线应用握持基准。UE 5.9 已原位烘焙 SCAR-H 换弹的 265 个采样，完整曲线摘要和蒙太奇片段回读一致。详见 [动作左手握持基准](Docs/BBBActionLeftHandAlignmentMCP.md)。

2026-11-21：武器动作及握姿烘焙回收本次原生导出遗留的 Sequencer 实例。UE 5.9 连续两次导出 MAC10 装备动作，换弹序列的预览角色和枪械数量保持一致，关闭序列后无残留。详见 [动作左手握持基准](Docs/BBBActionLeftHandAlignmentMCP.md)。

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

环境为 Windows、UE 5.9、项目编辑器模块、Python 与 `requests`。项目 Python 搜索路径指向本仓库 `Scripts`，由 `init_unreal.py` 接入独立常驻服务。

```powershell
.\Scripts\MCP\Start-BBBMcpService.ps1 -ProjectPath '<uproject绝对路径>' -InstallAtLogon

$hostInfo = & .\Scripts\MCP\Start-BBBMcpEditor.ps1 `
    -ProjectPath '<uproject绝对路径>' `
    -EnginePath '<UE 5.9 根目录>' `
    -PerformanceProfile Balanced
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认档位为 60 FPS、Normal。手动打开项目共用 `BBBMcpEditorStartup.start_editor_mcp()` 接入链。

源码版本变化返回 `TOOLSET_UPDATE_REQUIRED`。`restart` 指出待更新的 `service` 或 `host`；先交接已接收批次，再重启对应进程，回读 `source.current=true` 后继续。源码巡检间隔一秒，注册前后执行完整核验。

## 参考

`blueprint.rename_animation_blueprint_function` 用于原地重命名动画蓝图的本地函数图。工具调用 UE 的图表改名接口，编译后核对动画节点的属性绑定路径，再保存目标蓝图。已用 `BBBABP_UA` 回读确认函数节点和连线保留，`NotifyRecencyTimeOut` 绑定已更新，`BlendTime` 绑定保持原样。

- [公开契约](Docs/UnrealMcpCanonical.md)
- [调度与恢复](Docs/BBBMcpTaskProtection.md)
- [项目依赖](Docs/ProjectDependencies.md)
- [第三方动作](Docs/BBBExternalMcp.md)

## 本轮更新

2026-11-21：工具发现按实际用途排序，离线契约标注缓存状态，普通蓝图优先使用 DSL。批次等待由状态变更唤醒，已就绪的独立测试沿所属宿主继续。强制重存统一使用 `assets.resave_assets`。本机目录的 99 条离线搜索首项命中 99 条。

2026-11-18：新增 UE 5.9 Kimodo / AnimGenOffline MCP 准备工具，按目标骨骼网格创建批量生成工作序列及武器专属 AnimSequence 导出路径；新增异步准备状态查询与序列切换入口。UE 原生路径数组与反射属性映射已核验，六个区段全部准备就绪。当前编辑器设置为 GPU 模型、CPU 文本编码器、NF4；本机尚未配置可访问 `meta-llama/Meta-Llama-3-8B-Instruct` 的 Hugging Face 令牌，实际推理、导出与 AnimSequence 回读待本地设置令牌后完成。编辑器私有回环端口在临时端口绑定失败时会改试高位端口。详见 [BBBKimodoMCP](Docs/BBBKimodoMCP.md)。

2026-11-16：接入 UE 5.9 官方目录与蓝图 Graph DSL。启动器核验引擎版本和宿主身份，旧蓝图转译入口由原生工具接替。保存指定资产使用 `asset.save_asset`。蓝图 DSL 已验证创建、读取、修改、编译与清理。曲线、序列绑定和 Niagara 写入按引用内的资产路径排队。

UE 5.9 编辑器 V8 构建通过。249 项 MCP 离线测试通过。真实宿主上的 82 条搜索 79 条首位命中，82 条前三命中。临时枚举写入、保存与跨客户端回读均已验证。

2026-11-14：MCP 服务独占回环端口；仅在独占绑定验证端口可用后启动服务，收回启动失败的子进程，并限制并发请求及读写等待。

2026-11-04：新增独立弹窗通道与原生模态循环桥，control_task 支持 inspect_dialog/respond_dialog；提示选项按快照、归属及等级提交，原批次继续保存回读。九项弹窗契约检查及原生编辑器模块编译通过；真实共享宿主已回读模态窗口，公开服务与宿主源码版本一致。

2026-11-03：全目录与缓存统一校验范围声明；参考回放补齐会话范围。声明错误在发布前独立记录，参数范围错误返回补参字段；当前地图单独核验已保存包，打开地图合并当前与目标范围并支持 Entry 和临时空地图。源码及原生目录静态覆盖、专项契约检查通过。

2026-11-03：复用目录版本，支持精确 ID、源码指纹巡检、客户端身份加载和版本失配重启指引。静态语法、范围覆盖与引用检查完成。

2026-11-04 普通关卡构建: 新增保留源材质的原生 HLOD 单簇构建 光照有效性检查 纹理流送组件构建和反射捕获入口 模块编译通过 DeadCity 已完成 CPU Production 整图光照与反射捕获 保存重载后光照及非空体积光照有效 未构建对象和纹理流送组件均为 0 全部 17 簇有效 官方 Slate 短时 PIE 角色截图已核对 尚未进行 2K120 性能验收 详见 Docs/BBBLevelBuildMCP.md

2026-11-04 `editor.configure_inner_outline_material` 原位构建自有后处理材质 双模板组分别提供白色与橙色可见内侧轮廓 独立宽度和强度参数 支持新增或更新后处理材质 不创建兼容入口 工具语法核对通过 实际材质已保存且六个标量及橙色参数回读一致 完整材质再次编译后无新增编译错误 未运行游玩或画面验收。

GPU 分析改为 prepare、等待至少 60 帧、连续 capture、最后 restore；避免将绘制标记切换触发的预阴影缓存重建误判为稳定开销。流程和实测边界见 [BBBGpuProfileMCP](Docs/BBBGpuProfileMCP.md)，专项回归检查通过。

动作左手基准使用现有 Control Rig 求解，仅修改左臂并保留原手指及右臂。FAL 装备、换弹及 Mossberg 三段装填已原位烘焙保存，公共握持端点位置误差小于 0.005 厘米，逐发装填手指接缝误差小于 0.00004 度，插入段人工关键帧文件哈希保持；未运行 PIE，观感待人工审核。制作契约见 [BBBActionLeftHandAlignmentMCP](Docs/BBBActionLeftHandAlignmentMCP.md)。

2026-11-04 僵尸行为步态: `animation_graph.configure_fact_movement_styles` 分别接收 `patrol_style_paths` 和 `chase_style_paths` 两组各三套速度混合 巡逻与追击不再由同一组输入构图。三份待机与固定移动风格共用索引 起步和停步使用分开的速度门槛 原地转身限定在接近静止时。原生编辑器构建通过 两份正式动画蓝图均无警告编译保存 采样骨盆及手臂腿部的移动循环首尾误差低于 0.03 cm 和 0.08 度 现有十项动画图工具检查通过。未启动 PIE 未进行视觉验收。接口说明见 [BBBAnimationGraphMCP](Docs/BBBAnimationGraphMCP.md)。

2026-11-04 僵尸动画工具按原始秒数采样普通与爬行攻击及死亡。移除动作时间重映射参数。移动周期按原片段长度配置并支持三风格速度向量。Mass 行为探针可选择安全的原生状态机读取与八骨轨迹采样。入口边界回归覆盖源时间参数与拒绝旧重映射参数。

工具入口回归 16 项通过。两轮正式场景各约 10 秒采到 33 只僵尸的真实行为与骨骼事实。两种普通攻击的采样时间斜率均为 1.000 并在原始接触时刻判伤。循环倍率未超出 0.8 到 1.2。设定 60 fps 上限时探针下实际约 32 到 35 fps 此数据不作为稳定帧率或性能基准。

换弹制作预览可独立同步正式枪体片段速度和显隐通知；隐藏区间覆盖首尾插值帧，避免临时弹药与原模型同时显示。已刷新12把上线枪械的14段预览并回读隐藏区间，全部Control Rig与变换关键帧保持。未运行PIE；契约见 Docs/BBBActionLeftHandAlignmentMCP.md。

2026-11-18 资产迁移恢复按原批次证据处理混合状态：正式目标需已保存；旧副本需匹配原始 SHA256；旧重定向器需准确指向正式对象。使用引擎合并副本并更新引用，旧包无引用后通过引擎删除，最终回读磁盘和资产注册表。发现组外引用、未知文件或未保存项目包时保留原路径。入口仍为控管原批次的 recover；原生执行结果以批次回读为准。 BBB_Evac 原批次已回读 349 个正式目标，原生清除 349 个旧包；未运行 PIE。

迁移恢复按 UE 对象标识核对目标路径。目标仅大小写不同时仍须通过源文件摘要、目标类型及旧引用清理核验。已在 BBB_Evac 的 15 个动画蓝图及配套资产恢复批次验证。磁盘目录大小写需单独核验。
