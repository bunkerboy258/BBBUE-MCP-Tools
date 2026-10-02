# BBB 动画迁移 MCP

## 动画恢复与蒙太奇引用

`restore_animation_from_source(source_path, destination_path)` 删除目标动画并从源动画原位复制 使骨骼轨道 曲线 通知与全部动画设置与源一致 目标不存在时直接复制 禁止 PIE 中执行 目标存在时要求独占签出 保存后回读骨架与时长校验

目标资产被编辑器动画数据控制器持有时删除会被拒绝 可关闭宿主后删除目标 uasset 文件 再启动宿主直接复制 引用该目标的蒙太奇在目标重建前不要保存

`replace_montage_animation_references(montage_path, replacements_json)` 的映射键除了动画路径也接受 `slot:插槽名` 按插槽替换全部片段 用于当前引用已损坏为空的片段修复

蒙太奇运动采样的装备记录包含武器 `LeftHand` 插槽的世界变换 采样总超时为 300 秒 覆盖离屏渲染宿主的慢速帧率

## 左手 IK 曲线

`replace_animation_float_curve(asset_path, curve_name, keys_json, dry_run=True)` 原位替换一个 AnimSequence 的浮点曲线 `keys_json` 为包含 `time` 与 `value` 的关键帧数组 默认只预检 写入要求目标包无未保存修改 已独占签出 可编辑且不在 PIE 中 目标曲线原始 `.uasset` 与关键帧清单备份到 `Saved/Diagnostics/LeftHandIKCurves/Backups` 保存后逐关键帧复核并通过 `[BBB][LeftHandIKCurve]` 日志报告结果

`/Game/BBBC_UA/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_Base` 的 `Two Bone IK hand_l` 节点读取 `DisableLHandIK` 曲线并将 AlphaScaleBias 设为 Scale `-1` Bias `1` 因此曲线值 `0` 表示启用左手 IK 曲线值 `1` 表示关闭左手 IK

## 前臂扭转轨道

`limit_hand_swing_tracks(animation_paths, mesh_path, maximum_swing_degrees, dry_run=True)` 对显式动画的左手骨限制摆动角 保留轴向扭转和局部平移 仅在确认持枪接触关系后使用 默认只审计 写入要求独占签出和非 PIE 状态 工具保存修改前备份并验证其余所有轨道和事件不变

`inspect_pie_arm_pose()` 输出本地角色各骨骼网格的手臂最终姿势 参考旋转和活动动画 `capture_pie_bone_pose(focus_bone, camera_offset, file_name)` 围绕指定骨骼拍摄真实持枪场景 两者均只作用于 PIE 不保存资产

`capture_animation_pose(animation_path, mesh_path, time_seconds, focus_bone, camera_offset, file_name)` 在开启渲染的 PIE 世界中创建临时角色和相机 固定动画采样时刻并导出局部或全身图像 完成后销毁临时对象 不保存关卡 原生 `EvaluateAnimationPreviewPose` 仅接受临时 Actor 上的组件 用于截图前同步完成骨骼求值

`create_rifle_magazine_reload_animation(source_path, animation_path, montage_path, definition_path, magazine_mesh_path)` 使用 AnimSequenceFactory 从目标骨架创建全新动画 读取指定武器动画首帧作为基准完整生成骨骼轨道 弹匣骨在 0.30 至 0.40 秒短距离退出并在隐藏期间复位 新动作长度与 2.2 秒人物蒙太奇对齐 创建新蒙太奇并设置到步枪配置 原购买包动画保持不变 目标路径必须不存在 配置资产必须独占签出 且禁止在 PIE 中执行

