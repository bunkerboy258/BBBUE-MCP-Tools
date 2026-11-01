# 蓝图更新函数提取

`blueprint.extract_update_function(graph_path, node_guids, function_name, dry_run=true)` 将明确的顺序更新节点及其纯值依赖提取为同一蓝图内的线程安全函数。

仅接受自有蓝图直属函数图 单入口 至多一个执行出口 且没有跨边界数据线。原函数接口不可选入 新函数不得已存在。先预览确认边界 再正式应用。正式操作保留事务 源节点在调用重接后删除 编译有错误或警告时不保存。成功后保存资产 并应回读原图与新函数。

该入口不改变计算常量 不重排片段内执行顺序 不迁移关联实例 不用于潜在调用或异步节点。涉及返回值或复杂控制流的片段不适用。

2026-11-01 已在角色主蓝图完成三段实际提取 全部编译保存并回读。提取后顶层明确调用查询准备 轨迹 运动数据 状态 选库与帧末提交。

`animation_graph.configure_recoil_update_pipeline(blueprint_path, dry_run=true)` 需要已编译的装备动画事实曲线采样接口。创建主蓝图后坐力状态更新与只读结果函数 保留射击分段 回落公式和配置上限。配置只在明确主动画蓝图执行 不修改姿势图或动作素材。新增入口须在无 PIE 时调用并编译保存回读。原生代码编译和实际构图保存已通过 不替代用户运行验收。

`animation_graph.simplify_animation_fact_adapter(blueprint_path, dry_run=true)` 用于已展开主管线的角色蓝图。严格核对八处属性路径和两处落地结构消费者 将纯表达式迁到实际消费者 仅保留落地边沿和上一帧速度变量。未知消费者或跨执行边界表达式直接拒绝。成功后删除 CharacterProperties 变量 不自动删除 Shared 资产。实际角色蓝图已保存通过。

`animation_graph.centralize_weapon_handling(main_path, base_path, layer_paths, dry_run=true)` 将基类 UpdateWeaponHandling 的公共派生计算移入主蓝图 并在后坐力更新后调度。关联层通过已有主实例适配器读取结果 主实例未有效时不解引用。保持层内瞄准素材选择和求值曲线阶段。显式列出全部受影响关联子层并逐项编译保存；可继续完成已创建目标函数的迁移 不重复插入顶层调用。主蓝图 基类和五个子层实际编译保存通过。
