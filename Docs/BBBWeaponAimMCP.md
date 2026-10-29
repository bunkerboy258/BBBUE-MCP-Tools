# 连续举枪加法工具

`animation_graph.create_weapon_aim_additive` 接收只读 `neutral_path` 与 `target_path` 以及不存在的自有 `asset_path` 和 `reference_path`。静态参考保留中性动作零帧且清除曲线 避免直接引用 MM 动作导致脚部曲线被减去。加法仅复制目标零帧 `spine_01` 分支的旋转。全部位置和缩放及分支外旋转保持中性。两键静态 Local Space 加法不带曲线 通知 同步标记 属性或根运动。保存前求值确认曲线增量为零 原输入序列不改写。

`animation_graph.configure_weapon_aim_additives` 接收 `base_path` `layer_paths` `stand_paths` `crouch_paths` 与 `dependent_paths`。目标必须是已有 `FullBodyAdditives` 及 `WeaponAimStandAdditive` `WeaponAimCrouchAdditive` `WeaponAimAlpha` 和 `UpdateWeaponAimData` 声明的公共装备层。各类素材与直接子层一一对应 其余依赖子层按父层在前排列。所有写入路径必须唯一。

原生构图验证既有七节点后震层和唯一基准连线。保留原节点 在后震之前插入两份静态求值器 站蹲选择及独立权重的局部空间加法 共增加八节点。主图和层接口没有新增调用。具体子层仅提供站蹲素材引用。

`UpdateWeaponAimData` 在工作线程内制造举枪权重及独立的 `LocomotionAimIKAlpha`。瞄准 持续开火或最近发射后 0.5 秒提供举枪意图 跑步及 `UpperBody` 或 `FullBody` 离散动作覆盖时退出。加法开火与受击槽位不阻止举枪 瞄准跟随允许正常腰射 不与举枪权重捆绑。代码只读事实不增加玩法或网络状态。

写入前检查 PIE 未保存编辑 继承关系 骨架与局部空间加法类型。全部引用者无警告编译后保存。工具不会启动 PIE 动态验收由用户执行。新动画序列按项目版本规则作为本机美术依赖保存。

## 稳定端枪姿势

animation_graph.configure_stable_aim_pose 接收公共装备层、直接子层与其余依赖子层路径。在 FullBody_SkeletalControls 的 AimIK 输入前，现有站立和蹲伏静态参考加举枪加法组成绝对端枪姿势，通过 spine_01 渐进分支混合到 MM 输入姿势；骨盆和腿保留基础姿势。权重使用 WeaponAimAlpha，曲线取基础姿势。工具读取各子层加法素材的静态参考，编译并保存目标蓝图，不运行 PIE。

2026-10-29 切枪端枪覆盖修复：稳定姿势权重同时检查站立/蹲伏加法与参考四份素材；动作槽接管、无枪口或素材失效时立即归零，正常瞄准转换保留渐变。configure_stable_aim_pose 可重建既有配置的权重函数，不重复添加姿势节点。实际保存六份蓝图，磁盘重载后 BS_UpToDate，权重图回读含两份参考有效性检查和立即归零选择。未运行 PIE，动态切枪由用户复查。