`inspect_animation_bone_track_keys(asset_path, bone_name, sample_count=12)` 通过原生编辑器库读取动画数据模型里的真实骨骼关键帧 用于检查新建动画保存后的轨道与运行姿势是否一致

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.add_animation_notify_events(asset_path, track_name, events_json)` 向指定动画通知轨道增加单次通知 保留已有通知及其时间 状态和轨道 输入数组每项包含 `class_path` 与 `time` 要求资产独占签出 保存后返回完整通知列表

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.replace_animation_notify_track(asset_path, track_name, events_json)` 原位替换指定轨道的通知 输入数组支持单次通知与带 `duration` 的通知状态 每项可附 `properties` 设置独立通知实例的网格引用 骨骼名 浮点值和 `location` `rotation` `scale` 变换数组 旋转也可传 `rotation_quaternion` 四元数数组 要求资产独占签出并保存

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.move_animation_notify_event(asset_path, notify_class_path, time_seconds)` 移动资产中唯一的指定单次通知 校验通知名称唯一及目标时间 保留其他通知和轨道 拒绝 PIE 中写入 要求资产已签出并在保存后返回完整通知列表

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.set_asset_object_property(asset_path, property_name, object_path)` 为独占签出的资产设置单个对象引用属性 拒绝非对象属性和 PIE 中的写入

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.set_asset_transform_property(asset_path, property_name, transform_json)` 为独占签出的资产设置单个变换属性 JSON 使用 `location` `rotation` `scale` 三个长度为三的数组 旋转顺序为 Pitch Yaw Roll 保存后回读变换

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_static_mesh_bounds(asset_path)` 只读返回静态网格局部包围盒 用于定位手持道具的网格原点

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_pie_hand_attachments(bone_names)` 只读返回本地角色指定手部骨骼与附着静态网格的世界变换 用于核验手持道具的实际挂接位置

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_pie_actor_skeletal_bones(class_path, bone_names)` 只读返回 PIE 中指定 Actor 类的骨骼网格骨骼世界变换 可与角色手部骨骼采样一起计算通知实例握持偏移

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_pie_bone_alignment(class_path, actor_bone_name, pawn_bone_name)` 只读计算本地角色持有 Actor 的指定骨骼相对角色骨骼的变换 用于设置通知实例中的手持位置

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_animation_notify_properties(asset_path, class_path, property_names)` 只读核对动画中唯一通知实例的网格 骨骼 变换和时间参数

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.resave_asset(asset_path)` 对已独占签出的资产按当前类定义重新序列化 用于清理已删除的配置属性 拒绝 PIE 中执行

`Game.Scripts.BBBGenericEditorToolset.BBBGenericEditorToolset.inspect_animation_montage_segments(asset_path)` 只读返回蒙太奇每个插槽的动画片段引用 起止时间和播放速率 用于核验资产重建后的真实引用

原生编辑器库 `UBBBBlueprintEditorLibrary::GetAnimationBoneTrackTransforms` 读取真实动画模型中的完整源姿势 `GetAnimationProtectedDataHash` 校验非目标轨道与曲线 支持 UE5.8 的 Sequencer 数据模型 不使用固定返回空数组的旧轨道读取接口

`audit_arm_twist_tracks(animation_paths, mesh_path)` 逐原始关键帧审计左右 `lowerarm_twist_01_l/r` 与手骨的轴向旋转分配

`rebuild_arm_twist_tracks(animation_paths, mesh_path, dry_run=True)` 默认只审计 显式关闭预检后要求目标资产已经独占签出且没有未保存改动 工具从手骨相对骨架参考姿势提取轴向扭转 根据辅助骨在前臂上的位置分配旋转 保持手骨和全部非目标轨道不变 原始完整姿势数据用于普通动画与加法动画 加法配置和参考动画引用保持不变

接口注册位于 `Scripts/BBBAnimationMigrationToolset.py` 实现位于 `Scripts/BBBArmTwistTools.py` 报告与修改前备份保存在 `Saved/Diagnostics/ArmTwist` 写入后校验非目标轨道 通知 标记 曲线 根运动配置以及目标骨的平移和缩放 骨架不匹配 辅助骨层级异常 变换曲线 未签出和验证失败均以 `[BBB][ArmTwist]` 报警并停止

项目通过 UE5.8 官方 `ModelContextProtocol`、`ToolsetRegistry` 和 `EditorToolset` 插件暴露动画迁移工具。

工具集名称：`Game.Scripts.BBBAnimationMigrationToolset.BBBAnimationMigrationToolset`

- `probe_python_api`：确认当前 UE 版本实际暴露的 Python 类型和函数。
- `audit_ik_foot_tracks`：逐关键帧比较 `foot_l / foot_r` 与 `ik_foot_l / ik_foot_r` 的组件空间位置，输出 Stride Warping 输入轨道审计报告。
- `audit_ik_foot_tracks_against_reference`：使用当前与原版各自的实际网格，按同相对路径筛选原版关系正常而当前关系损坏的修复候选。
- `rebuild_ik_foot_tracks`：按 UE 自带 Copy Bones 的组件空间复制方式，原位重建指定非加法动画的左右 IK 脚轨道并立即复核。
- `start_locomotion_runtime_probe`：启动 PIE 移动、状态机、同步播放器和最终脚部姿势的只读逐帧探针。
- `stop_locomotion_runtime_probe`：停止移动动画探针并关闭 JSONL 与 CSV 报告文件。
- `probe_animation_blueprint`：读取动画蓝图的父类、骨架、全部图表、节点、引脚与关键动画节点属性。
- `probe_animation_property_access_paths`：通过仅编辑器模块中的 `UBBBBlueprintEditorLibrary` 读取动画蓝图属性存取节点隐藏的完整路径，用于定位已删除变量的残留读者。
- `rename_animation_blueprint_variables`：重命名动画蓝图成员变量并同步修正全部节点引用。
- `probe_animation_assets`：读取 AnimSequence 的骨架、长度、根运动、曲线、通知与同步标记。
- `probe_animation_bone_trajectories`：按归一化时间读取 AnimSequence 的根轨迹与指定骨骼轨迹，用于比较重定向前后的步幅和落脚位置。
- `probe_animation_component_poses`：必须指定与动画骨架一致的 `mesh_path`，按实际网格采样指定 `bone_names` 的组件空间姿势、四元数和左右 FK/IK 脚位置及旋转误差；`incorporate_root_motion` 控制是否保留根轨迹。缺少骨骼或骨架不一致会报错，报告写入 `Saved/Diagnostics/BBBAnimationComponentPoses.json`。
- `audit_animation_dependencies`：汇总动画目录对指定路径前缀的直接资产依赖，用于清理迁移源目录前确认正式资产是否仍有残留引用。
- `audit_animation_migration_metadata`：汇总正式 AnimSequence 携带的动画修改器、曲线压缩设置、加法基准动画与实际通知引用。
- `finalize_animation_runtime_assets`：将正式动画真正使用的通知资产迁入共享目录，并重建仍携带迁移孤儿对象的动画包。
- `replace_lyra_animation_references`：按唯一同名关系，将复制进项目的 Lyra AnimSequence 引用整体替换为 `/Game/BBBC/Animation` 中的重定向资产；支持只读预检。
- `retarget_missing_animations`：使用指定 IK Retargeter，只生成同名替换阶段报告为缺失的动画。
- `clean_retargeted_animation_dependencies`：保留已烘焙曲线与标记，移除正式动画携带的迁移期 Modifier 记录，并将曲线压缩和加法基准引用切换到正式目录。
- `set_animation_blueprint_skeletons`：将迁移后的 AnimBlueprint 统一切换到 BBB 目标骨架、编译并保存。
- `set_animation_blueprint_preview_mesh`：通过原生编辑器库设置 AnimBlueprint 预览骨骼网格、编译并保存。
- `add_animation_layer_boolean_input`：在动画层接口图的输入姿势上增加布尔参数，编译并保存接口；PIE 期间拒绝修改。
- `configure_recoil_animation_graphs`：新增 `FullBodyRecoil` 动画层接口，在 Base 动画层创建独立的 `Recoil_SM` 与可配置的 `RecoilAdditiveAnimation`；主动画图比较 `SourceRecoilMagnitude` 与上一帧数值，把递增触发写入 `bRecoilMagnitudeIncreasedThisUpdate`，Base 状态机经主动画实例线程安全入口读取该状态并启动或重播后坐力；依次编译接口、Base 和主动画蓝图，全部通过后保存变更资产；PIE 期间拒绝修改。
- `set_animation_sequence_preview_meshes`：只处理显式提供的步枪 AnimSequence 路径，校验目标骨架后设置预览网格；默认只预检，不扩大到其它同骨架动画资产。
- `set_animation_folder_preview_meshes`：只接受 `/Game/BBBC_UA/Animation/Lyra`，校验骨架后设置其子目录中的 AnimSequence 与 AnimMontage 预览网格；默认只预检。
- `build_weapon_animation_graph`：在武器 AnimBlueprint 中重建无状态的参考姿势、开火求值器、换弹求值器和布尔混合图，动画时间与激活状态只读取装备动画事实。

实现文件位于 `Scripts/BBBAnimationMigrationToolset.py`。`Content/Python/init_unreal.py` 只负责在编辑器启动时将该工具集注册到官方 MCP 服务器，不提供自定义网络服务。

## 无界面编辑器与 PIE 自动验收

`capture_pie_character_pose(camera_offset, file_name, width, height)` 在 PIE 世界创建临时 SceneCapture，围绕本地角色渲染 PNG 到 `Saved/Diagnostics/StopPoseCaptures`，结束后销毁临时 Actor。它需要开启渲染，不能用于 `-NullRHI`；视觉验收时先关闭隐藏宿主，再使用唯一带窗口的官方 MCP 编辑器。`CaptureViewport` 仅捕获编辑器世界，不能替代 PIE 角色截图。

只能使用 UE5.8 官方 `ModelContextProtocol` 插件。禁止通过自定义 Socket、stdio 或 headless MCP 服务替代它。

编辑器未运行时，先在 PowerShell 执行：

```powershell
& E:\BBB_Evac\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1
```

脚本只会复用当前项目的 `UnrealEditor.exe`，或以 `-ModelContextProtocolStartServer -NullRHI` 启动一个隐藏窗口的 UE5.8 编辑器；随后等待 `http://127.0.0.1:8000/mcp` 监听，并输出 PID 与端点。脚本不会关闭已有编辑器，不会启动自定义服务。

