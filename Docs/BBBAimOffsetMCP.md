# 原生 AimOffset 构建与接入

`animation_graph.create_aim_offset_from_template` 接收只读原生 AO 来源 新目标路径与按源采样顺序排列的同骨架 Mesh Space 序列。目标只能位于 `_Project` 且不得存在。工具沿用原二维布局并关闭附加输入平滑 保存后回读骨架与样本。第三方来源与动画轨道不变。

`animation_graph.configure_aim_offset_layer` 将已有 X 上下 Y 左右二维变量接入公共骨骼控制层之前的腰射 瞄准 下蹲三个 AO 加法采样。轴连接为 X 到 Pitch 和 Y 到 Yaw。先选择加法结果 再通过唯一 Apply Mesh Space Additive 与原基础姿势合成一次 并沿用既有控制节点的有效权重。禁止把同一姿势输出直接分接到多个节点。明确重命名旧函数与变量并移除已从原生控制结构删除的旧输入 不保留兼容入口。既有蒙太奇和双手握持链不重建。

`animation_graph.override_aim_offset_layer` 使用 UE 原生父节点资产覆盖为直接继承层选择三份 AO 不复制公共图。覆盖依赖公共图三个 AO 的从上到下顺序 应先完成子层覆盖再重新排版公共图。

依赖项目 `BBBAimOffsetEditorLibrary` 的最新编译模块。编辑期间拒绝 PIE 目标脏包和并行写入。配置后必须无警告编译并保存回读。构图成功不代表射击手感通过。

角色当前后坐力只通过 `GetRecoilAngles` 读取已发布快照。`sample_weapon_handling_runtime` 的 characterOffset 列表示该姿势驱动值 aimOffset 列表示图表合成的后坐力与摇摆 不是 AimIK 的目标偏移。
