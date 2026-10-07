# Traversal 资产与基础验收工具

`BBBTraversalToolset` 已纳入标准启动注册表 工具开发重载仍使用官方 `run_editor_script`

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

## 控制交接与网络验收

`inspect_traversal_montage_windows` 只读核对根运动校正窗口与混合时间
采样增加角色速度 双手位置 实际帧时 瞄准状态 步枪弹量与换弹状态
`get_pie_traversal_samples` 使用 `offset` 和 `count` 分页 每次最多一百条
`summarize_pie_traversal_samples` 从全量采样提取模式交接与攀爬期间的操作事实

`prepare_pie_traversal_fixture` 与 `sample_pie_traversal` 可用 `world_index` 选择同进程 PIE 世界
几何按世界独立持有 `place_player` 控制是否安置玩家 `lateral_offset` 让观察者停在同一场景侧面
多人安置按复制的玩家标识同时移动各世界中的同一角色副本 不混淆控制者与观察者

`configure_pie_traversal_network` 在内存中配置同进程的主机与客机
验收结束必须先以 `restore` 恢复原设置 再调用官方 `StopPIE` 以免编辑器保存临时偏好
`inspect_pie_traversal_network` 同时只读检查各世界中的角色副本
验收应复用唯一编辑器宿主 不使用固定时间步替代实际性能

`capture_pie_traversal_side_view` 用临时侧视相机保存全身姿势截图 不改玩家视点 不移动玩家
需要启用真实渲染 参数为独占的 PNG 文件名与 `world_index`
相机和渲染目标不保存为资产 截图位于 `Saved/temp/TraversalSideView` 任务结束后清理本轮文件
截图会引入渲染开销 平滑度应结合无截图时的实际帧时与位置采样判断

`inspect_pie_traversal_contact_points` 使用已初始化 PIE 角色的完整骨骼容器只读采样接触窗口末尾的左手组件空间位置
停止 PIE 后将其 `contacts` 数组传入 `configure_traversal_contact_points` 的 `points_json`
先 `dry_run` 核对再保存 已有自有蒙太奇必须独占签出 不改源序列与窗口时间
接触点采用无额外旋转的动画空间 Static Warp Point 最终落点仍使用原来的脚底空间目标
用于精确配置当前角色骨架 不修改引擎 也不新增运行时骨骼采样或手部 IK