编辑器可用后，固定使用以下官方 MCP 调用顺序：

1. `EditorToolset.EditorAppToolset.StartPIE`，参数使用 `bSimulate=false`、`playMode=PlayMode_InViewPort`。
2. `Game.Scripts.BBBAnimationMigrationToolset.BBBAnimationMigrationToolset.run_pie_input_sequence`，传入 `schemaVersion=2`、`timingMode="game_frames"` 的 `steps_json`。
   输入序列只预检 Move、Look 和各步骤实际启用的 held/pulse Action；未配置且未使用的 Dash、Slide 等动作不阻止移动场景复现。释放时只对已配置的 held Action 注入零值。
   移动档位仅接受 `held.run` 蹲伏仍使用 `held.crouch` 不再接受 `held.walk` 或 `held.sprint`
3. `get_pie_input_sequence_status`，确认 `finished=true`、`releaseAck=true` 与 `totalInjectedFrames`。
4. `probe_pie_character_animation_runtime`，读取主动画层、链接层、状态机、播放器时间和权重。
5. `EditorToolset.EditorAppToolset.StopPIE`。

对照 UE5.8 Lyra 原版修复斜向停步时，可调用 `Game.Scripts.BBBAnimationMigrationToolset.BBBAnimationMigrationToolset.restore_lyra_stop_pose`，参数是目标 Base 动画蓝图路径。工具只在上一轮新增的四节点方向扭曲链及停步角度捕获链完整时执行：恢复 SequenceEvaluator→LayeredBoneBlend→Root，删除 `StopLocomotionAngle`，编译并保存。结构不符会报警并拒绝删除。

