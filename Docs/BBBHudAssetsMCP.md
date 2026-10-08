# HUD 网格轮廓图

工具集 BBBHudAssetToolset 由统一 Bootstrap 加载。

render_mesh_silhouettes 接受 requests_json 列表。每项包含 mesh 网格资产路径和 output 相对于项目 Saved/temp 的 PNG 路径。可选 horizontal_axis 与 vertical_axis 分别指定水平和垂直轴 0 为 X 1 为 Y 2 为 Z。flip_horizontal 用于统一朝向。

原生依赖为项目编辑器模块的 BBBAssetThumbnailEditorLibrary.RenderMeshSilhouette。工具读取 LOD0 MeshDescription 并进行三倍采样的三角形正投影 输出 512x256 纯白透明 PNG。支持 NullRHI 无需打开可见编辑器。不修改模型 不覆盖输出。

先检查少量型号的侧向投影 再批量生成。导入纹理时仍按现有资产写入规则签出或添加 设为 UI 纹理并保留透明度。任务结束清理 Saved/temp 内临时输出。

set_input_action_keys 接受 mapping_context_path 和 mappings_json。每项包含 action 输入动作资产路径与 key 按键名称 如 One Two Three。同一动作只接受一个按键。工具通过 UE 5.8 InputMappingContext 的当前默认映射接口替换指定动作按键 保留其余动作的映射与修饰器。写入前检查资产权限 保存前核对映射数量与实际按键。
