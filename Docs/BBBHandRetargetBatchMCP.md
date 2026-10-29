# 批量左手握持重定向 MCP

工具以现有 Rifle_01 握持 Control Rig 关卡序列为模板，为明确列出的动画创建独立编辑序列，并用官方 Sequencer 烘焙器生成独立动画。它用于逐批校正 Lyra 持枪动作的左手，不会遍历或批量覆盖 Lyra 原始动画。

模板默认使用 `/Game/_Project/Characters/BBBC_UA/Animation/RifleAnimsetPro/Actions/WeaponHandling/LS_EquipRifle_LeftHandIK`，目标网格为 `/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Sk_CombinedMesh`。模板必须有唯一角色绑定、源动画片段、Control Rig 轨道、`hand_l_ik_ctrl`、`elbow_l_pv_ctrl`，并为角色全部骨骼提供 `source_<bone>` 原姿势控制器。工具会逐项检查绑定、骨架、接触区间、肘部可达性、控制器关键帧与保存结果；任一项失败会清理该项未完成的输出。

`control_rig.build_hand_retarget_sequences(manifest, write_paths)` 接受一到三十二条清单。每条指定源 `animation_path`、`template_sequence_path`、`mesh_path`、新 `sequence_path`、`grip_in_hand_r`、以及 `contacts`。握持变换使用右手骨骼局部空间：`position` 是厘米位置，`rotation` 是 `[x,y,z,w]` 单位四元数，`scale` 可省略。可选 `pole_in_hand_r` 用同一空间指定左肘极向；省略时沿用源姿势肘点。可选 `weight` 位于 0 到 1。接触帧区间首尾均包含，必须排序且互不重叠；`fade_in_frames` 和 `fade_out_frames` 通过 smoothstep 在区间端点回到原始左手姿势。每段动作最多 1200 帧，保留高采样率输入；通过官方 Sequencer 通道 API 写入控制器的逐帧欧拉变换，避免逐次写键求值整个序列。三个旋转通道按相邻帧展开，避免跨越 ±180° 时出现整圈插值。Control Rig 仍承担实际求解，官方控制器 API 全帧回读目标，官方 Sequencer 导出器完成烘焙。`write_paths` 必须与所有输出序列路径完全一致。

生成步骤复制模板到清单路径，将源动画放入唯一的 Sequencer 动画片段并按接触区间写入全身原姿势控制、左手 IK 与肘部 Pole Vector 控制。源动画片段在模板中保持停用，由原姿势控制器提供底稿，接触权重只混合左手目标。源动作、模板及现有 Control Rig 不保存或改写。

混合后的接触目标接近手臂伸直范围时，在制作姿势中旋转左锁骨及其子骨骼，为手臂保留 1 cm 弯曲余量；不平移关节、不缩放骨骼、不改变枪械或 IK 配置。锁骨最多修正 35°，仍不可达则拒绝该动作。报告返回最大锁骨修正角度。失败日志先保留原始原因，关闭序列编辑器并在释放制作函数局部引用后清理新输出，避免活动编辑器持有序列导致删除失败。

序列内部时间刻度选用源采样率的整数倍，至少约 24000 tick/s，保证 570 FPS 等高采样率源的结束帧和控制器关键帧不受默认 24000 tick/s 换算取整影响。源动画采样率与帧数保持原值。

`control_rig.bake_hand_retarget_sequences(manifest, write_paths)` 将序列通过 `control_rig.bake_control_rig_animation` 的官方导出路径写入新的 `/Game/_Project/` 动画目标，不覆盖已有资产。每项指定 `sequence_path`、对应的原始 `animation_path`、`mesh_path` 与 `output_animation_path`；`write_paths` 必须精确列出所有动画目标。接受普通动画，以及 `AAT_LocalSpaceBase` 下的 `ABPT_LocalAnimFrame` 或指向自身源动画的 `ABPT_AnimFrame`；其参考姿势索引必须有效。复制到新输出时，自身参考同步改为新输出，避免沿用未修正的旧基准。

通知校验使用通知对象的类路径，不比较复制后必然改变的通知实例路径；同时继续核对通知名称、触发时间、持续时间和单次/状态类型。实例路径变化不代表通知配置变化。

烘焙后只允许左臂骨骼轨道改变：`clavicle_l`、`upperarm_l`、`lowerarm_l`、左右臂扭转骨、`hand_l` 与 `ik_hand_l` 白名单中的对应左侧项。其余骨骼逐帧校验位置误差不超过 0.05 厘米、旋转误差不超过 0.1 度；左臂任一骨骼的局部变更超过 40 厘米或 150 度则视为异常。帧数、帧率、时长、Root Motion、Additive 设置、浮点曲线名称及关键帧插值、三次插值时生效的切线、通知类与通知时间都要与源动画一致。UE 导出器会重算线性关键帧不参与求值的切线数值，校验会忽略这两个无效字段。失败时删除该项新输出，不保存原动画。

推荐分成两批：先生成并检查少量代表性序列，再对这些序列运行烘焙并逐项确认报告；确认握持变换及接触区间后，再由调用者提供后续批次清单。工具本身不推断握持目标，不启动 PIE，也不修改动画蓝图、蒙太奇或原始 Lyra 资产。

