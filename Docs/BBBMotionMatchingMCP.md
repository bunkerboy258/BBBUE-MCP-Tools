# Motion Matching 编辑工具

完整参考配置的检查 依赖映射 Chooser 条目及标准 MM 内部图迁移见 [运动匹配配置检查与迁移](BBBMotionMatchingConfigurationMCP.md)。该入口支持接入参考 CMC 系统的场景轨迹碰撞处理。

`BBBMotionMatchingToolset` 通过 UE5.8 标准 Pose Search 构造动画数据库与动画图。仅允许明确的 `/Game/_Project` 目标。预览不修改资产 正式应用编译 保存并回读。

- `motion_matching.create_schema` 创建单骨架格式 包含轨迹位置 速度 朝向和指定骨的姿态位置 速度通道。
- `motion_matching.create_database` 使用完整且骨架一致的序列列表创建数据库。重建已有数据库必须显式传入 `replace_existing=true`。原生接口等待索引构建完成并检查实际姿态数量和维度。
- `motion_matching.inspect_database` 回读格式 完整动画列表和原生索引状态。
- `motion_matching.configure_database_provider` 在基础动画层构造纯函数 `SelectMMDatabases`。派生层提供站立 蹲姿 上升 下落 落地五组数据库。调用者提供四个查询上下文布尔值。
- `motion_matching.configure_main_updates` 构造主线程 `UpdateMMDatabaseContext` 与线程安全 `UpdateMotionMatching`。装备层引用转换和候选库读取在主线程完成。轨迹使用移动完成后的值快照 在线程安全主更新入口生成。主 MM 节点清空固定数据库。已有 `GetFootPlacementAlpha` 保留原权重计算 并增加地面事实门控 防止普通跳落继续贴地。
- `motion_matching.collapse_animation_states` 在明确状态机内合并普通状态和导管。删除内部转换 保留外部转换规则与优先级 重连入口和别名。含歧义的混合别名转换会被拒绝。
- `motion_matching.replace_motion_matching_pose` 仅替换闭合且明确的旧姿态分支 创建标准 MM 和 Pose History 绑定外部 TransformTrajectory 和已有线程安全回调。快照检查防止编辑过期图。
- `motion_matching.inspect_animation_blueprints` 返回图 函数调用 变量 属性存取路径和动画节点回调摘要 用于清理前核对实际引用。
- `motion_matching.cleanup_animation_blueprints` 按明确蓝图列表和结构化请求删除图 旁路执行或姿态节点 清除无连接别名及指定变量。修改全部完成后统一编译 保存。

创建的原生轨迹桥只使用输入快照和调用方持有的历史。不读取角色对象 不修改移动组件 不拥有网络状态。地面预测使用稳定 PoseSearch API 空中预测使用当前速度和重力的弹道位置。不调用实验性世界碰撞或 Mover 堆栈。

工具编译通过和索引就绪仅代表工程完整性。实际动画衔接 脚滑和操作手感由用户在可视编辑器验收。

资产移动持久化会跳过引擎已经保存且当前无脏标记的包 避免为大批动画重复序列化。目标文件缺失或仍为脏包时仍需原生保存 原包删除继续核对引用和实际文件。

## 角色蒙太奇与普通运动职责

`motion_matching.configure_character_montage_graph` 接收 `main_path` 与 `dry_run`。只编辑明确的自有主动画蓝图 默认预检 正式执行拒绝脏包和 PIE。

原生入口保留现有普通 MM 及其内部动画图 不修改 Unarmed 数据库或装备层。删除倒地和起身的三份 Sequence Evaluator 与四份生命姿态混合 删除六个专用混合与脚部变量 删除线程安全更新中的阶段计时和恢复打断计算。帮扶不再改写 MM 选择器 根骨模式保留实际 FullBody 槽位活动判断。

FullBody 槽位从装备处理链内移到最终惯性化之前 并开启持续更新源姿态。普通 MM 继续经过公共根骨 脚部 Pose History 和装备处理 所有生命动作由后置全身蒙太奇覆盖。倒地等待为蒙太奇循环 接受救援和站蹲起身为独立蒙太奇 不支持倒地移动。

完成救援由被救角色蒙太奇中的逻辑通知向直接角色提交完成输入 处理器核对操作和倒地轮次后产生生命结果。计时只用于进度显示 不得作为成功替代路径。动作根运动使用引擎 Disable Root Motion 通知屏蔽 不改变 CMC。

应用后主图必须严格无警告编译并保存。构图或编译失败禁止保存 检查 BBBCharacterMontage 日志。旧 consolidate_character_base_pose 入口已删除 没有别名或旧图重建路径。工具边界测试为 Tests.test_character_base_pose 动态表现由用户验收。
