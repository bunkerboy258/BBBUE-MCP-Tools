# BBB 关卡编辑 MCP

## 单个演员的持久放置

`level.place_actor_from_class(asset_path, class_path, label, location, rotation)` 只在明确指定且当前已打开的关卡中创建一个原生类或蓝图生成类的演员。`asset_path` 为关卡包路径 同时作为网关写入与保存范围。位置单位为厘米 旋转依次为俯仰 偏航 滚转角度。

工具拒绝 PIE 错误关卡 非有限变换 非 Actor 类和重复标签。成功后核对对象属于持久关卡 并保存该关卡 返回实际对象路径和位置。若返回已创建但保存失败 必须先查找标签核对 不得盲目重放。工具不修改类默认对象 不创建 Mass 实体 不处理项目玩法。

2026-10-16 用于僵尸独立受击调参靶的持久放置。补齐原生场景创建接口缺少关卡范围时的正式替代入口。不绕过资产协调。

`BBBLevelEditingToolset.configure_mass_display_spawners` 在已独占签出的 `/Game/_Project/Maps/BBBTest` 中，将现有 `MassSpawner` 复制为十个独立生成器，并保存关卡。调用前必须核对编辑器项目、当前关卡、Perforce 签出状态，且停止 PIE。

参数：`expected_level` 固定为 `/Game/_Project/Maps/BBBTest`；`source_spawner_path` 是当前关卡已有生成器的完整对象路径；`config_paths` 按展示顺序提供十个不同的 `MassEntityConfigAsset`；`center` 为队列中心的世界坐标；`spacing` 为沿 Y 轴的间距（厘米）；`radius` 为每个生成器的随机半径（厘米）。

工具把每个生成器的数量设为一、启用 BeginPlay 自动生成、绑定一种配置，标签命名为 `BBB_Showcase_Zombie_<变体名>`。重复标签或重复配置会拒绝写入。成功返回十个生成器的对象路径、配置和位置；失败不会自动执行 Perforce Revert。保存后应重新加载关卡并逐项回读配置，再启动 PIE 核对表现。

这项配置只保证每次启动 PIE 时生成十种变体各一只；非 PIE 编辑器视口不会显示运行时 Mass 实体。
