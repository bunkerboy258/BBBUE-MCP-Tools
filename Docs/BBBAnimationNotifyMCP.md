# 动画通知

通过 `find_tools` 搜索 `editor` 与目标操作，使用 `describe_tool` 读取参数后提交批次。

- `inspect_animation_notifies(asset_path)` 读取序列或蒙太奇的通知轨道、类路径、时间与持续时间。
- `replace_animation_notify_track(asset_path, track_name, events)` 校验完整配置后替换指定轨道并保存。
- `events` 为数组，每项包含 `class_path`、`time` 和可选 `duration`。通知状态使用正持续时间，单次通知使用零。
- 写入前核对轨道现状与资产独占归属；写入后读取实际事件。
- 创建失败时保留已完成范围，回读待保存内容并按批次核实流程处理。

## 原生通知时间边界

`editor.inspect_animation_notifies` 保留原有入口与字段，并新增 `nativeTriggerTime`、`nativeEndTriggerTime`、`nativeDuration`、`triggerTimeOffset`、`endTriggerTimeOffset`。这些数值由既有 `BBBHandPoseLayerEditorLibrary` 对实际资产通知数组直接调用 `FAnimNotifyEvent::GetTriggerTime/GetEndTriggerTime/GetDuration` 和读取原生偏移得到，不在 Python 中重算结束时间。

例如原生开始为 `0.30000001192092896`、持续为 `1.2000000476837158` 时，Python 双精度相加为 `1.5000000596046448`，实际原生结束可以是 `1.5`。制作底稿显示窗口应比较实际播放帧时间与返回的 `nativeEndTriggerTime`，采用 `[nativeTriggerTime,nativeEndTriggerTime)`，不要通过 `ceil((time+duration)*fps)` 推测。

原生列表与 Python 事件数组必须逐项匹配实例路径和数组位置；数量或身份不一致则明确失败，不返回拼错通知的时间。入口只读，不保存资产、不启动 PIE。八项独立检查覆盖完整事件、不完整轨道缓存、真实浮点结束保留、偏移保留及错位拒绝；编译后还须对真实序列和蒙太奇执行回读验证。