停步选片必须与进入 Stop 前的移动档位一致。Lyra 原版用持续的 ADS 状态选择 ADS/Walk 动画组；本项目由 `FBBBCharacterLocomotionSystem::ResolveGait` 将 ADS 瞄准意图映射为 Walk，并在非 ADS 松开移动输入后、水平制动尚未结束时保持 Run/Sprint 档位。这样现有 `SetUpStartAnim`、`FullBody_CycleState`、`SetUpStopAnim` 都继续读取同一个 `IsWalking` 事实。PIE 验收应核对非 ADS Jog Cycle→Jog Stop 与 ADS Walk Cycle→Walk Stop，不能仅以蓝图编译成功为准。

`start_locomotion_runtime_probe` 的 JSONL 还会读取 pelvis、左右 thigh 的最终世界旋转；PIE 网格仅在运行时切换为 `AlwaysTickPoseAndRefreshBones` 以确保 `-NullRHI` 宿主的骨骼采样有效，不保存网格属性。

不要只检查 MCP 外层请求是否成功。每个项目工具的 `returnValue` 都必须解析，若内层 `error` 非空或输入序列未完成，则该次验收失败。

常用 `steps_json` 场景：

```json
{
    "schemaVersion": 2,
    "timingMode": "game_frames",
    "runId": "unarmed_stop",
    "steps": [
        {"frames": 30, "held": {"move": [0, 0], "look": [0, 0]}},
        {"frames": 180, "held": {"move": [0, 1], "look": [0, 0]}},
        {"frames": 180, "held": {"move": [0, 0], "look": [0, 0]}}
    ]
}
```

