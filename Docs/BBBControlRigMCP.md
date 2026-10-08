# Control Rig 动画图 MCP

## `create_control_rig_anim_graph_node`

在指定动画蓝图的 AnimGraph 中创建并配置 Control Rig 节点，返回新节点的完整对象路径。该工具不会连接姿势或状态引脚，不编译或保存蓝图。

参数：

- `blueprint_path`：动画蓝图资产路径
- `graph_path`：动画图对象完整路径，例如 `/Game/BBBC_UA/AnimationSystem/BBBABP_UA.BBBABP_UA:AnimGraph`
- `rig_asset_path`：Control Rig 蓝图资产路径
- `exposed_input_names`：需要显示的 Rig 输入变量名数组
- `position_x`、`position_y`：AnimGraph 中的节点坐标

## `configure_control_rig_anim_graph_node`

为指定动画蓝图中的现有 `AnimGraphNode_ControlRig` 配置 Control Rig 资产，并显示请求的 Rig 输入引脚。该工具只修改传入的节点，不修改 Control Rig 资产，不自动连接动画图，不编译或保存蓝图。

参数：

- `blueprint_path`：目标动画蓝图资产路径，例如 `/Game/BBBC_UA/AnimationSystem/BBBABP_UA`
- `node_path`：目标 Control Rig 动画图节点对象完整路径，例如 `/Game/BBBC_UA/AnimationSystem/BBBABP_UA.BBBABP_UA:AnimGraph.AnimGraphNode_ControlRig_0`
- `rig_asset_path`：Control Rig 蓝图资产路径，例如 `/Game/BBBC_UA/Rigs/CR_BBB_MannequinFootPlant`
- `exposed_input_names`：需要显示的 Rig 输入变量名数组，例如 `["isCrouching", "isMoving2D"]`

调用前应确认目标动画蓝图与 Rig 使用兼容的骨架，并且输入变量确实存在。工具会在运行时校验动画蓝图归属、预览网格骨架、Rig 生成类和输入变量；校验失败会写入 `[BBB][ControlRig]` 错误日志并返回失败。成功后通过结构性重建生成引脚，后续需显式连接姿势、启用布尔值及状态输入，并由调用方决定何时编译和保存。

## `inspect_control_rig_controls`

读取 Control Rig 蓝图层级中实际可动画控制器的名称 类型和初始组件空间偏移。参数 `asset_path` 为绑定资产路径。该工具只读 不创建 Sequencer 轨道或修改资产。写键前用返回的控制器类型选择官方写键接口。

`configure_sequence_rig` 先打开目标 Level Sequence 再获取绑定轨道与实例 避免打开序列重建预览实例后仍向旧实例写键。原姿势控制器写键后会校验实际值 失败时禁止保存。

`configure_control_rig_graph` 的请求支持 `controls` 数组追加独立 EulerTransform 控制器 每项指定 `name` 和可选 `visible`。已有同名控制器会拒绝。`breakLinks` 数组显式断开指定来源与目标引脚 再按 `links` 连接 不自动猜测原图入口。适用于在现有 IK 前明确补入原始全身姿势 不要求新的专用绑定工具。
