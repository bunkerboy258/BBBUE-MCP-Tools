# 运动匹配配置检查与迁移

`motion_matching.inspect_configuration(content_directory, object_paths)` 原生读取配置的完整反射文本 子对象和蓝图默认值。`content_directory` 为空时读取本项目 指定参考 Content 目录时临时挂载且不保存参考包。支持读取 Chooser 的 ResultsStructs 与嵌套表 不受编辑器可编辑属性列表限制。

`motion_matching.migrate_configuration(content_directory, target_paths, request, dry_run)` 按明确对象映射创建自有配置。拒绝覆盖已有目标 拒绝复制动画序列和整份蓝图。`target_paths` 必须与请求中的资产目标 主蓝图和可选派生层完全一致。

请求字段:

- `assets`: `source` 与 `target` 数组。原生复制配置及其内部子对象 随后统一替换引用。
- `objectRemaps`: 已有依赖对象的 `source` 与 `target` 数组。用于动画 骨架 已迁移配置和类引用。骨架映射不等于动画重定向 必须事先准备同骨架动画。
- `overrides`: 明确的 `object` `property` `value` 数组。值采用引擎完整属性文本 仅允许写入本次创建配置或目标蓝图内部对象。适用于删减已核实的 Chooser 行与同步过滤列。
- `blueprint`: 明确的 `source` `target` `functions` `variables`。仅复制列出的函数和成员 可通过 `nodeTemplates` 提供同类动画节点的源与目标映射 通过 `historyAtOutput` 将已有姿态历史移动到主输出之前。
- `integration`: 可选的 BBB 角色快照适配。包含 `baseLayer` `layer` `chooser`。要求 UBBBAnimInstance 的事实接口及 GASP 标准 MM 函数集合 不导入参考 Pawn 或玩法。主线程生成轨迹与数据库上下文 派生层通过原有数据库提供函数求值 Chooser。

复制数据库保留条目采样范围 镜像和重选设置 标签 成本及归一化关联。归一化集合只保留已映射的自有数据库。复制 BlendProfile 时按目标骨名重建索引。数据库索引仍需通过 `motion_matching.inspect_database` 单独等待和核验。

动画节点模板复制包含内部图 属性绑定及搜索后回调。替换内部图时同步更新父图 SubGraphs 登记 避免编译检查仍指向旧空图。带标签的内部图需要注册相应 AnimBlueprint 编译扩展 并由正式主图标签保证重启后的扩展发现。参考函数的 Transform 默认值必须转换为蓝图使用的格式。BBB 快照适配移除标准查询中对实验性 OffsetRoot 节点的依赖 不以参考蓝图未接入的开关推断功能已关闭。

应用不是跨资产事务。原生阶段不保存 Python 入口逐项编译 保存和回读。失败时先检查明确目标的实际磁盘与脏包状态 不自动覆盖或回滚 不创建备份。已有配置可放入 `objectRemaps` 后继续迁移未保存的主蓝图。

2026-10-25: 运动匹配 Python 回归共二十八项通过 其中包括配置迁移边界五项和有界运行时探针八项。引擎编译及运行结果以项目实施记录为准。
