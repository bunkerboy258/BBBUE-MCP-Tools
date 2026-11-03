# 六行为事实动画构图

当前唯一行为契约为 Idle=0 Alert=1 Patrol=2 Chase=3 Attack=4 Dead=5。普通命中使用部位减速和物理受击。没有独立硬直行为 旧枚举布局和三动作组接口不保留。

## 干净重建

`rebuild_fact_driven_state_machine` 接收独占持有的动画蓝图 同骨架速度 BlendSpace 两个动作序列以及三个只读事实属性。动作依次为攻击 死亡 `action_values` 必须为 [4 5]。事实属性依次为 BehaviorFact MovementSpeedFact ActionProgressFact。可明确指定事实动画父类。

原生构图删除旧函数 事件图 成员变量和动画节点。生成 Idle Alert Patrol Locomotion Attack Dead 六状态。死亡没有出口。巡逻和追击按实际水平速度求值 BlendSpace。停住时进入待机。过渡使用标准惯性化。构图只修改内存 Python 入口必须无警告编译后仅保存目标。不保存旧图或兼容分支。

重建后依次配置循环变体 动作变体和持续爬行。原生依赖为项目 Source/ABBB_EvacEditor 下的 BBBAnimationGraphEditorLibrary。宿主必须加载最新编译模块。

## 循环与动作变体

出生变化使用 `BBBMonsterVariationDefinition` 与实体 `Variation` Fragment。`configure_fact_movement_styles(asset_path, style_paths, blend_duration=0.18)` 要求三个不同的同骨架一维速度混合，干净重建 Patrol 和 Locomotion 图。固定 `LocomotionStyleFact` 只激活一个分支；`AnimationSpeedFact` 为实际水平速度除以出生速度倍率；`LoopPhaseFact` 为 Mass 持续维护的归一化相位。表现 Actor 重建不重新抽取风格或起点。拒绝 PIE、脏包、无效类型、非独占写入及编译警告。

待机与警觉现在也显式采样连续实体相位；动作和循环变体的选择读取 `VariationSeedFact`，不再使用 Actor 的临时编号。既有僵尸图必须重新配置循环与动作变体，不保留旧属性别名。循环入口结果返回 `continuousEntityPhase=true`，不返回旧起点桶数。按需组合素材风格，不新增玩法状态、逐实例动画计时 Tick 或动态材质实例。

`configure_fact_locomotion_variants` 参数为 asset_path idle_paths alert_paths stationary_speed blend_duration。它重建独立 Idle 与 Alert 姿势图。循环序列按稳定表现身份选择并错开播放起点。警觉只有一条序列时不复制相同样本。Patrol 与 Locomotion 保持实际速度混合 不写 Mass 事实。

`configure_fact_action_variants` 只接受攻击 死亡两个非空组。variant_paths 按组展开 counts 提供两个数量。progress_pivots sample_pivots progress_ends 必须与序列一一对应。逻辑进度 0 pivot end 映射到动画采样 0 sample pivot 1 然后保持末帧。满足 0 < pivot < end <= 1 及 0 < sample pivot < 1。

当前攻击逻辑 pivot 为 0.4。各序列采样 pivot 取真实命中姿势。死亡可提前倒地并保持末帧。线程安全动画函数只读事实 根据动作编号或进入时间变化翻转姿势槽。同状态新攻击也使用惯性重启 不在原生动画实例保存第二套播放器。

持续爬行构图与只读场景诊断见 [BBBFactCrawlMCP.md](BBBFactCrawlMCP.md)。爬行是姿态事实 复用相同六种行为。

## 资产与检查入口

`prepare_in_place_cycles(asset_paths, compression_reference_path)` 接收最多十六条明确的项目循环动画。先检查全部资产的独占写入状态和脏包 再将根轨道归零并对骨盆尾段做平滑接缝修正。压缩配置取自同骨架正式样本。拒绝错误骨架 缺失轨道 PIE 和保存失败。各资产逐项保存并回读根位移 批量不是事务 不自动回滚或重试。

移动循环时长由共享 `BBBMonsterVariationDefinition` 配置保存。三个向量依次对应三个固定风格 每个向量的 X Y Z 为走 跑 冲刺的真实循环秒数。待机三时长和警觉时长也从正式片段读取。变体选择和相位不在 Actor 中重新生成。

`inspect_mass_variation_network()` 只读查询全部同进程 PIE 世界。按稳定 instanceId 比较 variationSeed infection locomotionStyle speedScale phaseOffset 和速度配置。迟加入必须实际看到新增世界及相同属性后才算通过。loopPhase 是本地连续表现相位 不作为需要逐帧同步的网络事实。

