# 资产精确修复

工具集 `BBBAssetMaintenanceToolset` 新增以下通用入口. 原生能力位于接入项目 `BBBAssetRepairEditorLibrary`, 运行前须完成编辑器目标编译.

- `inspect_pose_asset_source_guids(asset_paths)`: 只读比较缓存 GUID 与源动画的新旧算法, 返回持久化姿势载荷指纹. 最多 64 项.
- `repair_pose_asset_source_guids(expected_reports_json, dry_run=true, allow_verified_samples=false)`: 使用完整检查报告进行全批预检. 默认仅缓存匹配旧算法且不匹配当前算法时允许更新. 显式启用逐键证明时, 还要求骨骼/姿势/曲线结构匹配, 全部姿势有效, 位置误差不超过 0.0001 cm, 旋转误差不超过 0.0001 度, 缩放误差不超过 0.000001. 精度界限固定, 不能通过参数放大. 拒绝报告漂移或任意脏包. 执行必须备份并独占签出. 不调用姿势重生成, 不修改源动画. 保存前验证载荷指纹相同.
- `inspect_animation_access_errors(asset_paths)`: 输出动画属性访问节点精确路径和错误, 最多 16 项.
- `repair_animation_property_queries(operations_json, save=false)`: 创建带空值回退的浮点或布尔查询, 插入平滑布尔权重, 修改精确属性路径或替换为纯查询调用. 全批编译通过后才允许保存. 失败不保存, 保留内存现场供诊断.

蓝图操作计划为数组, 每项包含 `asset` 和以下可选数组:

- `guarded_queries`: `name`, `object_getter`, `class`, `value_getter`, `fallback`. 名称不得已存在. 对象查询和数值查询必须为纯函数. 类型转换成功后才读取对象, 失败直接返回回退值.
- `weights`: `update`, `variable`, `boolean_getter`, `object_getter`, `speed`. 现有更新函数须有 `DeltaTime` 参数. 在入口后更新新变量, 目标为布尔查询成立且对象非空时的 1, 否则为 0.
- `paths`: `node`, `old`, `new`. 路径为字符串数组. 必须匹配旧路径和所属蓝图.
- `calls`: `node`, `old`, `query`. 使用现有无参数纯查询替换属性节点并保留输出消费者.

上述蓝图工具不是任意自动迁移器. 调用者必须先核对旧查询与新数据的语义, 保留备份, 检查计划. 不得以常量替代未知语义或恢复已删除的兼容接口. 修改内存后再次执行时应仅提供剩余操作, 不重复创建已经存在的查询.

## 单对象重定向包删除

`delete_asset_redirectors` 保持原有签出和无引用预检. 原生删除入口现在使用 `DeleteRedirectorPackages`, 在引擎删除对象前保留原始包. 引擎可能将重定向对象移到临时包, 若只从删除后的对象收集包, 会出现注册表对象已删除但磁盘文件仍在的情况. 新入口随后对原始包执行引擎正常空包清理, 不直接删除目标文件, 不以对象删除返回值冒充磁盘删除成功. 调用方继续核验文件和注册表均消失.
