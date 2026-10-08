# PIE 混音输出录制

`BBBGenericEditorToolset.start_pie_audio_recording(file_prefix)`：开始当前 PIE 世界的混音输出录制。不是麦克风录制。前缀必须为 `任务目录名/文件名` 两段英文 数字 下划线或横线。生成位置严格限定在项目 `Saved/temp` 内并拒绝链接 越界和覆盖。

`BBBGenericEditorToolset.finish_pie_audio_recording()`：结束同一 PIE 世界的录制并请求原生异步 WAV 导出。返回 `export_requested` 不代表有效音频已经写入。调用者必须等待文件落盘并核对时长 通道 采样率和非静音内容。

必须使用启用音频设备的宿主 不得带 `-NoSound`。隐藏宿主的后台音量可能为零 验收时可临时设置 `au.DisableAppVolume 1` 但不得保存用户配置。录制过程中禁止结束 PIE 或重载工具。世界改变后录制失效且不补录历史。

每次只允许一个本工具录制。完成后清理本任务的导出文件 不改声音资产或关卡。声音请求计数或 `AudioComponent.IsPlaying` 不能代替混音输出验证。
