# 僵尸台阶与攀爬制作

本组入口只制作并保存资源和静态台沿连接 不启动 PIE 不执行验收。

- `monster_traversal.bake_mantle` 从完整上台原片重定向到指定僵尸骨架 烘焙僵尸首尾站姿 双手接触窗口按原片长度明确计算 输出序列及蒙太奇。只写明确的两个自有输出。
- `monster_traversal.configure_assets` 接收明确的逻辑配置 表现配置 动画蓝图与两个动作序列。核对表现配置实际动画蓝图与写入范围一致后 设置根锁定与逻辑动作时长 配置动画图中的快速上台和较高攀爬分支及双手 Two Bone IK 编译 保存并回读。多人结果由运行时代码复制当前动作 不复制骨骼。
- `monster_traversal.build_links(expected_level, spacing=120, minimum_height=35, maximum_height=250, dry_run=true)` 扫描当前关卡静态导航边界 调用与运行时共用的胶囊净空和落点判断 同时制作平台上台与薄墙翻越连接。应用仅重建 `BBB_StaticClimb` 组 保留手工连接 保存关卡并请求导航构建。
- `monster_traversal.inspect_links(expected_level)` 只读返回连接总数 平台连接数 翻墙连接数 当前导航类型和导航是否仍在构建。导航构建完成后仍须保存关卡中的导航数据。

运行时使用原生 Recast 查询和 Detour 动态多边形走廊 Detour 自适应速度采样负责人群与墙边避让 Mass 维护实际碰撞位置和跨障动作进度。查询阶段按当前允许高度与肢体能力排除不合格连接。低台阶继续地面移动 中台快速上台 较高台沿使用攀爬动作。尸群入口和出口按实际身体尺寸短时占用 攀爬失败有重试间隔 入口按等待时刻公平分摊 临近探测复用同一几何判断 不逐只逐帧完整扫描地形。

僵尸仍只有逻辑配置和表现配置两个入口。逻辑配置中的 `Traversal` 控制高度 时长与重试 跨障轨迹依据入口 台沿和出口生成 先抬升 再跨越 最后落地 薄墙不要求顶部能站人。表现配置中的 `Mantle` 与 `Climb` 控制动作 抓边窗口和手掌间距。

人工检查时 `bbb.Monster.Traversal.Draw 1` 显示当前失败原因和活动轨迹 `bbb.Monster.Traversal.Draw 2` 仅显示活动攀爬 `bbb.Monster.Traversal.Draw 0` 关闭。普通导航使用 `bbb.Monster.Navigation.DebugEntity <实体索引>` 显示当前走廊拐点 黄色期望速度 绿色避让速度 白色实际速度和停止原因 传入 -1 关闭。当前只读 Mass 探针返回 desiredVelocity recommendedVelocity neighborCount velocitySamples stopReason 和跨障入口出口。

禁止把资源制作 保存回读或原生编译成功描述为已通过游戏实测。实际通过率 动画观感和尸群性能由本轮用户验收。
