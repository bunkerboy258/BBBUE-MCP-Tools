# 批量左手握持重定向 MCP

工具以现有 Rifle_01 握持 Control Rig 关卡序列为模板，为明确列出的动画创建独立编辑序列，并用官方 Sequencer 烘焙器生成独立动画。它用于逐批校正 Lyra 持枪动作的左手，不会遍历或批量覆盖 Lyra 原始动画。

模板默认使用 `/Game/_Project/Characters/BBBC_UA/Animation/RifleAnimsetPro/Actions/WeaponHandling/LS_EquipRifle_LeftHandIK`，目标网格为 `/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Sk_CombinedMesh`。模板必须有唯一角色绑定、源动画片段、Control Rig 轨道、`hand_l_ik_ctrl`、`elbow_l_pv_ctrl`，并为角色全部骨骼提供 `source_<bone>` 原姿势控制器。工具会逐项检查绑定、骨架、接触区间、肘部可达性、控制器关键帧与保存结果；任一项失败会清理该项未完成的输出。

`control_rig.build_hand_retarget_sequences(manifest, write_paths)` 接受一到三十二条清单。每条指定源 `animation_path`、`template_sequence_path`、`mesh_path`、新 `sequence_path`、`grip_in_hand_r`、以及 `contacts`。握持变换使用右手骨骼局部空间：`position` 是厘米位置，`rotation` 是 `[x,y,z,w]` 单位四元数，`scale` 可省略。可选 `pole_in_hand_r` 用同一空间指定左肘极向；省略时沿用源姿势肘点。可选 `weight` 位于 0 到 1。接触帧区间首尾均包含，必须排序且互不重叠；`fade_in_frames` 和 `fade_out_frames` 通过 smoothstep 在区间端点回到原始左手姿势。每段动作最多 600 帧。`write_paths` 必须与所有输出序列路径完全一致。

生成步骤复制模板到清单路径，将源动画放入唯一的 Sequencer 动画片段并按接触区间写入全身原姿势控制、左手 IK 与肘部 Pole Vector 控制。源动画片段在模板中保持停用，由原姿势控制器提供底稿，接触权重只混合左手目标。源动作、模板及现有 Control Rig 不保存或改写。

`control_rig.bake_hand_retarget_sequences(manifest, write_paths)` 将序列通过 `control_rig.bake_control_rig_animation` 的官方导出路径写入新的 `/Game/_Project/` 动画目标，不覆盖已有资产。每项指定 `sequence_path`、对应的原始 `animation_path`、`mesh_path` 与 `output_animation_path`；`write_paths` 必须精确列出所有动画目标。当前只接受 `AAT_LocalSpaceBase` 且 `ABPT_LocalAnimFrame` 的 Additive 动画及普通动画，其参考姿势索引必须有效。

烘焙后只允许左臂骨骼轨道改变：`clavicle_l`、`upperarm_l`、`lowerarm_l`、左右臂扭转骨、`hand_l` 与 `ik_hand_l` 白名单中的对应左侧项。其余骨骼逐帧校验位置误差不超过 0.05 厘米、旋转误差不超过 0.1 度；左臂任一骨骼的局部变更超过 40 厘米或 150 度则视为异常。帧数、帧率、时长、Root Motion、Additive 设置、浮点曲线名称及关键帧插值、三次插值时生效的切线、通知类与通知时间都要与源动画一致。UE 导出器会重算线性关键帧不参与求值的切线数值，校验会忽略这两个无效字段。失败时删除该项新输出，不保存原动画。

推荐分成两批：先生成并检查少量代表性序列，再对这些序列运行烘焙并逐项确认报告；确认握持变换及接触区间后，再由调用者提供后续批次清单。工具本身不推断握持目标，不启动 PIE，也不修改动画蓝图、蒙太奇或原始 Lyra 资产。

2026-10-17 在隐藏 NullRHI、Balanced 60 FPS 宿主中完成真实链路验证：普通 `MM_Rifle_Idle_Hipfire` 生成 251 帧序列并烘焙；加法 `MM_Rifle_Reload_Additive` 生成 67 帧序列并烘焙，`disableaimik` 与 `disablelhandik` 曲线通过保存后回读。输出位于 `/Game/_Project/Characters/BBBC_UA/Animation/HandRetarget/`，分别是 `LS_Rifle01_Idle_Hipfire_LHand`、`MM_Rifle_Idle_Hipfire_LHand_Rifle01`、`LS_Rifle01_Reload_Additive_LHand` 和 `MM_Rifle_Reload_Additive_LHand_Rifle01`。样本握持偏移取自原始 Idle 第 0 帧，目的是验证工具链；正式逐动作加工前仍须按 Rifle_01 的实际握把位置校准 `grip_in_hand_r` 与接触帧。样本没有接入运行时。