上例用于 Stop。每个 `held` 必须同时包含 `move` 与 `look` 二维数组。蹲下立即反向时，将前进与后退段的 `held.crouch` 都设为 `true`，不插入空输入帧。持枪场景使用 `{"frames":1,"held":{"move":[0,0],"look":[0,0]},"pulse":["equip_slot_1"]}`，等待 120 游戏帧，再保持前进 240 游戏帧。

距离匹配断线修复入口为 `Scripts/Animation/P5_RestoreUADistanceMatching.py`。它只接受 `/Game/BBBC` Base 为结构参考，只修改 `/Game/BBBC_UA` Base 中 `UpdateStartAnim` 和 `UpdateStopAnim`，执行前拒绝 PIE，执行后编译并保存目标蓝图。

## 当前关卡编辑

`Game.Scripts.BBBLevelEditingToolset.BBBLevelEditingToolset.break_level_instance_to_current_level` 调用 UE5.8 官方 `ULevelInstanceSubsystem::BreakLevelInstance`，将指定 Level Instance 的内容拆解到当前持久关卡，并可保留原目录结构。工具不自动保存当前地图；执行后需要在编辑器中确认结果并手动保存。

实现文件位于 `Scripts/BBBLevelEditingToolset.py`，底层编辑器库函数位于 `Source/ABBB_EvacEditor/Public/BBBBlueprintEditorLibrary.h` 与 `Source/ABBB_EvacEditor/Private/BBBBlueprintEditorLibrary.cpp`。

## 移动动画运行时探针

`Scripts/ProbeScripts/probe_locomotion_sync_runtime.py` 用于 PIE 下只读采集当前 Lyra 移动动画链。通过编辑器 Python 或 MCP 执行该脚本后，探针会自动启用 `bbb.Animation.LocomotionProbe` 和原生 `LogAnimMarkerSync`。

探针同时输出：

- `Saved/Diagnostics/BBBLocomotionRuntime.jsonl`：移动组件、主 AnimBP、Linked Layer、状态机、播放器与同步组的逐帧数据。
- `Saved/Diagnostics/BBBLocomotionFeet.csv`：角色位移、动画位移速度、骨盆和左右脚最终世界位置及滑动速度。
- `Saved/Logs/ABBB_Evac.log`：`BBB_LOCOMOTION_FRAME`、`BBB_CHARACTER_ANIMATION_FACTS`、`BBB_ANIM_GRAPH_VALUES`、`BBB_FINAL_POSE`、`BBB_LINKED_LAYER` 和 `BBB_ANIM_PLAYER` 原生日志。

状态机、同步组和播放器由真正承载移动图的 Linked Layer 采集；角色精确步态、瞄准、开火、换弹与 IK 有效性由主动画实例的线程安全事实快照采集。

在编辑器 Python 控制台执行 `builtins.BBB_LOCOMOTION_SYNC_PROBE_STOP()` 可停止探针并恢复日志级别。该探针不修改或保存动画资产。

## IK 脚轨道修复

`capture_pie_character_pose` 的原生辅助函数 `UBBBBlueprintEditorLibrary::SpawnTransientPIEActor` 只允许在游戏线程和 PIE 世界创建临时 Actor，失败时触发诊断。截图工具在 `finally` 中销毁临时 SceneCapture2D，不保存关卡；需要启用渲染的唯一可见编辑器宿主。

`audit_ik_foot_tracks` 与 `rebuild_ik_foot_tracks` 都必须提供 `mesh_path`，使用实际运行网格和运行时平移重定向规则采样。骨骼名比较遵循 UE 的不区分大小写规则。`probe_animation_component_poses` 默认启用 `should_retarget`，可显式关闭以区分原始轨道与运行时重定向的误差。

IK 重建通过网格查询真实父骨名，使用 FK 脚组件变换相对于父骨组件变换计算 IK 局部轨道。不能使用 `AnimPose.set_bone_pose(..., WORLD)` 推导局部轨道：UE5.8 此实现直接用骨架父索引索引姿势数组，在网格与骨架骨骼顺序不一致时会引用错误的父变换。重建后先验证再保存。

