# BBB 关卡编辑 MCP

`BBBLevelEditingToolset.configure_mass_display_spawners` 在已独占签出的 `/Game/_Project/Maps/BBBTest` 中，将现有 `MassSpawner` 复制为十个独立生成器，并保存关卡。调用前必须核对编辑器项目、当前关卡、Perforce 签出状态，且停止 PIE。

参数：`expected_level` 固定为 `/Game/_Project/Maps/BBBTest`；`source_spawner_path` 是当前关卡已有生成器的完整对象路径；`config_paths` 按展示顺序提供十个不同的 `MassEntityConfigAsset`；`center` 为队列中心的世界坐标；`spacing` 为沿 Y 轴的间距（厘米）；`radius` 为每个生成器的随机半径（厘米）。

工具把每个生成器的数量设为一、启用 BeginPlay 自动生成、绑定一种配置，标签命名为 `BBB_Showcase_Zombie_<变体名>`。重复标签或重复配置会拒绝写入。成功返回十个生成器的对象路径、配置和位置；失败不会自动执行 Perforce Revert。保存后应重新加载关卡并逐项回读配置，再启动 PIE 核对表现。

这项配置只保证每次启动 PIE 时生成十种变体各一只；非 PIE 编辑器视口不会显示运行时 Mass 实体。
