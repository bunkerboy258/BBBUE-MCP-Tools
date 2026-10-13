# 副本小怪导演基础资产

`editor.create_monster_director_assets` 使用项目原生 `BBBMonsterDirectorEditorLibrary` 在共享资产编辑宿主创建九个基础资产 编译蓝图 保存并返回结构校验 不修改地图 不启动生成 不覆盖已有目标

调用参数 `asset_paths` 必须完整提供以下路径

```json
[
  "/Game/_Project/Mass/Monster/Director/BP_BBBMonsterDirector",
  "/Game/_Project/Mass/Monster/Director/BP_BBBMonsterSpawnRegion_Box",
  "/Game/_Project/Mass/Monster/Director/BP_BBBMonsterSpawnRegion_Cylinder",
  "/Game/_Project/Mass/Monster/Director/MEC_BBBMonsterDirector",
  "/Game/_Project/Mass/Monster/Director/DA_BBBMonsterSpawnPool_Default",
  "/Game/_Project/Mass/Monster/Director/EQS_BBBMonsterDirectorSpawnLocations",
  "/Game/_Project/Mass/Monster/Director/DA_BBBMonsterDirector_Once",
  "/Game/_Project/Mass/Monster/Director/DA_BBBMonsterDirector_Waves",
  "/Game/_Project/Mass/Monster/Director/DA_BBBMonsterDirector_Refill"
]
```

先执行 Perforce 新目标预检 所有目标必须尚不存在 缺少项目原生库时契约明确不可用

默认小怪池引用现有康纳 智浩 迈克尔 森田 伦佐 樱田 爱丽丝 清 世津子 由奈十种定义 权重相同 每种定义继续使用自己的 Mass 配置

默认规则为一次生成 20 只 分波阶段 10/15/20 只 或补员总额度 60 只 分波与补员每批最多 5 只 间隔 10 秒 导演存活上限 20 世界存活上限 80 第一阶段等待玩家进入 后续阶段自动激活 导演蓝图默认关闭自动开始

`editor.validate_monster_director_assets` 无参数 可在独立只读测试宿主执行 只加载并校验蓝图默认对象 规则 小怪组合 Mass Trait 与 EQS 生成器 不保存资产 宿主冷启动后的校验用于确认磁盘内容

测试前缀 `UBBB.Mass.MonsterDirector` 验证预算 请求失效 多导演归属 区域采样与现有小怪批量初始化 实际地图选点 导航 多人同步和战斗验收仍须在指定地图执行

`editor.run_automation_tests` 归为运行控制 可通过公开网关进入独立测试宿主 首次批次传入 `test_options={"map":"/Engine/Maps/Entry"}` 不要求启动 PIE 测试宿主资产写入限制继续生效 日志最终通过结果需要核验

编辑器工具入口为 `工具 > 副本小怪导演` 地图放置导演和区域蓝图后绑定区域引用 每个区域标识在该导演内唯一 阶段通过区域标识选择区域 方盒与圆柱使用原生移动 旋转与缩放工具 地图必须具有适合小怪胶囊的导航数据
