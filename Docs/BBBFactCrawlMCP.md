# 事实驱动的持续爬行构图

`BBBAnimationGraphToolset.configure_fact_crawl_states` 为当前 `FactDrivenActions` 动画图配置姿势分支。玩法仍由 Mass 行为与移动事实维护。

参数:

- `asset_path`: 已按 binary+l 独占签出的事实动画蓝图。
- `sequence_paths`: 六个同骨架序列 按倒地 待机 警觉 移动 攻击 死亡排列。
- `blend_duration`: 0 到 0.5 秒 不包含零 默认 0.18。

父类必须提供 `CrawlingFact` `CrawlProgressFact` `BehaviorFact` `MovementSpeedFact` `ActionProgressFact`。倒地与攻击按事实进度采样。爬行移动按实际速度相对 75 cm/s 调整播放率。死亡固定采样最后一帧且没有状态出口。未找到专用爬行死亡动画时必须提供明确的伏地终姿序列 不得使用恢复站立的动画。

工具拒绝 PIE 拒绝已有爬行分支 拒绝无效参数 骨架或非当前图。所有验证通过后编译并保存。重新构图时先使用现有 `rebuild_fact_driven_state_machine` 干净重建站立事实图 再配置变体和爬行 不保存历史兼容分支。

`BBBAnimationGraphToolset.inspect_mass_scene_population` 无参数。它只读查询当前 PIE 全部正式小怪及已生成的测试小怪 返回实体编号 演员路径 生命 实际速度 爬行 减速 地面与路径诊断。不创建临时 Actor 强制 LOD 配置 不暂停游戏 不修改资产。原生 `InspectPopulation` 的空实体列表表示查询当前场景小怪。
