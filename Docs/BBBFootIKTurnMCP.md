# 原地转身脚部 IK 诊断

通过 `find_tools` 搜索目标，使用 `describe_tool` 读取参数，再提交批次。

- `editor.inspect_control_rig_graphs(asset_path)` 返回模型、本地函数图、引脚、默认值和连线。
- `editor.inspect_animation_float_curves(asset_paths, curve_names)` 返回原始曲线时间和值，缺失曲线以 `exists=false` 表达。

运行时脚部结果使用实际角色、骨骼姿势和地面接触探针核验。追踪通道枚举用于确认配置，实际命中结果用于判断接触。
