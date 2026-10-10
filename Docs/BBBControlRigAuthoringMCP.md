# Control Rig 动画编辑 MCP

## 独立动作制作

`sample_animation_poses` 必须提供实际动画时长内的有限非负时间 每次至多六百项 越界时在采样前拒绝 避免引擎返回参考姿势而被误认成动画内容。

- `inspect_control_rig_reference` 读取实际导入骨架的局部与组件参考变换，用于选取求解轴向及初始化控制器；只读，不创建临时资产。

- `create_control_rig_sequence` 使用明确的时长和帧率创建只有目标网格的生成型序列，不添加源动画、不保存当前关卡，拒绝覆盖已有序列。
- `configure_sequence_rig` 向该序列加入控制绑定与显式关键帧。无父级和偏移的 `source_` 控制器采用局部接口并逐键验证。
- `bake_control_rig_animation` 使用官方 Sequencer 导出器，将指定序列唯一的网格绑定烘焙到明确的动画路径；已有目标必须取得写入权限。只保存目标动画，不创建诊断备份或改写来源。

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
# 独立控制轨道首次建立

`prepare_animation_sequence` 和 `create_sequence_attachment` 复用 Sequencer 自动建立的唯一生成轨道 不再添加重复轨道 起止关键帧负责生成与销毁临时演员

`add_pose_controls` 必须显式传入 `solve_node_name` 指定原有求解执行入口 隐藏原姿势控制器先恢复底稿的组件姿势 手部位置仍由 IK 控制器编辑 不依赖特定节点名称

`configure_sequence_rig` 会核对并切换已有轨道的叠加模式 非叠加模式关闭源动画轨道 需要由原姿势控制器完整提供底稿 禁止将绝对 IK 结果再次叠加到原姿势

`build_pose_control_keys` 在没有姿势修正请求时通过官方 AnimPose 接口直接读取组件姿势 避免重新合成源姿势 不改变原始位置 朝向或缩放 单次拒绝超过 600 帧

`build_pose_control_keys` 必须显式传入包含首尾的 `first_frame` 与 `last_frame` 每批最多 120 帧 返回关键帧保留源动画的绝对帧号 长动画分批完成 不重复提交仍在执行的请求

原姿势控制器使用官方 Euler Transform 数组接口按控制器批量写键 随后对全部关键帧回读校验 不省略位置与朝向误差检查

独立序列创建器的编辑演员使用官方 `transient=True` 只提供生成型模板 不成为测试关卡的持久内容

`capture_attachment_pose` 的骨骼附件允许显式设置 `animation_time_seconds` 秒值 用于按各自时间轴检查角色与机构动画 不设置时使用角色采样时间 超出动画时长直接报错 不自动循环或截断

骨骼附件指定 `hidden_bones` 时必须同时指定动画 隐藏后重新完成瞬态组件求值 使截图使用已更新的骨骼可见性 不能将尚未刷新的一帧误当成弹匣显隐失败

`configure_sequence_attachment_animation` 在唯一附件动画片段上设置起止显示帧和固定播放速度 使用 UE5.8 官方 TimeWarp 接口并回读校验 起始帧包含 结束帧不包含 显式范围内不得超过一遍源动画 修改只保存对应序列

已有骨骼附件尚无机构动画轨道时 该入口在验证时间范围后创建唯一轨道与片段 已有多个轨道或片段时拒绝修改

通用工具 `retime_single_action_montage` 仅处理各插槽从零开始并只播放一次的单段动作 调整片段速度后用官方数据控制器更新蒙太奇帧率与长度 不修改源序列 调用后按新的动作时间轴显式配置通知

`remap_animation_bone_times` 对自有无通知无曲线的机构序列按明确时间对应点重映射指定骨骼 其它轨道等比例播放 全部源姿势在修改前读取 使用官方数据控制器保留骨骼局部位置 朝向与缩放 不修改角色动画或第三方资源

`source_animation_path` 必须明确指定独立源动画 禁止源与目标相同 源姿势含有的变换修正曲线统一烘焙到目标骨骼轨道 目标旧变换修正曲线通过官方控制器删除 避免播放时重复叠加 修改后必须同时回读原始轨道与实际求值姿势

`sample_sequence_controls` 支持明确指定的欧拉变换控制器 包括 `hand_l_ik_ctrl` 返回控制器局部通道值 不将它误称为骨骼组件空间目标 该读取不会改写控制器关键帧

`capture_attachment_pose` 的 `file_name` 必须为 `任务目录/唯一文件.png` 输出仅落入 `Saved/temp/任务目录/` 拒绝父目录跳转 目录链接和覆盖已有文件 动画与附件均在瞬态 PIE 对象上求值 不保存资产

手部近景使用固定手动曝光与中性环境光 近景补光强度为 2000 避免在五十厘米左右的拍摄距离将皮肤与手持物照至纯白 验收须能辨认物体边界与手指接触位置

首次建立控制绑定轨道时先用 `configure_sequence_rig` 提交空关键帧数组 待这次调用结束后再分批写键 官方 Sequencer 的新实例需要经过真实编辑器帧注册修改事件 同一调用内建轨后立即写键可能不产生通道关键帧 工具的实际回读与数量检查不能省略

`sample_animation_poses` 经项目编辑器库一次批量读取 UE5.8 官方 RAW 姿势 `GetAnimPoseAtTimeIntervals` 与 `AnimPoseExtensions` 公开接口均在 C++ 中调用 避免逐骨 Python 反射复制 骨名按 UE 的不区分大小写语义匹配 缺少骨骼或空姿势直接报错 不使用单位变换伪造结果

末帧秒值跨 Python 反射进入 C++ 时允许至多一微秒的舍入误差 仅该误差范围内使用实际动画末帧 返回时间为实际求值时间 其它越界请求仍拒绝

首次创建控制绑定轨道时，先以 `keys_json="[]"` 调用 `configure_sequence_rig`，让编辑器完成轨道初始化，再在下一次调用写入真实关键帧。只打开序列不能代替轨道初始化。

`create_control_rig_sequence` 接受不存在的资产包，也接受当前工作区已经打开添加但尚未创建的包；两种情况都重新验证 Perforce 状态，拒绝其它工作区持有或无效的状态。重复生成轨道会影响官方烘焙器建立临时演员，创建器使用唯一生成轨道和明确的开始、结束关键帧。

`create_sequence_attachment` 按挂接骨骼或插槽查找唯一的骨骼演员模板 不依赖绑定列表顺序 多个匹配或没有匹配时在创建附件之前拒绝操作
# 烘焙曲线保留

`bake_control_rig_animation` 从角色绑定的原始动画轨道读取源动作 即使该轨道已停用也保留其浮点曲线来源 原生复制完整关键帧 插值和切线 烘焙位置修正不会丢失 `DisableLHandIK` 或 `DisableAimIK` 控制曲线 多个不同源动作或源与结果时长不一致时拒绝保存
