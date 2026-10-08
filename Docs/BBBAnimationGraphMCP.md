# 六行为事实动画构图

当前唯一行为契约为 Idle=0 Alert=1 Patrol=2 Chase=3 Attack=4 Dead=5。普通命中使用部位减速和物理受击。没有独立硬直行为 旧枚举布局和三动作组接口不保留。

## 干净重建

`rebuild_fact_driven_state_machine` 接收独占持有的动画蓝图 同骨架速度 BlendSpace 两个动作序列以及三个只读事实属性。动作依次为攻击 死亡 `action_values` 必须为 [4 5]。事实属性依次为 BehaviorFact MovementSpeedFact ActionProgressFact。可明确指定事实动画父类。

原生构图删除旧函数 事件图 成员变量和动画节点。生成 Idle Alert Patrol Locomotion Attack Dead 六状态。死亡没有出口。巡逻和追击按实际水平速度求值 BlendSpace。停住时进入待机。过渡使用标准惯性化。构图只修改内存 Python 入口必须无警告编译后仅保存目标。不保存旧图或兼容分支。

重建后依次配置循环变体 动作变体和持续爬行。原生依赖为项目 Source/ABBB_EvacEditor 下的 BBBAnimationGraphEditorLibrary。宿主必须加载最新编译模块。

## 循环与动作变体

`configure_fact_locomotion_variants` 参数为 asset_path idle_paths alert_paths stationary_speed blend_duration。它重建独立 Idle 与 Alert 姿势图。循环序列按稳定表现身份选择并错开播放起点。警觉只有一条序列时不复制相同样本。Patrol 与 Locomotion 保持实际速度混合 不写 Mass 事实。

`configure_fact_action_variants` 只接受攻击 死亡两个非空组。variant_paths 按组展开 counts 提供两个数量。progress_pivots sample_pivots progress_ends 必须与序列一一对应。逻辑进度 0 pivot end 映射到动画采样 0 sample pivot 1 然后保持末帧。满足 0 < pivot < end <= 1 及 0 < sample pivot < 1。

当前攻击逻辑 pivot 为 0.4。各序列采样 pivot 取真实命中姿势。死亡可提前倒地并保持末帧。线程安全动画函数只读事实 根据动作编号或进入时间变化翻转姿势槽。同状态新攻击也使用惯性重启 不在原生动画实例保存第二套播放器。

持续爬行构图与只读场景诊断见 [BBBFactCrawlMCP.md](BBBFactCrawlMCP.md)。爬行是姿态事实 复用相同六种行为。

## 资产与检查入口

`create_speed_blend_space` 创建不存在的一维速度混合资产。样本同骨架 速度严格递增且首项为零。调用前检查循环根轨道与接缝。已有资产不覆盖。

`create_merged_skeletal_asset` 从同骨架模块的导入 MeshDescription 合并材质 UV 和蒙皮 构建三层 LOD。不能用临时运行时合并结果替代可重建资产。

`create_mass_presentation_variant` 为明确合并网格创建不存在的载体 定义与实体模板并互相绑定。`reparent_presentation_blueprint` 配置明确原生表现父类。`configure_actor_animation_blueprint` 将无警告编译的同骨架动画类绑定到指定载体组件。

通用显式双通道构图与只读查询连接能力用于明确的新表现需求 不用于僵尸旧状态机兼容。僵尸正式父类只使用 BBBMonsterFactAnimInstance。

`capture_monster_animation_transition` 使用六行为编号 必须明确传入 initial_speed target_speed。静止速度为零。采样走真实动画蓝图 不替换成单节点播放。

动画样本 群体验收 根轨道审查分别写入 Saved/temp/AnimationSamples Saved/temp/PopulationBenchmarks Saved/temp/AnimationAudits。收尾仅清除本次前缀。任何构图成功都不等于视觉或性能通过。

