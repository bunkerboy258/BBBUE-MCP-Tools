# Control Rig 动画编辑 MCP

`create_control_rig` 的 `graph_json` 与 `configure_control_rig_graph` 的 `request_json` 支持 `variables` 数组。每项使用 `name`、`type`、可选 `typeObject`、`default`、`node` 与 `position`，创建公开输入变量及读取节点。结构体例：`{"name":"TargetPosition","type":"FVector","typeObject":"/Script/CoreUObject.Vector","default":"(X=0,Y=0,Z=0)","node":"ReadPosition"}`。变量重名、类型缺失或节点创建失败立即报错；不静默复用未知变量。

动画迁移工具的 `configure_control_rig_anim_graph_node` 仅设置 Rig 和公开输入并重建引脚，保留已有 Alpha 类型、缩放偏差及姿势传递配置。需要 Float 权重时先通过 ObjectTools 设置 Node，再调用该工具生成 Alpha 引脚。不得隐式强制 Bool、反相 Alpha 或重置输入姿势。

`evaluate_rig_pose` 可选 `variables_json` 接受公开变量名到 Unreal 文本值的对象，如 `{"TargetPosition":"(X=1,Y=2,Z=3)","TargetRotation":"(Pitch=0,Yaw=0,Roll=0)"}`。在瞬态实例上、输入原动画姿势之后赋值，任一赋值失败立即报错。不保存或重定向源动画。

工具文件：`Scripts/BBBControlRigAuthoringToolset.py`。通过官方动画迁移工具的 `run_editor_script` 加载，注册 `Game.Scripts.BBBControlRigAuthoringToolset.BBBControlRigAuthoringToolset` 及 Epic 官方动画编辑工具集。

- `inspect_authoring_api` 查询当前引擎反射 API。
- `set_background_budget` 限制编辑器帧率；后台使用唯一隐藏 NullRHI 编辑器，进程优先级 BelowNormal，不操作用户前台。
- `create_control_rig` 接受目标网格、控制器 JSON、官方 RigVM 节点与连线 JSON。导入实际网格参考骨架，显式检查每个引脚和连接，拒绝覆盖已有绑定。
- `evaluate_rig_pose` 在实际网格评估的源动画姿势上调用官方 Rig 求解，不保存动画，返回源及求解后的骨骼变换。
- `prepare_animation_sequence` 创建独立 Level Sequence、生成型角色和原动画轨道，不保存当前关卡，拒绝覆盖已有序列。

此次目标资产：`/Game/BBBC_UA/Rigs/CR_BBB_Rifle_01_ReloadHandIK` 和 `/Game/BBBC_UA/Equipment/Rifle/Rifle_01/LS_BBB_Rifle_01_ReloadHandEdit`。原动画作为底层，Rig 仅调整手臂，零权重必须保留全部原始骨骼姿势。

未通过验收的全身模块 Rig `CR_BBB_UE4_Mannequin` 已删除。旧 `bake_animation_arm_trajectory` 和 `audit_arm_motion_trajectory` 已清除，旧配置 `Docs/Rifle01ReloadTrajectory.json` 已删除。`BBBAnimationTrajectoryTools.py` 仅保留复制动画、蒙太奇引用替换和固定轨道等通用资产操作，不再包含自制 IK 求解或轨迹烘焙。

原始 Lyra 动画、现有通知和运行时数据保留。当前工作尚未视觉验收。Scripts、Docs 和二进制资产不参与默认内层 Git 推送。

## 2026 09 30 握持与掌推验收

本节记录后续完成状态 上文未验收状态属于早期记录

- `build_pose_control_keys` 从实际角色网格取得父骨骼映射 修改局部旋转后使用官方 `MathLibrary.compose_transforms` 按层级重新合成组件姿势 不从已修改 AnimPose 的缓存读取子骨骼组件变换 保留原局部位移与缩放
- `configure_sequence_rig` 对无父级无偏移的 `source_` 原姿势控制器使用官方局部 Euler Transform 接口写键 每个关键帧立即读回 位置误差超过 0.01 厘米或四元数差超过阈值时直接报错 其它控制器仍使用对应的官方控制器接口
- `apply_baked_bone_deltas` 逐帧拒绝允许列表以外的骨骼差异 然后只合入授权旋转及 `ik_hand_l` 位移 原动画其它轨道和曲线保留
- `play_pie_montages` 仅用于动画与通知验证 返回 `animationOnly` 不代表装备业务输入验收 真实输入应使用 `run_pie_input_sequence` 并核对业务日志及运行时采样

当前编辑源为 `CR_BBB_Rifle_01_ReloadHandIK` 与 `LS_BBB_Rifle_01_ReloadHandEdit` 官方烘焙结果为 `ANI_BBB_Rifle_01_ReloadHandBake` 运行时使用独立 `ANI_BBB_Rifle_01_CharacterReload` 与 `_Additive` 原始共享 Lyra 动画保持作为底稿

持匣时拇指与四指对握 插入后在 1.2 秒结束手持显示并交接到枪上 手掌随后下移并在第 44 帧再次抬起推压 不能将这段下移抬起删成连续握持

验收记录见 `Docs/Rifle01ReloadValidation.md` 本轮真实输入 正侧面截图 中断清理报告位于 `Saved/Diagnostics/AnimationMotion/ReloadControlRig_GameplayVerification` `ReloadControlRig_GripVerified` 和 `ReloadControlRig_InterruptVerified`
