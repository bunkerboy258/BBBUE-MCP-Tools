# 纹理美术交付

`BBBGenericEditorToolset.export_textures_png(asset_paths, export_name)` 使用 Unreal 原生 `TextureExporterPNG` 导出明确的 `Texture2D` 包路径列表，每批最多 256 张，保留源像素、透明通道与原始尺寸，不修改资产。

`export_name` 是 `Saved/Exports/` 下的新目录名称，只接受字母、数字、下划线和连字符。目录已存在或 PIE 正在运行时拒绝执行。输出按 `/Game/` 内的路径保留目录，并附带 `TextureManifest.json`，记录资产、相对文件名、尺寸和字节数。

无需可渲染 RHI；既有编辑器宿主在重启并注册工具后即可调用。导出清单与美术文件是交付成果；将多个交付目录归并到一个美术包时，调用者应同步清单中的相对路径。
