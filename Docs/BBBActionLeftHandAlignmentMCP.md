# 动作左手握持基准

通过 `control_rig.process_dual_arm_body_pose(action="finalize")` 处理正式 `_RetargetActions.json.source`。配置必须显式指定 `reference_space: "hand_r"`、`reference_animation`、`left_hand_rig`、`target_mesh`、`blend_curve` 与明确输出项；`write_paths` 可以选择本次已批准的输出子集。

参考动画第零帧的 hand_l 相对 hand_r 变换是唯一握持目标。每帧按原曲线计算动作权重，曲线零使用握持目标，曲线一保留原动作。使用现有左臂 Control Rig 求解并同步 ik_hand_l，不改根、身体、右臂、曲线、通知或动画设置。拒绝缺少曲线的离散动作及加法动画；公共持枪参考可显式设置 `constant_reference: true`。

动作项的 `authoring_input.source_recipe` 指向当前正式 ManualAction 制作源。工具在瞬态归属中原生求值 LS，从当前有效人工制作恢复左臂轨迹与手指局部旋转；手指不参与握持基准混合。手指来源与 LS 的有效人工偏移均保留。目标、原曲线、制作输入和参考动画摘要一并记录；重复请求不叠加修正，发现外部修改后拒绝静默重做。

写入前在瞬态候选上核对逐帧握持目标、非目标骨轨、元数据及手指来源，成功后才原位写入并保存。临时对象清除，不建立磁盘备份或备用动画。

分段动作的指骨接缝通过现有 ManualAction `prepare_action` 独立处理：`restore_action_fingers_request` 显式设置 `seam: true`、`bone_names`、`animation`、`reference_frame`、`frames` 和 `preserve_frames`。仅向当前 LS 的所选指骨旋转加法通道写入接缝与保护锚点；参考段 LS 不写入。瞬态原生导出先验证接缝及保护锚点，再核对其余通道的完整键值、默认值和切线摘要。该步骤独立于左手位置对齐，必须由调用者明确选择。
