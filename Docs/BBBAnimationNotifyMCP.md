# 动画通知

通过 `find_tools` 搜索 `editor` 与目标操作，使用 `describe_tool` 读取参数后提交批次。

- `inspect_animation_notifies(asset_path)` 读取序列或蒙太奇的通知轨道、类路径、时间与持续时间。
- `replace_animation_notify_track(asset_path, track_name, events)` 校验完整配置后替换指定轨道并保存。
- `events` 为数组，每项包含 `class_path`、`time` 和可选 `duration`。通知状态使用正持续时间，单次通知使用零。
- 写入前核对轨道现状与资产独占归属；写入后读取实际事件。
- 创建失败时保留已完成范围，回读待保存内容并按批次核实流程处理。
