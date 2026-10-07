# 声音资产只读审计与 WAV 导出

工具集：`BBBGenericEditorToolset`。不播放、不重导入、不修改和保存声音资产，不创建运行时音频逻辑。

## inspect_sound_assets

参数 `asset_paths: list[str]`：1—256 个 `/Game` 下的 SoundWave 或 SoundCue 包路径或同名对象路径。拒绝空列表、重复包、父级跳转和其他资产类型。

返回每项的资产类、硬软包依赖、声音公共属性、波形格式属性，以及 Cue 可达节点和 WavePlayer 的实际加载引用。读取失败属性记录在 `unavailable`，不能把不可读取当成默认值。节点或资产加载失败作为业务错误返回。

## export_sound_waves

参数 `asset_paths: list[str]`：1—256 个 SoundWave 路径；`output_directory: str`：项目 `Saved/temp` 下的绝对子目录。

整批预检路径、资产类型、输出重名和已存在文件后才创建目录。拒绝链接和重解析点、越界及覆盖。使用引擎 `SoundExporterWAV` 与 `AssetExportTask` 导出，随后用标准 WAV 读取器验证通道数、采样率、帧数和时长。

导出文件是本任务临时审计副本；调用者负责在任务结束后清理。部分导出失败可能保留已经生成的文件，禁止原批次无条件重试或覆盖；依据返回错误和磁盘实际状态处理剩余项。

声音是否适合脚步、爬行摩擦、撞击等用途需要实际试听；文件名、波形和技术参数不能代替主观音色确认。不能仅凭 `UI` 前缀判断空间化，应检查 Cue 和 SoundWave 的衰减、并发以及节点属性。

回归：`python -B -m unittest discover -s Tests -p test_sound_asset_audit.py`；宿主注册后核对新增工具 schema，再实际检查 SoundWave、SoundCue 并导出 WAV。
