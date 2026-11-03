# 基础脚步声与声音制作

`assets.import_external_packages(content_directory, relative_packages, destination_root, dry_run)` 按明确清单导入外部 Content 内的原始包 同时使用引擎统一重命名改写硬软引用 保留源目录内结构 要求目标为第三方资源包根 上限五百一十二个包及五百一十二 MB 拒绝覆盖或将跳转作为主资产 保存后检查依赖与来源指纹

`blueprint.convert_notify_blueprint_to_state(blueprint_path, state_class, child_paths)` 将普通通知蓝图的 Received_Notify 覆盖转换为状态通知的 Received_NotifyBegin 由原生编辑器接口保留函数内部节点和连线 更新覆盖签名与父类 并编译明确的子通知后保存 不生成 Tick 或 End 行为

`animation.inspect_reference_notify_events(content_directory, animation_paths)` 只读加载明确的外部序列 animation_paths 使用外部 Content 内的相对包名并严格限制目录字符，每批最多一百二十八项，返回通知原生时刻与类。时刻扣除 TriggerTimeOffset，来源包不保存。只读外部蓝图依赖可能在宿主内保留，因此采集结束后应通过正常宿主交接清除来源加载状态再进入 PIE。

`animation.replace_notify_tracks(requests)` 每批一至八条明确的 asset_path、track_name、events。复用已有单轨通知编辑入口，保存后核对数量和时间，保护全骨轨、曲线、同步标记、循环、根运动与其它通知轨道。events 的字段为 class_path、time、duration、properties。

同刻通知通过原生 SetAnimationNotifyInstanceTrack 按实际通知对象归属到指定轨道 并恢复原有非目标通知的轨道 不按触发时刻识别对象 避免同时落脚与擦地时误改轨道 用户枚举由属性当前类型解析 不要求蓝图枚举暴露在 unreal 模块全局

`animation.assign_notify_instance_tracks(asset_path, assignments)` 使用明确通知对象路径到已有轨道名的映射 单独整理轨道 不改通知时刻 类型或实例参数 保存后回读通知列表 通知写入通过新增对象集合差确定本次对象 不采用同刻事件的返回对象

状态通知的区间重叠按顺序放入同名前缀的第二轨道及后续轨道 例如 Footsteps_2 不挪动触发时刻 不使用原有 PoseSearch 或默认轨道保存新增声音事件 replace_notify_tracks 将这个轨道族作为明确的替换范围并核验族外数据

外部包导入只允许恢复指纹完全相同的原始暂存 不覆盖不同内容的既有包 外部通知读取应使用隔离宿主 并先明确载入骨架 枚举 结构体和通知类依赖 再读取通知实例参数


运行时 `BBBCharacterFootstepPresentationAnimNotifyState` 是 Blueprintable 的 final 原生状态通知类型 具体通知蓝图在 Begin 复用 GASP Foley 链 淡出判断 事件音库与 MetaSound 不再由原生通知重复实现 不向玩法提交输入或发送逐步网络消息

2026-11-03 原生完整编译通过 已迁入二百八十九个官方 Foley 依赖资产 角色声音组件和 Begin 通知链已保存 回读二千零七十一条序列共一万七千七百零四条通知 全骨轨 曲线 同步标记 根运动与原有搜索通知保护检查通过 九十六个搜索库引用 维度与姿态数保持原值且索引就绪 未进行 PIE 听感验收 由用户验收
