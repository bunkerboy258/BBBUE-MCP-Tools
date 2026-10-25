# 动作匹配运行时探针

适用于当前 PIE 本地玩家的标准 Motion Matching 与 Pose History。原生 `BBBMotionMatchingEditorLibrary.ProbeMotionMatchingRuntime` 只等待已有并行求值结束 不推进动画 不修改角色或资产。

调用 `motion_matching.start_runtime_probe` 并明确本任务 `file_prefix`。`duration_seconds` 为 1 到 120 秒 默认 20 秒。`sample_interval` 为 0.05 到 1 秒 默认 0.1 秒。报告仅写入 `Saved/temp/<file_prefix>/MMRuntime_<时间>.jsonl`。拒绝路径穿越和重复启动。

`motion_matching.inspect_runtime_probe` 返回状态 样本数 活跃序列计数 方向误差均值与 P95 以及最新快照。`motion_matching.stop_runtime_probe` 注销回调并关闭文件。时限到达 PIE 结束或原生采样失败时自动收尾。暂停期间不重复记录同一游戏时间。

快照包含角色 网格和根骨朝向 世界与角色及网格空间速度 当前输入 加速度 主蓝图生成轨迹 Pose History 实际轨迹 MM 命中数据库与序列 命中时间 代价 镜像 播放速率和权重。命中序列额外采样原始根轨迹 计算根局部与世界空间速度。两侧速度均超过 50 cm/s 时给出方向夹角。

方向误差用于定位查询与动画坐标是否一致。起停 转身和过渡姿态可能暂时产生较大误差 须结合输入阶段 轨迹和实际姿态判断。不能仅凭一个总均值判定视觉验收通过。

使用 `animation.run_pie_input_sequence` 的 `schemaVersion:2` 在游戏帧中注入明确四向输入。先采集修复前报告 再在相同配置下采集修复后报告。完成后仅清理本任务目录 不删除并行采样。

2026-10-25 工程复现: 目标动画前进根轨迹为网格 +Y 左移为网格 +X。错误实现把角色世界旋转写入 `FPoseSearchTrajectoryData::FDerived::Facing`。角色 yaw 为 0 且网格 yaw 为 -90 时 生成和历史轨迹 yaw 错误地成为 0 导致前进命中左移动画 后退命中右移动画。修复为使用本帧网格世界旋转 不写固定角度补偿。

空手四向中速度大于 100 cm/s 的样本平均方向误差: 前进 88.44 到 1.11 度 后退 90 到 0 度 左移 90 到 0 度 右移 90.30 到 0 度。步枪四向 连续反向和视角转动共 750 个注入游戏帧 无跳过 输入释放确认成功。步枪探针共 349 个样本 符合速度阈值的平均方向误差 0.633 度 P95 为 0.220 度。转动后的角色 yaw 为 15 网格和查询轨迹 yaw 均为 -75。

验证: UE5.8 Development Editor 编译成功。原生 `BBB.Animation.MotionMatching.TrajectoryCoordinateSpace` 测试通过 覆盖三个角色朝向各四个移动方向。23 项 Python 探针及相关 MM 工具测试通过。以上证据验证坐标和方向匹配 起停转身细节及整体观感仍由实际游戏画面验收。