`audit_ik_foot_tracks` 的报告写入 `Saved/Diagnostics/BBBAnimationIKTrackAudit.json`。当重定向后的 `ik_foot_l / ik_foot_r` 停留在参考姿势时，Stride Warping 会把正确的腿部 FK 姿势拉向错误目标，从而产生原地踏步。

`rebuild_ik_foot_tracks` 只接受明确的 AnimSequence 路径。工具会先在内存中生成全部关键帧，再原位覆盖左右 IK 脚轨道；不复制兼容资产，不修改通知、曲线、Sync Marker、Root Motion 和状态机。加法动画会被拒绝，防止错误改写其局部差值。

## UA 骨架与接口迁移

- `copy_animation_skeleton_metadata(source_skeleton_path, target_skeleton_path, target_to_source_bones)`：只修改目标骨架，按骨名复制混合描述文件、虚拟骨骼、插槽及蒙太奇分组。UE4 脊柱映射使用 `spine_01:spine_01, spine_02:spine_03, spine_03:spine_05`。目标不存在的虚拟骨骼端点或插槽骨骼会报警并返回失败。
- `rebind_animation_blueprint_interface(blueprint_path, source_interface_path, target_interface_path)`：替换 `ImplementedInterfaces` 的接口类，保留现有动画覆盖图；节点内 `Interface` 引用需同步修改。
- `UA_RepointRefs.py`：先 `APPLY=False` 输出 `Saved/UA_RepointPreview.json`；节点通过完整对象路径去重，结构体使用 `export_text/import_text`，类默认值通过官方 `ToolsetLibrary` 枚举与回读。禁止用 `consolidate_assets` 替换引用。
`remap_animation_blueprint_class_references(blueprint_path, class_paths)`：在目标蓝图及所属图对象内统一替换类引用，包含转换节点、函数返回类型及引脚类型；用于避免复制动画层后仍转换到旧主蓝图而导致运行时读取失败。


### 运行时动画实例检查

运行时采样不得调用 `TickPose` 或 `RefreshBoneTransforms` 不得更改网格可见性求值策略 两个原生探针只等待已经存在的并行求值任务并读取结果 `frame` 使用游戏更新计数 `GFrameCounter` 而非渲染计数

逐帧探针通过 `native_runtime` 保存完整原生快照 主状态读取主动画实例的真实状态机 不猜测索引或沿用已删除的步态接口 `camera` 记录同一回调内玩家相机管理器实际使用的位置与旋转 停止时恢复探针准备阶段的网格求值策略 同步组详细信息仍由原生 `LogAnimMarkerSync` 日志提供

`probe_animation_instance_runtime` 拒绝默认对象 模板对象及外层不是骨骼网格的实例 避免无效对象在获取所属网格时触发强制转换崩溃

`probe_pie_character_animation_runtime` 的 `skeletalComponents` 包含 `leaderPoseComponent` `tickGroup` `visibilityBasedAnimTickOption` `enableUpdateRateOptimizations` 和组件世界变换 用于核对可见身体与隐藏主网格的实际更新关系

离屏动态测试应在开始采样前显式设置被测网格的求值策略 并在测试结束时恢复或销毁 PIE 世界 不能在每次读取时主动推进动画 使用旧版主动推进探针生成的时序数据不得用于证明运行时更新正确 持续移动测试必须确认路线未碰撞障碍物

### 二零二六年十月二日相机跟随时序验收

本机 UE5.8 `Engine/Source/Runtime/Engine/Private/LevelTick.cpp` 先运行 `TG_PostPhysics` 然后调用 `UpdateCameraManager` 最后才运行 `TG_PostUpdateWork` 和 `TG_LastDemotable` 相机 Actor 与 SpringArm 若在最后一组更新 玩家视图会缓存上一帧相机位置

项目相机与 `CameraBoom` 已改为 `TG_PostPhysics` 保留 CMC 到相机以及相机到 SpringArm 的已有依赖 不移动装备更新 不新增游戏接口 镜头贡献仍读取最近已发布的装备快照 初始化检查四个 TickGroup 与 EndTickGroup 防止蓝图覆盖后重新出现延迟

开启渲染的无障碍持续右移测试中 修复前两百七十五个稳定样本的相机横向偏移为四十二点九五六至四十五厘米 配置值为五十厘米 修复后六十帧率的两百五十八个稳定样本均为五十厘米 三十帧率无武器测试的两百六十八个移动样本也均为五十厘米 其中八十八个为蹲伏移动 两组完整相机偏移均保持配置值负三百三十 五十 六十五厘米 输入序列全部完成并确认释放