所有资产修改拒绝 PIE 和其它会话未保存编辑 受控资产保留签出与冲突检查 未受控资产不因工作区映射而拒绝写入 并报告未受版本保护 保存后必须重载和实际验证 不自动 Submit Get Latest 或 Revert

## 血效定义绑定

`BBBAssetMaintenanceToolset.configure_monster_blood_presentation` 参数为 settings_path channel_path ground_material_paths definition_paths。已有数据通道与血迹材质只读。配置与每个小怪 Definition 修改前必须独占签出。工具仅保存配置及定义并回读 BloodPresentation 绑定。不重建已打磨的 Niagara 不修改表现蓝图 不提供旧参数或旧工具名称的兼容入口。

拒绝脏包 PIE 重复或空定义列表及错误资产类型。创建新配置时需要明确待添加权限。返回 success bindings 和 particleSystemRebuilt=false。粒子效果必须另外进行真实命中验证。
# 角色倒地姿势接入

`create_directional_blend_space` 为五个同骨架循环创建二维混合资产，输入顺序为待机、前、后、左、右。轴表示角色局部前向和右向实际速度，单位为厘米每秒。创建前检查 Perforce 写入资格，保存后仍需核对新资产的 `binary+l` 添加状态。

`configure_character_downed_state` 接收角色主动画蓝图、现有动画层接口、基础动画层、入场序列、二维混合、直接继承 Base 的装备层清单和角色配置。所有受影响资产与六个动画序列必须已独占签出。拒绝未保存编辑、重复状态、已有倒地曲线和错误继承关系。

主图沿用 `LocomotionSM`。`DownedSources` 别名集中转入 `Downed` 状态，状态只调用 `FullBody_DownedState` 动画层。入场选择导管允许首次展示已倒地角色时直接进入正确状态。状态转换读取 `SourceLifePhase`，不持有生命规则。

接口在 `ItemAnimLayers` 组增加 `FullBody_DownedState`。Base 在该层内实现 `DownedSM`，由 EntrySelector 按 `SourceDownedEntryElapsed` 选择 Entry 或 Crawl。Entry 按角色发布的经过时间采样，Crawl 读取主实例的实际局部速度。Rifle、Unarmed 继承同一实现。负入场时间跳过倒下片段。死亡仍由角色物理表现接管。

主 AnimGraph 保持统一的全身槽位、惯性化、根骨、骨骼控制和脚部控制输出链。六个倒地片段使用 `DisableLegIK`、`DisableAimIK`、`DisableLHandIK`、`DisableLocomotionAdditives` 曲线控制表现修正。原地转身函数在非存活阶段清零根骨朝向偏移。

原生构图精确清理此前错误接入的直接输出分支，拒绝拓扑不匹配，不覆盖其它节点。旧直接接图工具和入场蒙太奇配置已移除，不保留兼容入口。构图或编译失败不保存；全部无警告编译后才逐项保存。完成后必须检查状态机、继承、布局、真实角色四向动作与装备收起，单独播放动画不能替代运行时验收。

## 角色半蹲帮扶状态

`configure_character_rescue_state` 接收已有主动画蓝图、移动层接口、Base、同骨架半蹲帮扶循环和直接继承 Base 的装备层。`recovery_blend_seconds` 默认 0.5，仅表示倒地恢复到正常移动的动画混合时间，不生成站起动画或玩法锁定阶段。

主图节点和输出链保持原样。既有 `LocomotionSM` 内增加 `Rescue` 状态，读取原生事实 `bSourceRescueHelping`。状态调用接口 `FullBody_RescueState`，Base 实现循环序列，装备层沿用继承。首次展示已帮扶角色通过既有入场导管选择当前状态。救援者倒地沿用既有 Downed 转换。

拒绝 PIE、目标脏包、重复接口、不匹配继承和已有禁用曲线。检查写入资格后构图，全部蓝图无警告编译成功才保存显式目标。循环禁用脚 IK、瞄准 IK、左手装备 IK 和移动附加修正。保存后仍须检查主图布局、状态转换与继承，以及角色运行时的装备恢复和控制开放。
