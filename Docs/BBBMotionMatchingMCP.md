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