`create_speed_blend_space` 创建不存在的一维速度混合资产。样本同骨架 速度严格递增且首项为零。调用前检查循环根轨道与接缝。已有资产不覆盖。

`create_merged_skeletal_asset` 从同骨架模块的导入 MeshDescription 合并材质 UV 和蒙皮 构建三层 LOD。不能用临时运行时合并结果替代可重建资产。

`create_mass_presentation_variant` 为明确合并网格创建不存在的载体 定义与实体模板并互相绑定。`reparent_presentation_blueprint` 配置明确原生表现父类。`configure_actor_animation_blueprint` 将无警告编译的同骨架动画类绑定到指定载体组件。

通用显式双通道构图与只读查询连接能力用于明确的新表现需求 不用于僵尸旧状态机兼容。僵尸正式父类只使用 BBBMonsterFactAnimInstance。

`capture_monster_animation_transition` 使用六行为编号 必须明确传入 initial_speed target_speed。静止速度为零。采样走真实动画蓝图 不替换成单节点播放。

动画样本 群体验收 根轨道审查分别写入 Saved/temp/AnimationSamples Saved/temp/PopulationBenchmarks Saved/temp/AnimationAudits。收尾仅清除本次前缀。任何构图成功都不等于视觉或性能通过。

所有资产修改拒绝 PIE 和其它会话未保存编辑 受控资产保留签出与冲突检查 未受控资产不因工作区映射而拒绝写入 并报告未受版本保护 保存后必须重载和实际验证 不自动 Submit Get Latest 或 Revert

## 血效定义绑定

`BBBAssetMaintenanceToolset.configure_monster_blood_residue` 参数为 settings_path channel_path splatter_material_paths droplet_material_paths pool_material_paths。配置独占持有后重建三类环境残留参数并保存回读。现有 Definition 绑定与共享 Niagara 保留 不修改表现蓝图 不提供旧参数或旧工具名称兼容。材质构建与 PIE 只读验收见 BBBHitReactionMCP.md。

拒绝脏包 PIE 每组重复或空材质列表及错误资产类型。工具只编辑已有配置 不创建配置或改写定义绑定。返回 success settings parameters groups 和 particleSystemRebuilt=false。粒子效果必须另外进行真实命中验证。
# 角色普通运动与离散动作

普通运动由 GASP MM 生成 倒地等待 接受救援 帮扶与起身使用后置 FullBody 蒙太奇。主图清理使用 [运动匹配工具](BBBMotionMatchingMCP.md) 的 motion_matching.configure_character_montage_graph 不修改空手库和装备层。僵尸事实动画工具保持独立。

`configure_special_infected_actions(asset_path, sequence_paths)` 只用于已重建的特感事实图.四个同骨架序列依次为蓄力 冲撞 恢复 喷吐.冲撞读取 SpecialLoopPhaseFact 按实际移动速度与表现配置步幅循环采样.其余阶段读取 SpecialProgressFact.五个入口通过线程安全 GetSpecialBlendDuration 读取唯一表现配置中的混合时长.死亡 爬行 踉跄与攀爬优先于技能姿态.原生构图后无警告编译并保存.不在 PIE 期间编辑.

`build_special_infected_assets(destination_root, prefab_root, recipe)` 为四类特感的明确自有目录建立逻辑 表现 实体模板 载体 动画蓝图和速度混合.制作描述必须指定 source_logic source_presentation source_actor mesh sequences sample_speeds logic_properties presentation_properties 以及可选 special_properties.九个同骨架序列依次为待机 行走 跑步 攻击 死亡 蓄力 冲撞 恢复 喷吐.预制资源目录必须是 Shared/Injury 下同名变体.已有输出只允许复用相同制作描述指纹 并拒绝覆盖其它来源.通过标准 IK Rig 与 IK Retargeter 生成同骨架的正式序列 并装配爬行 踉跄和攀爬.制作描述 stage=animations 可在无渲染宿主仅准备二十二个动作序列.材质适配和完整表现校验后保存完成标记 失败前已经保存的自有输出可按相同指纹继续.预制网格必须提前离线制作 不进行运行时切割.

同一入口支持离线打磨阶段. `stage=survey` 与 `sources` 明确列出一至三十二份序列 返回头 手 脚及骨盆轨迹和首尾误差. `stage=polish_animations` 的 `animations` 按角色名指定 `source` 与可选 `frames:[首帧,末帧]` 和 `loop` 使用原位重定向 锁根及尾部混合保存动作.制作指纹只复用相同输入 拒绝覆盖非本工具资产. `stage=polish_physics` 使用现有物理与受击配置内核写入 `physics` `profiles` 及 `hit_properties` 不改变血量与触发裁决.

