# 持枪运动承重构图

`animation_graph.configure_weapon_locomotion_weight` 在已有角色 MM 和公共装备层上构造承重表现 不执行 PIE。必须指定 main_path base_path layer_paths dependent_paths 以及逐层一一对应的 carry_support_weights motion_pitch_degrees motion_yaw_degrees。

全部目标为自有动画蓝图 路径唯一且子层父类按顺序已在本次范围内。支撑权重范围为 0 至 0.4 俯仰范围为 0 至 2 度 侧向范围为 0 至 1.5 度。transition_blend_time 与 cruise_blend_time 默认分别为 0.18 和 0.28 秒 要求 0.12 <= transition <= cruise <= 0.4 且所有值有限。

工具在 Base 声明七个蓝图字段 通过项目编辑器库提供中文显示名。三个配置字段为 WeaponCarrySupportAlpha WeaponMotionPitchDegrees WeaponMotionYawDegrees。其余为上帧速度 上帧观察旋转 当前响应角及初始化标记。原生角色类没有新增派生字段。

UpdateWeaponAimData 以水平速度制造地面移动的最小持枪支撑 权重由子层配置。新 UpdateWeaponWeightData 在其后执行一次 以真实速度差和观察偏航差制造限幅的俯仰与侧向反应 加入现有 WeaponPoseOffsetAngles。首次采样 长帧 切换装备 跑步 腾空及离散动作均有初始化 限幅或退出处理。瞄准和蹲伏缩小幅度。

Get_MMBlendTime 只在 MovementMode_LastFrame 的原连续地面返回值前加入持枪选择。起步 急转或制动使用 transition_blend_time 其余持枪地面使用 cruise_blend_time 非持枪与空中保留原返回值。

工具保留主姿态图与原有加法 骨骼修正 握姿和后坐力计算图 并在保存前比较逻辑签名。所有引用者必须无警告编译通过后保存。已有 UpdateWeaponWeightData 时拒绝重复构造 后续直接编辑子层的三个配置值即可。工具不覆盖原始动画 不新增素材或备份图。

`animation_graph.configure_weapon_aim_additives` 的共享举枪声明同步包含默认零承重配置 因而新建装备层仍从零承重开始。只有本工具明确设置的子层启用对应幅度。
