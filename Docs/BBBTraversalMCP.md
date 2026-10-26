# Motion Warping 资产工具

`BBBTraversalToolset` 仅保留四个通用资产工具，不再提供本项目角色攀爬状态机、输入、复制或测试场景入口。

- `inspect_traversal_montage_windows` 只读核对明确蒙太奇的校正窗口和混合时间。
- `configure_traversal_montages` 配置明确源序列与目标蒙太奇的 Skew Warp 窗口。它只负责资产，调用者必须自行实现播放和移动控制。
- `inspect_pie_traversal_contact_points` 通过已初始化的 PIE 骨骼容器读取接触窗口末尾的手部位置。
- `configure_traversal_contact_points` 将明确的接触点写回独占持有的蒙太奇，支持只读预检，不修改源序列与窗口时间。

BBB_Evac 本版本不实现攀爬，运行时代码只保留无状态系统入口。不得用这些资产工具重新接入已删除的角色状态、RPC 或动画槽位。角色基础姿态收敛使用 [运动匹配工具](BBBMotionMatchingMCP.md) 中的 `motion_matching.configure_character_montage_graph`。
