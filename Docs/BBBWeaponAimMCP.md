# 连续举枪加法工具

`animation_graph.create_weapon_aim_additive` 接收只读 `neutral_path` 与 `target_path` 以及不存在的自有 `asset_path` 和 `reference_path`。静态参考保留中性动作零帧且清除曲线 避免直接引用 MM 动作导致脚部曲线被减去。加法仅复制目标零帧 `spine_01` 分支的旋转。全部位置和缩放及分支外旋转保持中性。两键静态 Local Space 加法不带曲线 通知 同步标记 属性或根运动。保存前求值确认曲线增量为零 原输入序列不改写。

`animation_graph.configure_upper_body_pose` 接收 `interface_path` `base_path` `main_path` 与按父层在前排列的 `layer_paths`。它声明 `UpperBodyPose(InputPose)` 动画层接口 并将公共装备层的已有端枪子图移到这个层。主图在上半身加法与动作槽之前调用它 随后继续原有后坐力 握姿 AimIK 和左手贴合。主图本地实现为输入直通 装备公共层提供实际端枪计算。

端枪层按 `spine_01` 深度 5 混合完整上半身 使用根骨空间旋转基准 不再排除手腕。`FullBody_SkeletalControls` 删除原端枪分支 `FullBodyAdditives` 删除重复举枪加法 保留原七节点后坐力计算。旧 `configure_weapon_aim_additives` 与 `configure_stable_aim_pose` 入口已删除。

`UpdateWeaponAimData` 在线程安全蓝图内制造举枪权重。瞄准 持续开火或最近发射后 0.5 秒提供举枪意图 跑步及 UpperBody 或 FullBody 动作槽接管时退出稳定端枪。`LocomotionAimIKAlpha` 独立以速度 10 插值：有效装备有枪口且非跑步或有举枪意图时趋向 1，否则趋向 0；不读取动作槽状态、稳定端枪权重或端枪素材。骨骼控制层仍用动画的 `DisableAimIK` 曲线衰减 AimIK，因此换弹开始不会绕过作者曲线将 IK 直接清零。代码侧不增加玩法和网络状态。

迁移前要求目标无未保存编辑且不在 PIE 检查旧图结构和子图没有外部共享消费者。迁移后检查端枪层 16 节点 后坐力层 7 节点 骨骼控制层 40 节点。所有引用者编译成功且四份端枪素材引用保持不变才保存。该工具从旧图迁移 已完成的结构再次调用只核验并连接同一层 不重复添加姿势节点 不保留旧图运行分支。

2026-10-30 验证: Python 语法与六项工具边界检查通过 原生构建成功 八份动画蓝图编译保存并从磁盘重载 四份端枪素材引用保持不变。主图已核对输入姿势至 UpperBodyPose 再至原有上半身加法的连接。FAL 两轮短回归共 1260 输入帧 未漏步且释放确认 角色后坐力保留 换弹实际播放。低持枪左手目标不可达仍未修复 用户选择先查看当前效果。
