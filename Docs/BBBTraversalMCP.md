# Traversal 资产与基础验收工具

`Scripts/BBBTraversalToolset.py` 通过官方 `run_editor_script` 按需注册。

- `inspect_traversal_editing_schema` 只读返回 Base 和主动画蓝图的实际图表、可创建节点及 Motion Warping API。
- `configure_traversal_montages` 从已准备的根运动序列配置 FullBody 蒙太奇和官方 Skew Warp 窗口；目标脚底空间采用 UE Character Adapter，窗口可配置动画骨骼 Warp Point。
- `configure_traversal_blueprints` 首次构建 Base 配置和事件投递链、翻越时骨骼修正旁路、主动画蓝图脚部控制开关。已有 TraversalRequested 时拒绝重复构建；修改前先只读检查。
- `prepare_pie_traversal_fixture` 在运行中的 PIE 创建隔离的临时地板和静态障碍，并安置本地玩家；高度为 0 表示普通跳跃场景，`blocked` 添加顶部阻挡。退出 PIE 后场景销毁，不保存关卡。
- `sample_pie_traversal` 异步按游戏时间采样，`get_pie_traversal_samples` 返回结果。采样开始后立即使用官方 `run_pie_input_sequence` 投递 jump；检查实际蒙太奇、朝向、胶囊脚底、根骨位置和 Walking 恢复。
- `remove_pie_traversal_obstacle` 只删除当前工具创建的临时障碍，用于验收动作期间目标失效后的退出与根运动停止。

`windows_json` 每条动画对应一个窗口数组。字段为 `start`、`end`、`target`，可选 `bone`、`rotation`、`subtract_remaining`。接触骨骼窗口通常设置 `rotation: false`，避免骨骼朝向改变角色整体朝向；最终落点窗口可设置 `subtract_remaining: true`，将窗口后的剩余根运动计入落点。这里的骨骼 Warp Point 用于根运动目标换算，不代表已实现手部贴面 IK。

推荐基础验收：100cm 薄障碍跨越、100cm 深平台攀爬、200cm 深平台攀爬、顶部受阻回退、无障碍跳跃、动作完成后继续移动、动作期间障碍销毁。NullRHI 可验收流程和位置数据，不能替代手部接触等视觉验收。工具不会自动修改输入配置或绕过项目输入管线。

当前原生逻辑快照检查器会把没有 VariableReference 的 `K2Node_MakeStruct` 也作为变量检查，可能报告“变量引用无法解析”。此类结构构造节点需结合真实蓝图编译结果判断，不能仅据该快照提示判定资产损坏。可调用官方 `BlueprintTools.compile_blueprint` 并设置 `warnings_as_errors: true` 检查编译错误与警告。

已有资产必须先独占签出。新目标先检查 Perforce 映射，保存后打开添加。工具不修改源动画，不执行提交或回退。
