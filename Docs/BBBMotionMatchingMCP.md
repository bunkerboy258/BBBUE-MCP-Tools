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

## 角色基础姿态收敛

`motion_matching.consolidate_character_base_pose` 接收 `main_path`、`base_layer_path`、`ground_pose_path`、`recovery_stand_path`、`recovery_crouch_path`、`helping_chooser_path`、`ground_pose_time` 与 `dry_run`。前三条序列必须与主图及基础层同骨架，地面采样秒数必须落在序列范围内。默认只读预检，正式执行要求明确目标可写且没有其他未保存编辑。

原生入口保留普通运动 MM、Offset Root、Foot Placement、Leg IK 和 Pose History。地面静态采样与站立或蹲姿恢复先与普通 MM 汇合，再进入公共根骨和脚部处理以及 `BasePose` 缓存。帮扶事实选择明确的空手 GASP 选择器及其蹲姿数据库。地面与恢复阶段释放根骨偏移并禁用贴地；地面、恢复和帮扶期间绕过装备姿态修正，最终统一惯性化输出。

角色只发布当前生命阶段、上一阶段、阶段经过秒数、移动输入和速度等事实。工作线程蓝图派生是否使用地面或恢复姿态。恢复被移动输入、实际速度或帮扶打断后，在本次恢复内保持打断；不会松开输入又重播起身。倒地为静止等待，不提供四向爬行。死亡物理表现仍由现有角色系统接管。

工具删除旧攀爬选择函数、Traversal 槽和倒地数据库分支，不保留兼容入口。主图和基础层全部无警告编译后才仅保存这两个目标。构图或编译失败不保存，需检查 `BBBBasePose` 日志与现场节点。它不写源序列、不接管玩法、不触发版本控制操作。单次构图用于明确的旧图收敛，不重复重建已完成的主图。

独立边界回归为 `Tests.test_character_base_pose`。真实表现仍需对保存后的主图执行 PIE，检查普通移动、静止倒地、救援蹲姿、起身结束与输入打断，单节点预览不能替代运行时验收。

本轮起身使用目标骨架上由 GASP 站立起身前 76 帧和蹲姿起身前 46 帧裁出的单次片段，分别为 2.5 秒与 1.5 秒。源动作保留，正式片段开启根运动读取与首帧锁根，运行时继续仅蒙太奇驱动根运动。静态倒地采样站立恢复片段第 0 秒，以便与恢复起点衔接。
