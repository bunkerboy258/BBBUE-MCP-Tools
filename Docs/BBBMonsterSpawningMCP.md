# 统一小怪生成

## 编辑资产

`editor.create_monster_director_assets(asset_paths)` 调用项目原生编辑器库创建或更新统一出生资产并保存三个导演定义的阶段引用。参数必须明确包含下列十六个包。已有出生规则保留其可调选点参数。已有地图迁移已经完成 此入口不再包含旧生成器迁移分支。

- `/Game/_Project/Mass/Monster/Spawn/BP_BBBMonsterSpawner`
- `/Game/_Project/Mass/Monster/Spawn/MEC_BBBMonsterSpawner`
- `/Game/_Project/Mass/Monster/Spawn/DA_BBBMonsterSpawn_Default`
- 同目录 `DA_BBBMonsterSpawn_Connor` `Jiho` `Michael` `Morita` `Renzo` `Sakurada` `Alice` `Kiyo` `Setsuko` `Yuina` 共十项 各名称均使用完整 `DA_BBBMonsterSpawn_` 前缀
- `/Game/_Project/Mass/Monster/Director/DA_BBBMonsterDirector_Once`
- 同目录 `DA_BBBMonsterDirector_Waves`
- 同目录 `DA_BBBMonsterDirector_Refill`

通过 `editor.validate_monster_director_assets` 只读核验正式配置。创建返回成功不等于运行验收完成。

## 运行验收

- 使用干员归属的测试宿主打开原项目 不复制工程
- `editor.run_automation_tests` 的 `UBBB.Mass.MonsterSpawn` 验证随机通道和有界取消
- `UBBB.Mass.MonsterDirector` 验证导演额度 暂停前实际创建结算及保存资产
- `animation_graph.inspect_mass_scene_population` 读取当前实体事实
- `animation_graph.inspect_mass_variation_network` 同时读取主机与客机的种子和个体差异
- 临时运行配置使用 `editor.spawn_configured_pie_actor` 明确世界及原生类 不修改资产默认对象

正式生成器没有逐实例玩法 Tick。房主执行统一出生处理 客机只从现有 Mass 网络载体还原小怪及出生种子。
