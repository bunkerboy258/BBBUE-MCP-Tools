# Traversal 资产与基础验收工具

`Scripts/BBBTraversalToolset.py` 通过官方 `run_editor_script` 按需注册。

- `inspect_traversal_editing_schema` 只读返回 Base 和主动画蓝图的实际图表、可创建节点及 Motion Warping API。
- `configure_traversal_montages` 从已准备的根运动序列配置 FullBody 蒙太奇和官方 Skew Warp 窗口；目标脚底空间采用 UE Character Adapter，窗口可配置动画骨骼 Warp Point。
- `configure_traversal_blueprints` 首次构建 Base 配置和事件投递链、翻越时骨骼修正旁路、主动画蓝图脚部控制开关。已有 TraversalRequested 时拒绝重复构建；修改前先只读检查。
- `prepare_pie_traversal_fixture` 在运行中的 PIE 创建隔离的临时地板和静态障碍，并安置本地玩家；高度为 0 表示普通跳跃场景，`blocked` 添加顶部阻挡。退出 PIE 后场景销毁，不保存关卡。
- `sample_pie_traversal` 异步按游戏时间采样，`get_pie_traversal_samples` 返回结果。采样开始后立即使用官方 `run_pie_input_sequence` 投递 jump；检查实际蒙太奇、朝向、胶囊脚底、根骨位置和 Walking 恢复。
- `remove_pie_traversal_obstacle` 只删除当前工具创建的临时障碍，用于验收动作期间目标失效后的退出与根运动停止。

`configure_traversal_ik_transition` 用于已完成 Traversal 接入后的握持与瞄准过渡。先使用逻辑快照核对 Base 的 `FullBody_SkeletalControls`，把其 `logicSignature` 传入 `expected_graph_signature`，再执行 `dry_run: true` 预检。确认后 `dry_run: false` 写入指定自有 Animation Sequence 的 `DisableLHandIK` 和 `DisableAimIK` 浮点曲线，并把现有 Traversal 真分支改为 FABRIK 后的组件空间转本地空间，使其只旁路 Leg IK；假分支仍经过 Leg IK。Main 的脚部 Control Rig 开关保持不变。工具拒绝未知结构和指纹变化，不丢弃已有未保存蓝图内容，也不重复创建已正确连接的转换节点。

默认开头 0.15 秒从 0 渐变到 1，动作中保持 1，结尾 0.25 秒恢复为 0。0 允许现有 IK，1 禁用。两段渐变各使用七个 smoothstep 采样关键帧。未装备或左手目标无效时，原图的左手 Alpha 仍为 0；Aim Alpha 仍乘主实例瞄准权重和 LocomotionAimIKAlpha。写入前后逐骨骼检查原始轨道指纹，并检查根运动、根锁定、加法类型、通知、同步标记和其它浮点曲线，确认均未改变后才保存。不生成资产备份。

`sample_pie_traversal(include_ik_curves: true)` 同时读取主实例与当前 Rifle/Unarmed 链接层曲线、当前蒙太奇播放位置、左手目标有效性和原图权重因子。`calculatedLeftInputAlpha` 与 `calculatedAimInputAlpha` 是依据现有图公式计算的输入权重，不是读取原生节点内部 ActualAlpha。异步采样回调运行在编辑器主线程，诊断读取不作为动画工作线程 API。

目标序列有未保存改动时默认拒绝写入；只有已确认改动归属后，才可显式传入 `allow_dirty_sequences: true` 保留当前数据并继续编辑。骨骼指纹仅编码平移、四元数、缩放数值，不包含 Python 包装对象地址。实际曲线还会受到蒙太奇淡入淡出权重的影响；验收结束段时继续采集到淡出结束，不仅检查 `IsTraversing` 为真的样本。

`windows_json` 每条动画对应一个窗口数组。字段为 `start`、`end`、`target`，可选 `bone`、`rotation`、`subtract_remaining`。接触骨骼窗口通常设置 `rotation: false`，避免骨骼朝向改变角色整体朝向；最终落点窗口可设置 `subtract_remaining: true`，将窗口后的剩余根运动计入落点。这里的骨骼 Warp Point 用于根运动目标换算，不代表已实现手部贴面 IK。

推荐基础验收：100cm 薄障碍跨越、100cm 深平台攀爬、200cm 深平台攀爬、顶部受阻回退、无障碍跳跃、动作完成后继续移动、动作期间障碍销毁。NullRHI 可验收流程和位置数据，不能替代手部接触等视觉验收。工具不会自动修改输入配置或绕过项目输入管线。

当前原生逻辑快照检查器会把没有 VariableReference 的 `K2Node_MakeStruct` 也作为变量检查，可能报告“变量引用无法解析”。此类结构构造节点需结合真实蓝图编译结果判断，不能仅据该快照提示判定资产损坏。可调用官方 `BlueprintTools.compile_blueprint` 并设置 `warnings_as_errors: true` 检查编译错误与警告。

已有资产必须先独占签出。新目标先检查 Perforce 映射，保存后打开添加。蒙太奇配置工具不修改源动画；过渡工具只修改调用者明确指定的自有序列的两条禁用曲线。工具不执行提交或回退。
