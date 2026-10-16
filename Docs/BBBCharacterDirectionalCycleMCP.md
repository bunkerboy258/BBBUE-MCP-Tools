# 角色四向循环与参考方向扭曲

`animation_graph.restore_character_directional_cycle` 将基础装备动画层的 `FullBody_CycleState` 恢复为单段循环选片。明确传入基础层 完整装备后代数组 参考项目 Content 目录和原始基础动画层相对包路径。装备后代按父层在前排列。

工具从原始参考循环图直接复制 Sequence Player 同步配置与 Orientation Warping 运行时结构 可选输入及默认值。原始属性存取路径的主实例入口映射为本项目 `GetBBBMainAnimAdapterThreadSafe`。角色骨架缺少 `spine_04` 与 `spine_05` 时仅保留实际存在的脊柱链 其他骨骼与数值设置保持原值。更新函数恢复惯性换片与速度匹配 保留走路 跑步 蹲伏四向动画选择和既有步幅权重。

主 AnimGraph 状态机 继承关系 Start Stop Pivot 不参与修改。原循环 BlendSpace 专用变量和更新链移除。工具编译并保存基础层及装备后代。专用 BlendSpace 删除前须明确路径并确认引用已解除 通过资产管理工具完成清理。

`animation.export_animation_blueprint_graphs` 支持项目包路径及外部项目 Content 内的绝对 uasset 文件路径。外部参考只在非 PIE 状态下临时挂载读取 不编译或保存参考资产。参考包的编译状态不能作为目标资产编译状态使用。

本轮仅执行必要的编辑器编译与资产保存 不进行运行或视觉验收。