`stage=polish_retargeters` 先按双肩横向校准目标根骨朝向 再清空旧姿势偏移. 原生同形身体保持源参考姿势 共享动作按校准后的目标重新对齐. 两套重定向器复制源根轨并固定辅助骨到实际手脚. 随后通过 `polish_animations` 原位重建明确动作 动作复用指纹包含当前姿势与操作栈. 原生动作额外保留参考姿势及父级一致的非链附属骨 例如触须 下颌和扭转骨 参考姿势不一致时拒绝直接复制. 循环收尾后重新生成辅助手脚轨道 并记录明确制作参数 不改变源第三方资源或运行时逻辑.

`stage=polish_motion_timing` 从当前三份速度混合空间读取既有六个速度点 按新动作的支撑脚位移重算步频和突进步幅. 仅保存唯一表现配置 不重建动画图 不改变速度与技能时机. 在 `polish_animations` 完成后调用.

`stage=polish_graph` 输入 `idle` 三份待机 `alert` 一份警觉 `styles` 三组待机走跑冲刺角色名 `attacks` `attack_pivots` `deaths` 四项 `special` 和 `special_animation`.完整重建当前事实图 不叠加旧状态图.速度混合包含静止 蹒跚 行走 追近快走 跑步 冲刺六个速度点.支撑脚后移速度中位数用于离线标定三种风格循环时长 高速冲撞保留至少零点四秒循环以保持姿态可读.攻击采样将手部实际接触帧映射到已有伤害时刻 死亡按原始时长结束并保持终姿.潜行与狂暴使用不同移动风格.喷吐在释放帧分段 并将同帧头部位置变换为逻辑配置的局部发射偏移.返回循环时长 步幅 保存与唯一表现配置校验 不进行自动游戏验收.

`create_slime_assets(destination_root)` 在明确的正式 Shared/Slime 目录原位装配喷口 飞行拖尾 撞击泼溅 地面水洼与少量气泡.现有 DA_Slime 的表现分区统一保存资源 配色 形变比例 拖尾寿命 铺开及消退时间和距离预算.原玩法数值与实体模板保持原值.制作阶段统一世界空间 使用 DataInstance.Alive 回收粒子 并明确写入 vec4 动态材质通道.地面保留来源实例的全部纹理参数 母材质接入贴花生命周期透明度.液体遮罩采用共享自有纹理副本 最大1024并关闭流送 减少运行时首次流送波动 不改原包纹理.同一指纹的只读结果可回报素材实际连接的动态通道.制作使用独立的现有水体与血液素材副本 不改第三方原包.仅在没有 PIE 时执行.相同制作指纹完成后只读回报就绪状态.

`preview.capture_slime_presentation(definition_path, file_prefix)` 在明确的渲染 PIE 中仅驱动正式表现载体 不生成 Mass 实体或玩法伤害.拍摄喷口 飞行 落地 成形及消退五个时刻 并回读粒子快照.前缀使用 Saved/temp 下的任务目录与名称. `preview.get_slime_capture_status()` 返回当前进度 实际时刻及图像路径.完成或失败均销毁自有灯光 地面与载体并清理回调.最终场景观感以实机为准.

`animation_graph.import_special_infected_prefabs(destination_root, prefab_root, source_mesh_path, part_ids=[])` 从同名 ArtSource 制作源导入专属骨架、物理、三档身体和内部组织。空断点列表导入身体；非空每批最多三个断点，包含三档封口及蒙皮/静态掉落与剩余段。每项保存来源指纹并回读骨架和 LOD，重复调用仅复用完全相同来源，拒绝覆盖来源不符的资产。无需 PIE，可在 NullRHI 宿主调用。

## 物理姿态到全身蒙太奇的交接

`animation_graph.configure_snapshot_montage_source(blueprint_path, slot_name, condition_getter, snapshot_property, blend_duration=0.25)` 在已有唯一全身槽之前接入只读 FPoseSnapshot。条件必须来自原生线程安全查询。条件为真时使用物理退出快照，结束后混回原源姿态；普通 MM、根骨、脚部和装备链保持原有结构。不创建起身状态机，不改变运动库。重复构图、错误快照类型或非线程安全查询会被拒绝。仅用于明确自有动画蓝图，构图后无警告编译并保存。

`motion_matching.create_schema` 的 `trajectory_offsets=[]` 创建仅姿态通道的搜索格式，适合一次性动作选择。采样骨属性可用现有反射配置工具设置；修改后必须刷新格式并核对数据库实际维度及索引，不能仅凭保存成功判定索引已更新。
