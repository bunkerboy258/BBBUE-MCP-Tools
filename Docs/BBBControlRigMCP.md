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
