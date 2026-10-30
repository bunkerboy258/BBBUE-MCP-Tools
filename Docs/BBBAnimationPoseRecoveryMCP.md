# 动画原始骨轨恢复

## 明确幅度的加法重建

control_rig.process_dual_arm_body_pose 的 bake 支持正式 BBBDualArmBodyPose 制作源中的 scaled_additive 任务。明确 source、output、base_animation、source_reference_frame、amplitude 和可选 rotation_space；制作源 mesh 提供同骨架层级。source_reference_frame 为有效原始帧，负一读取有效 ref_pose_seq 及其参考帧；拒绝无效范围、空骨轨、错误骨架、非单位旋转及含事件曲线的输出。rotation_space 为 source、mesh 或 local。

按指定旋转空间提取最短弧变化量，幅度作用于角度和局部位置、缩放差。输出使用当前基准的 Local Space Additive。写后逐帧重建组件姿态核对倍数，检查位移与缩放并保存，制作源记录输出骨轨摘要。零变化必须使用显式单位四元数，不能使用 Python Quat 默认零值。

2026-10-30：14 份现用近战通过原有官方序列烘焙恢复，骨轨各 68，元数据及三条控制曲线保持。3 份原始 Lyra 射击输入重定向并转换至有效当前基准，再生成 14 份三倍专属角色后坐力，逐帧幅度回读通过；无 PIE 动态验收。

入口属于 animation_graph。只处理明确自有资产，通过原位写入保持运行引用，不建立兼容路径或备份资产。

- restore_saved_grip_pose：读取型号 Source/Animation 内已通过的 BBBGripAuthoring 解，仅向缺少原始骨轨的两至三键静态 AnimSequence 写入保存的完整 local_pose。拒绝覆盖非空输出、跨型号来源与不完整制作解。回读位置及旋转后保存。
- restore_animation_bone_tracks：从同骨架、同帧数、同帧率且有原始骨轨的明确源复制到空轨目标，不改目标曲线、通知或加法参考。逐帧回读位置、旋转、缩放后保存。允许公共身体后震源本来不含手指骨轨的情况，不伪造手指运动。
- rebuild_weapon_aim_additive：使用现有 BBBWeaponAimEditorLibrary.build_aim_additive 原位重建已有加法与无曲线参考，拒绝空骨轨输入，保存两个正式目标。

control_rig.process_dual_arm_body_pose 的 bake 在输出已存在但骨轨为空、元数据与制作输入完全一致时，恢复原始输入并继续烘焙已批准控制姿势；非空已有输出仍拒绝覆盖，已记录的输出指纹仍需一致。

正式 ManualAction 原生导出后要求源骨轨非空且全部包含在导出结果内。轨道比较拒绝空预期姿势，避免空集合循环被误报为零误差成功。

稳定端枪配置排除 hand_l/hand_r 分支，脊柱混合不覆盖已经应用的专属腕部及手指姿势。

2026-10-29 实际静态编辑：恢复 14 装备、16 换弹、28 静态握姿、14 后坐力，重建 8 举枪资产和手枪/重物基础姿势。85 份目标磁盘重载回读无空轨；另外 45 份 Lyra AimOffsets 采样重定向恢复后各 68 条骨轨。手枪 49 帧后坐力原有静态求值器通过；公共及五个装备子层编译保存。未执行自动化动态验收。