稳定移动动画播放器的时间推进与声明速率一致 主动画事实与角色位置一致 可见身体组件变换与主网格一致 不据此修改循环同步组或身体跟随逻辑 本次结论证明已定位的一帧相机滞后被移除 不代表已完成用户显示器上的主观视觉验收

`probe_animation_instance_runtime(instance_path)` 接受 PIE 动画实例对象路径，返回状态机名称、状态时间及活跃播放器资产、时间、权重。原生端先等待并行动画计算完成，再按实际节点类型读取；禁止通过猜测状态机索引调用 GetCurrentStateName。持续 UA 测试通过 `run_editor_script` 执行 `Scripts/UA_RuntimeProbe.py`。


`remap_animation_sequence_notify_classes(animation_path, class_paths)` 原位替换 AnimSequence 中的通知实例类，保留通知时间、持续时间、轨道及实例属性。`Scripts/UA_RepointNotifies.py` 先从 BBBC 原动画复制通知，再将 BBBC 通知类替换为 UA 对应类，避免状态判断与通知实例类型不一致。

## 持枪后坐力图表工具

- `submit_character_diagnostic_inputs` 只在 PIE 向本地角色正式输入入口提交固定诊断包 请求为含 `name` 与三维 `value` 的数组 `Camera` 使用三轴冲量 `Unequip` 使用零向量 `AimFact` 使用 X 作为瞄准标记 `AimImpulseFact` 使用 X 腰射冲量 Y 瞄准冲量 Z 回零速度 多项在同一回调提交 可检查槽位覆盖与权威事实包读取 已由原生端限制到 PIE 游戏线程
- 持枪运行探针额外返回逐帧样本与相机 Actor 实际角度 可对照武器开火序号检查响应时序及回零曲线 不读取相机私有状态 动画图仅读取独立的 `HipFire` `AimFire` 与 `Airborne` 表现字段 不再读取整份冲量配置

- `sample_weapon_handling_runtime` 的 `start` 与 `status` 记录角色角度冲击 动画层跟随速度 后震权重 世界手部位置 武器开火序号和镜头角度 `equip` 只在 PIE 中创建现有装备注入调试演员 不保存关卡

- `render_asset_thumbnails` 请求项可设置 `diagnostic_only=true` 只输出网格 PNG 不导入纹理 不修改资产 `yaw` 用于选择辨认模型所需角度 诊断图片验收后删除

- `create_backward_additive_animation` 从指定持枪动画首帧新建局部空间加法动画 通过右臂双骨旋转让右手向后移动 保持骨段长度与手部朝向 末帧返回基准姿势 目标路径已存在时拒绝覆盖
- `configure_weapon_handling_graphs` 根据步枪动画快照重建持枪表现函数 默认用于角色基础动画层 `camera=true` 用于相机蓝图 `ReadRecoilSource` 函数
- 角色图选择腰射或瞄准设置 再叠加空中倍率 用武器快照时间计算摇摆 用最近开火经过时间求值后震动画 不再根据角度大小增加推测是否开火
- 相机图只读取武器动画快照 自行选择镜头冲量 角度上限和回正速度 不依赖步枪玩法黑板
- 图表工具仅编译不保存 必须先签出资产 调用后检查编译结果再显式保存
- 原生辅助接口 `BindAnimationNodeInput` 用于暴露动画节点输入并绑定属性路径 `ConfigureTimedAdditiveLayer` 用于重建按外部时间求值的非循环加法层

## IK 重定向链配置

通过 `Game.Scripts.BBBExternalToolset.BBBExternalToolset.retarget` 调用以下动作：

- `set_retarget_chain_bones`：修改已有 IK 链的起止骨骼，保存前回读核对；链不存在或回读不匹配时返回失败。
- `set_retargeter_source_ik_rig`：替换重定向器的源 IK Rig。`chain_mappings` 使用目标链名称到源链名称的映射；未显式指定的有效旧映射会保留，指定映射会逐项回读核对。

调用时必须解析 `returnValue` 内层 JSON，并确认 `success=true`。写入配置前应先读取两侧 IK Rig 的链边界，确认所需链名与骨骼存在；写入后再读取 IK Rig 和重定向器配置进行复核。
