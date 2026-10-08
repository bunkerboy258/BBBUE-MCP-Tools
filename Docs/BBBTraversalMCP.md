# Traversal 资产与基础验收工具

`BBBTraversalToolset` 已纳入标准启动注册表 工具开发重载仍使用官方 `run_editor_script`

- `inspect_traversal_editing_schema` 只读返回 Base 和主动画蓝图的实际图表、可创建节点及 Motion Warping API。
- `configure_traversal_montages` 从已准备的根运动序列配置独立 Traversal 槽蒙太奇和官方 Skew Warp 窗口 蒙太奇自身不淡出且不自动结束 由移动状态机管理姿势混合 目标脚底空间采用 UE Character Adapter 窗口可配置动画骨骼 Warp Point
- `configure_character_traversal_state` 将当前攀爬接入主图既有 LocomotionSM 并在现有动画层接口新增 FullBody_TraversalState Base 提供状态内 Slot 和线程安全 SelectTraversalMontage 具体 Rifle 与 Unarmed 层仅继承 Base 不重写攀爬或武器属性复制
- `prepare_pie_traversal_fixture` 在运行中的 PIE 创建隔离的临时地板和静态障碍，并安置本地玩家；高度为 0 表示普通跳跃场景，`blocked` 添加顶部阻挡。退出 PIE 后场景销毁，不保存关卡。
- `sample_pie_traversal` 异步按游戏时间采样，`get_pie_traversal_samples` 返回结果。采样开始后立即使用官方 `run_pie_input_sequence` 投递 jump；检查实际蒙太奇、朝向、胶囊脚底、根骨位置和 Walking 恢复。
- `remove_pie_traversal_obstacle` 只删除当前工具创建的临时障碍 用于验收动作期间目标失效后的退出与根运动停止 world_index 默认负一同时删除所有 PIE 副本的测试障碍 避免不同副本的地面几何不一致 也可明确指定单个世界

`configure_character_traversal_state` 必须明确主图 接口 Base 具体继承层和翻越 低攀爬 高攀爬三条既有蒙太奇 工具检查骨架一致性 直接继承关系 写权限与未保存改动 然后执行原生构图 所有目标编译无错误无警告后才逐个保存 不备份 不提交 不回退 旧 EventGraph 请求链与骨骼控制旁路直接移除 不保留兼容入口 重复调用拒绝再次构图

主状态机承担动作进出与姿势交接 倒地优先于攀爬 攀爬优先于普通移动 退出等待 CMC 离开 Flying 并按实际事实进入 Cycle Idle 或 FallLoop 持续移动不经过 Idle 蒙太奇停止根运动时暂停在当前姿势 状态淡出完成后才清理播放实例 新状态的 Modify Curve 禁用权重随状态混合 保持既有骨骼控制和脚部开关链原状

`sample_pie_traversal(include_ik_curves: true)` 同时读取主实例与当前 Rifle 或 Unarmed 链接层曲线 蒙太奇位置 左手目标有效性和原图权重因子 calculatedLeftInputAlpha 与 calculatedAimInputAlpha 仅是按现有公式计算的输入权重 并非节点内部 ActualAlpha 诊断读取运行在编辑器主线程 不作为动画工作线程 API

`windows_json` 每条动画对应一个窗口数组。字段为 `start`、`end`、`target`，可选 `bone`、`rotation`、`subtract_remaining`。接触骨骼窗口通常设置 `rotation: false`，避免骨骼朝向改变角色整体朝向；最终落点窗口可设置 `subtract_remaining: true`，将窗口后的剩余根运动计入落点。这里的骨骼 Warp Point 用于根运动目标换算，不代表已实现手部贴面 IK。

推荐基础验收为 150cm 薄障碍跨越 150cm 深平台攀爬 200cm 深平台攀爬 100cm 低障碍普通跳跃 顶部受阻回退 无障碍跳跃 动作完成后持续移动和动作期间障碍销毁 当前触发最低高度由角色配置决定 不增加普通跳跃可通过性的程序判断 NullRHI 可验收流程和位置数据 不能替代手部接触等视觉验收 工具不会修改输入配置或绕过项目输入管线

当前原生逻辑快照检查器会把没有 VariableReference 的 `K2Node_MakeStruct` 也作为变量检查，可能报告“变量引用无法解析”。此类结构构造节点需结合真实蓝图编译结果判断，不能仅据该快照提示判定资产损坏。可调用官方 `BlueprintTools.compile_blueprint` 并设置 `warnings_as_errors: true` 检查编译错误与警告。

Perforce 用于版本管理而非限制正常编辑 受控资产仍检查他人占用 冲突与实际写权限 未受控骨架或资产允许修改并警告版本保护缺口 不因为未映射到工作区而阻止本次构图 工具只保存明确目标 不修改源动画 不执行 Get Latest Submit 或 Revert

## 控制交接与网络验收

`configure_character_movement_input(main_path)` 在主图既有线程安全 UpdateAccelerationData 中派生 HasMovementInput 普通移动转换按 SourceMovementInput 判断持续输入 急转方向与其有效分支仍使用真实 SourceAcceleration 攀爬出口按速度与持续输入选择 Cycle 或 Idle 不伪造 CMC 加速度 不改 EventGraph 或主姿势链 重复构图或脏目标拒绝 无警告编译后仅保存主图

角色网络观察同步同版本的实际加速度与已解析世界空间移动输入 镜像只还原黑板 不重演输入 移动输入在根运动期间已存在 不等待退出后的首帧 CMC 加速度 网络诊断同时显示 SourceMovementInput 持续按住移动时退出后不得经过 Stop 或 Idle 松开输入后正常制动

节点布局调整使用通用 `BBBBlueprintGraphToolset.set_blueprint_node_positions` 必须提供当前快照及明确的节点 GUID 与整数坐标 支持状态机节点 不重建连接 不编译或保存 移动后回读坐标并检查逻辑签名一致 再对指定蓝图严格编译并显式保存 不移动既有状态或说明框

`inspect_traversal_montage_windows` 只读核对根运动校正窗口与混合时间
采样增加角色速度 双手位置 实际帧时 瞄准状态 步枪弹量与换弹状态
装备隐藏与使用许可同时采样 网络检查也返回各副本的状态权重与装备隐藏事实 装备实例仍在背包中 暂时隐藏不等同于销毁或更改选中槽
采样的 animationState 返回真实 LocomotionSM 当前状态与各状态权重 Traversal 槽权重 播放位置 暂停情况和根运动禁用事实 用于核实控制释放与尾姿混合并非同一时刻
`get_pie_traversal_samples` 使用 `offset` 和 `count` 分页 每次最多一百条
`summarize_pie_traversal_samples` 从全量采样提取模式交接与攀爬期间的操作事实

`prepare_pie_traversal_fixture` 与 `sample_pie_traversal` 可用 `world_index` 选择同进程 PIE 世界
多人采样同时记录各世界全部角色副本的网络事实 可按 playerId 对齐同一操作者 不以本地控制者或 Actor 名称误认镜像
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
