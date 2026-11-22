# BBB Monster Director MCP 工具

领域名：`monster_director`（对应 `Scripts/BBBMonsterDirectorToolset.py` 与引擎原生 `UBBBMonsterDirectorEditorLibrary`）。

用于操作推进式关卡导演系统（固有僵尸 `Population` / 周期动态波次 `DynamicHorde` / 预制事件波次 `EventWave` / 禁刷区 `BlockSpawn`）。

## 公开工具

- `monster_director.inspect_directors(expected_level="")`
  - 只读列出当前编辑关卡中的导演实例、区域用途统计、事件波次列表及校验状态。
- `monster_director.collect_regions(expected_level="", director_name="", save_level=False)`
  - 将关卡内全部 `ABBBMonsterSpawnRegionPresentationActor` 一键绑定到目标导演，可选直接保存当前关卡。
- `monster_director.validate_director(expected_level="", director_name="")`
  - 校验导演定义资产、实体模板与区域绑定完整性。
- `monster_director.preview_spawn(expected_level="", director_name="", mode="DynamicHorde", target_id="")`
  - 以当前编辑视口相机作为参考玩家，在场景绘制合格出生点（绿球）与排除点（红点）并返回原因统计 JSON。
  - `mode` 支持 `Population`、`DynamicHorde`、`EventWave`。
- `monster_director.read_pie_status(director_name="")`
  - 读取 PIE 主机世界中导演的只读实时状态（运行开关、存活/累计/预留数、固有区激活进度、动态波次冷却、运行中事件列表）。
- `monster_director.control_pie(action, director_name="", event_id="")`
  - 控制 PIE 主机导演，`action` 支持：`Start`、`Stop`、`PauseDynamicHorde`、`ResumeDynamicHorde`、`TriggerEventWave`、`StopEventWave`。