运行时交接核验可组合 `animation.start_pie_montage_motion_capture(capture_images=false)` 与 `animation.run_pie_input_sequence`：无截图采样保持游戏时间倍率，不阻塞后续输入提交，也不等待动作自行开始后才允许输入。它先返回 waiting，随后由正常装备或换弹输入启动动作；使用状态工具读取完成结果，数据输出在 `Saved/temp/<file_prefix>/motion.json`。带截图模式继续保留原有慢速观察与等待行为。

2026-10-17 在隐藏 NullRHI、Balanced 60 FPS 宿主中完成真实链路验证：普通 `MM_Rifle_Idle_Hipfire` 生成 251 帧序列并烘焙；加法 `MM_Rifle_Reload_Additive` 生成 67 帧序列并烘焙，`disableaimik` 与 `disablelhandik` 曲线通过保存后回读。输出位于 `/Game/_Project/Characters/BBBC_UA/Animation/HandRetarget/`，分别是 `LS_Rifle01_Idle_Hipfire_LHand`、`MM_Rifle_Idle_Hipfire_LHand_Rifle01`、`LS_Rifle01_Reload_Additive_LHand` 和 `MM_Rifle_Reload_Additive_LHand_Rifle01`。样本握持偏移取自原始 Idle 第 0 帧，目的是验证工具链；正式逐动作加工前仍须按 Rifle_01 的实际握把位置校准 `grip_in_hand_r` 与接触帧。样本没有接入运行时。

2026-10-17 最终制作完成 Rifle01 的 67 条基础动作和 4 条专属动作，每条保留独立正式 Sequencer 并完成烘焙。基础动作共 5178 帧独立握持回读、214 个同步标记核对通过，21 项针对性单元检查通过。上述旧四项工具链样本已在确认无引用后删除；正式输出归 Rifle_01/Animation/Character，正式序列归 Rifle_01/Animation/Sequencer。用户负责其余运行时和实际画面验收，无截图采样修正后未再次执行 PIE 验证。

`animation.replace_animation_bone_tracks` 可提供 `source_animation_path`，直接读取已烘焙源的完整原始轨道并写入现有 `animation_path`；此模式省略 `tracks`，与显式轨道模式互斥。目标对象和路径保留，不删除或重建资产。要求源与目标骨架、帧数、帧率、Root Motion、Additive 参考、通知时间、浮点曲线和同步标记一致，骨骼轨道集合完全相同；支持最多 1200 帧与 128 条轨道。所有轨道先准备和校验，再通过动画控制器写入，逐帧回读位置、四元数、缩放并检查元数据未变化后保存。不创建备份或修改源动画。

## 当前库原位左臂样板

control_rig.process_dual_arm_body_pose接受以_LeftHandMotion.json.source结尾的制作源，action=bake，write_paths精确列出jobs的animation及sequence。制作源指定mesh、reference、template及jobs；从当前正式握姿读取右手局部左手目标，复用既有源姿态控制器与左手Rig求解。官方导出仅在瞬态LS和动画副本执行，不调用CurveSnapshot路径；正式动画只写七根左臂及辅助骨旋转，并同步 ik_hand_l 平移；保留真实手臂骨的原平移、全部缩放、其他骨轨和元数据，回读后保存。

2026-10-29 三条MM1700样板已原位烘焙保存：待机299采样、步行119采样、跑步74采样。制作源为角色Source/Animation/MM1700_FAL_LeftHandMotion.json.source。原文件共享锁已解除；左手辅助IK同步完成，非左臂骨轨与元数据回读保持。三个正式LS的枪体挂接已同步当前FAL配置，前台打开动画及待机制作序列供用户播放审核。没有执行PIE或自动化验收，尚未批量处理其余动画。瞬态烘焙对象不落盘，不创建备份。

2026-10-29 批量原位烘焙中，Sequencer 临时对象累计触发编辑器 UObject 上限。原位左臂入口现在在每条保存后释放瞬态烘焙引用，收集 Python 和 UE 临时对象，再继续下一条；故障批次必须先确认宿主终止及资产恢复状态，复用已有制作序列的源控制器重烘，不能依靠失败状态推断每条是否保存。非目标轨道和已覆盖元数据仍在单条保存前回读核对。

2026-10-29 原位烘焙在瞬态候选上验证后才写正式动画；检查全部源姿势、手和肘控制通道的逐帧键数，拒绝复用失败后的空底稿。左手辅助骨从最终 hand_l 与辅助骨实际父节点逐帧计算局部轨道，并验证全帧组件空间位置与角度。制作源 mode=ik_sync 只修复既有动画的辅助骨，mode=restore_original 从明确第三方来源和重定向器恢复受损左臂，仅写左臂旋转和左手辅助骨；恢复输出挂载到 Saved/temp/BBBLeftIKRetarget，执行完毕清理并卸载。两模式仍使用同一 process_dual_arm_body_pose 入口，需明确列出 animation 与 sequence 写入路径。原始设置检查包含根锁、速率、插值及压缩设置。864 条有效动作完成；15 条不可达的极端瞄准姿势保留恢复后的原左臂，记录见项目 Docs/Animation/MM1700_Rifle01_LeftHandCalibration20261029.md。
# 正式握持制作输入

`process_dual_arm_body_pose` 的左手动作制作分支直接读取正式制作源 `grip_in_hand_r`，通过已有变换校验后使用，不再从参考动画重新求值并覆盖此输入。字段缺失或无效时在动画写入前明确失败。既有制作源的握持变换已包含右手空间位置和四元数，参考动画缺轨不会再把骨架默认张臂姿势当成握持目标。

