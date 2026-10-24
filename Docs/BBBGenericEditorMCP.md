# BBB 通用编辑器 MCP

## 动画曲线原样迁移

- `editor.inspect_animation_curve_data` 读取精确采样率 原始浮点曲线及指定局部骨轨道的量化摘要 轨道摘要只用于同源核对 不代替动作验收
- `editor.rename_animation_curve` 对明确的自有动画序列及动画蓝图原位改名 默认只检查 新旧曲线并存时拒绝覆盖 正式执行保留曲线原始键和标记 并更新蓝图名称引脚及节点内嵌名称属性 编译并保存
- `editor.copy_animation_float_curves` 从明确基准复制完整浮点曲线到同源同长目标 保留插值 切线 权重和标记 不删除目标无关曲线 不创建备份 不做时间归一化 默认只检查

`replace_animation_float_curve` 的 `interpolation` 可选 `linear` 或 `cubic_flat` 默认保留原先写键方式 `cubic_flat` 通过动画数据控制器写入 RCIM_Cubic 和水平 RCTM_User 切线 等价于两端水平控制柄的三次贝塞尔 不加密关键帧 `inspect_animation_float_curves` 的 keys 回读原始插值类型与切线

`editor.schedule_pie_actor_function` 的 `repeat_count` 控制一至六百次公开 Actor 函数调用 `interval_seconds` 为游戏秒间隔 零表示连续游戏更新 每个游戏更新最多调用一次 总计划时长最多六十秒 `status` 返回实际调用次数与每次时刻 世界或目标结束立即释放回调

PIE 混音导出完成检查同时核对 WAV 文件头与有效采样 导出完成后释放对应活动

公开批次默认完成本批次范围的验证、保存与回读。分阶段预览或人工检查时传 `completion="review"`。下文函数级保存行为描述对应领域实现；公开调用的完成策略以批次参数为准。

## 动画通知完整性检查

`inspect_animation_notify_properties` 的 `match_index` 按完整事件数组中同类通知的顺序从零选择实例 用于分别读取双弹握持或多枚退壳的变换 默认负一要求唯一实例 索引越界明确失败 返回实例路径 匹配数量和时间区间 不修改资产

`inspect_animation_notifies(asset_path)` 从动画完整事件数组读取通知 同一时刻的多个通知实例均独立返回 轨道名称只在缓存中的实例身份能唯一对应时返回 缓存缺失或不唯一时 track 为 null 不猜测归属 不修改或保存资产 须在 PIE 结束后查询编辑器资产

## PIE 网格实例与附着对象清理检查

`inspect_pie_static_mesh_instances(mesh_path)` 只读检查全部 PIE Actor 的静态网格组件 同时覆盖独立物理弹壳和附着在角色手上的弹药或弹匣
返回组件路径 世界位置 物理速度 附着父组件与 Socket 独立静态网格 Actor 才有剩余寿命 其它组件的寿命字段为空
在通知生效期间先验证对应组件确实出现 再在正常结束或中断后检查数量归零 不将仅检查独立 Actor 的结果作为手持组件清理证据

## 明确字体源导入

`import_font_faces(requests)` 每项指定项目 Content 内永久 `.ttf` 或 `.otf` 的 `source` 与新 `destination` 包路径。仅创建内联 `FontFace` 不生成额外 `Font` 不覆盖既有资源。批量一至十六项。导入前检查源文件与 Perforce 写入许可。

## 透明缩略图主体取景

`frame_texture_thumbnails(asset_paths, occupancy=0.86, dry_run=True)` 只处理明确列出的真实透明纹理
按透明轮廓统一主体最长边占幅 保留颜色和长宽比 不生成装备内容
先用 dry_run 检查全部源图 正式执行前必须独占签出目标纹理
拒绝空图 无透明背景 重复资产 非法占幅及 PIE 中的写入
逐项导入保存 中途失败不自动重放 已保存结果需要调用方检查
调用引擎自带 Python 子进程及其 Pillow 不要求内嵌 Python 安装依赖 临时导出统一位于 Saved/temp/ThumbnailFraming 并在调用结束清理批次目录

`capture_editor_screenshot` 的截图位于 Saved/temp/McpScreenshots
仅截图调用方明确指定的 Slate 控件 不切换焦点 调用方在验收结束后清理自己产生的截图

## 精确重载已保存资产

`reimport_texture(asset_path, source_file)` 将绝对路径的 PNG 原位导入已有 Texture2D 并只保存该资产。
目标必须已独占签出 不允许 PIE 或覆盖未保存修改 保留原导入设置 验证导入返回唯一原路径。
它不办理签出 不生成副本或重定向器 失败后应检查资产状态 不自动重试。

`reload_assets_from_disk(asset_paths, discard_dirty_packages, dry_run=True)` 接受一至六十四个精确 `/Game/` 内容资产包路径，不接受目录、地图、PIE 或尚未保存的新资产。默认只预检；正式调用前核对返回的 `discarding`。

脏包只有逐项出现在 `discard_dirty_packages` 中才允许重载；该数组必须是目标列表子集。调用方必须确认这些未保存修改属于本任务且确实应放弃，不以此丢弃用户或其他会话的改动。工具使用原生 ReloadPackages，无弹窗、不保存、不执行 Perforce Revert，结束后回读目标脏状态；部分失败会报警，不自动重试。重载会替换内存对象，后续重新查询对象引用。

适用场景包括读取磁盘上的最新保存结果，以及清理本任务造成的源资产脏标记。它不等于从版本库获取最新版本，也不是资产修改回滚事务。

## 静态网格 PCG 入库验证

通过实际发现的通用工具集调用 `create_static_mesh_grid_graph(graph_path, mesh_paths, grid_extent=600.0, cell_size=300.0)` 创建新图。仅接受未占用的 Game 包路径、一到三十二个已加载静态网格及有限正网格参数，最多二百五十六个点。创建 CPU 平面网格和加权 Static Mesh Spawner，默认使用原组件坐标，不裁切体积。该图用于验证导入资源可以实例化，不包含地形投射、道路避让或营地规划。修改不存在的资产不需要签出；创建后由调用方核对 Perforce 添加状态。

`generate_and_inspect_pcg(actor_path, graph_path, expected_level, generate=False)` 默认只读，核对活动关卡和 Actor 世界，要求恰好一个 PCG 组件，返回生成标记、ISM 网格及实例数。传 `generate=True` 时先检查可编辑状态并启动异步生成；不会等待任务结束，也不自动重放已生成组件。调用方之后用 `generate=False` 回读确认实例数，并只保存自己的关卡。生成标记有效但零实例会报警。

两工具在 PIE 中拒绝写入。失败可能留下未保存的新图；批次不是事务，不自动重试、覆盖或回滚。调用出错后先检查实际图与生成状态。工具只负责图和实例技术验证，资源许可、视觉质量、碰撞及性能仍须分别检查。

本项目验证资产：`/Game/_Project/PCG/AssetLibrary/PCG_BBBAssetLibraryValidation` 与 `L_BBBAssetLibraryValidation`；首次 CPU 生成核验为桶炉四个、塑料箱六个、水桶六个，共十六个实例。资产库索引见项目 `Docs/PCG/AssetLibraryManifest.md`。

工具集名称: 使用本次实际发现的 `BBBGenericEditorToolset` 完整注册名称

## bind_niagara_channel_reader

参数 system_path channel_path
在发射器生成图表创建共享的 Emitter.Channel 读取器 用于数据通道生成与读取的编译期绑定
仅对尚未绑定该参数的系统调用 修改前要求独占签出 完成后编译保存

## set_niagara_channel_reader_frame_mode

参数 `system_path` 与 `read_current_frame`

统一设置指定 Niagara 系统内的数据通道读取器 包含源图与编译缓存 然后重编译并保存
`true` 读取当前帧 `false` 读取上一帧
仅在无 PIE 且目标资产没有未保存改动时调用 要求已独占签出 不修改其它资产
读取当前帧时 调用方必须保证通道发布先于光效模拟 工具不会替运行时代码建立 Tick 依赖

## inspect_niagara_graphs 与 set_niagara_pin_default

inspect_niagara_graphs 使用 system_path 读取系统内部节点 引脚 默认值与连接
结果开头还会列出脚本编译状态：2 为错误 3 为最新 5 为带警告的最新 6 为计算脚本带警告的最新
set_niagara_pin_default 使用 system_path node_path pin_name value 修改未连接输入引脚
节点必须来自该系统图表的检查结果 系统必须独占签出 修改后编译并保存

## set_niagara_spawn_update_mode

参数 system_path 与 mode
mode 为原生模式 0 跳过新粒子的首帧更新 1 执行首帧更新 2 插值更新
作用于系统内全部发射器 修改前要求独占签出 完成后重新编译并保存

## inspect_pie_niagara_system

参数 system_path 为完整 Niagara 系统对象路径
只读列出 PIE 组件的激活状态 粒子数量 位置与边界
原生检查会等待当前并行模拟结束 不改变资产

## inspect_pie_actor_properties

只读检查所有 PIE 世界中指定 class_path 的 Actor
property_paths 支持以点分隔的反射属性路径 数组返回数量与前三项 避免大量实例刷屏
返回每个世界的对象数量以及前三个对象的属性样本

## set_struct_array_object

在已签出对象的结构体数组指定元素上创建实例化子对象
参数为 object_path array_property index object_property class_path properties
不修改数组中其它元素 调用后使用 save_assets 保存宿主包

## create_channel_sprite_system

为尚未配置的 Niagara Data Channel 创建 Islands 子对象和共享的线段 Sprite 系统
参数 `channel_path` 指向已有空通道 `system_path` 指向尚不存在的 Game 系统路径
数据字段固定为 Position SpriteAlignment SpriteSize Color 可用于任意批量线段表现
原生图表操作由 BBBNiagaraEditorLibrary 执行 调用入口在 Scripts 注册
拒绝覆盖已有系统与已配置通道 完成后保存两份资产

## configure_persistent_projectile_tracer

参数 `system_path` 指向已有共享子弹 Niagara 系统 `channel_path` 指向其数据通道

把数据通道改为全局共享记录 并让粒子生成时记住槽位 后续每帧从同一槽位更新光段 命中时结束

要求两份资产均已完成 Perforce 独占签出 工具只修改并保存这两份指定资产 无 PIE 时调用

## set_instanced_struct_array

为指定资产结构体中的实例化对象数组创建真实子对象并保存
参数为 `asset_path` `struct_property` `array_property` `instances`
JSON 数组每项包含 `class` 原生类路径和可选的 `properties` 属性对象
适用于 Mass 配置的 `config.traits` 等实例数组
拒绝空引用并在写回后核对实际对象
修改现有资产前要求已独占签出

## create_asset_with_factory

使用原生工厂创建尚不存在的 Game 资产并保存
参数为 `asset_path` `asset_class_path` `factory_class_path` 和可选的 `factory_properties`
拒绝覆盖已有资产

## import_files_from_directory

参数为本地 `source_directory` `destination_path` `extensions` 和可选的 `recursive`
按扩展名调用 UE 原生资产工厂批量导入文件 保留源目录层级并保存生成资产
`extensions` 为 结构化对象数组 例如 `["wav"]` 或 `[".wav"]`
目标必须是空的 `/Game/` 目录 工具拒绝覆盖 重名或超出 5000 个文件的任务
源目录和文件名中的非字母数字 下划线或连字符字符会转换为下划线以符合 UE 资产路径要求
单个源文件未生成资产或生成路径不在目标目录时会报警并停止保存

## reimport_sound_waves

参数为本地 `source_directory` 目标 `/Game/` 内容目录 `destination_path` 可选 `source_suffix` 默认 `_Shot` 和 `recursive` 默认 `true`
按源目录层级寻找 `<原资产名>_Shot.wav` 并原位重导入同名已有 SoundWave 保留资产路径与引用
重导入前验证全部源文件 目标类型 可编辑状态及未保存状态 限制单次最多 256 个
每个资产重导入后检查原路径与有效时长 仅保存该目标资产 失败时报警并停止 后续可重试
不会保存目标目录外的未保存资产 也不会创建新资产

## inspect_pie_player_control

只读检查当前 PIE 中指定玩家的控制器本地性 人物控制状态 视角目标 以及所属组件的激活和 Tick 状态
参数 `player_index` 默认为 `0` 未启动 PIE 或玩家不存在时明确报错 不修改资产或游戏状态

输出包含默认输入映射与鼠标指针显示状态 属性读取失败写入 `inputPropertyErrors` 不把读取失败视为空引用

`camera` 返回玩家实际视点 FOV 以及视角目标上的相机臂当前长度 遮挡检测开关 遮挡收缩状态和未遮挡位置 用于核对真实玩家视角而不是外部拍摄视角

## capture_pie_player_view

按当前玩家相机管理器的实际位置 旋转和 FOV 生成无 UI 的场景截图 用于视角构图验证 不是视口像素截图 不包含 HUD 与相机后处理效果保证
参数 `file_name` 必填且必须是新的 PNG 文件名 `width` 默认 1280 `height` 默认 720 `player_index` 默认 0
输出保存到 `Saved/Diagnostics/PlayerView` 仅在当前 PIE 创建临时 SceneCapture 并在完成或失败后销毁 不修改地图资产 需要启用渲染的宿主

## resize_pie_window

参数 `width` 与 `height` 是目标 PIE 渲染视口像素尺寸
仅调整唯一浮动 PIE 窗口 不调整编辑器主窗口 不改变桌面分辨率 不发送桌面输入
尺寸范围为 320 到 4096 且总像素不超过 8388608 必须正在运行单个浮动 PIE
调整后读取 FSceneViewport 实际像素并按测量差值修正一次 仍不匹配会报警并返回实际宽高 视口内 PIE 或多个浮动 PIE 会明确拒绝
用于视觉验收时 先启动浮动 PIE 再调用此工具 然后通过 Slate Snapshot 获取 PIE 视口引用并使用 `capture_editor_screenshot` 保存真实视口截图

## export_pie_render_target

将当前 PIE 本地玩家持有的临时 Render Target 导出为 PNG 用于检查独立预览世界的实际画面 不修改内容资产

参数为 `target_path` 和仅含文件名的 `file_name` 输出位于 `Saved/Diagnostics/PreviewTarget` 仅支持 `RTF_RGBA8` 目标 拒绝无 PIE 非渲染目标 非本地玩家持有的目标以及覆盖已有文件

此工具需要启用渲染的单一 UE5.8 MCP 宿主 `-NullRHI` 宿主不能用于像素验收

## invoke_pie_actor_function

调用当前 PIE 世界中指定 Actor 的反射函数 参数为 `actor_path` `function_name` 和 位置参数数组 `arguments` 默认 `[]`
仅接受当前 PIE 中已加载 Actor 拒绝编辑器对象 此工具会改变运行时状态 调用前必须确认函数语义与任务授权 不用于资产保存或编辑器生命周期管理

## inspect_asset_properties

只读读取一个或多个 UE 资产的完整路径、类路径和指定编辑器属性。

```json
{
    "asset_paths": ["/Game/BBBC/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_Base"],
    "property_names": ["target_skeleton", "preview_mesh"]
}
```

工具不会修改、保存或签出资产。属性读取失败会写入 `propertyErrors`，不会伪造属性值。

## inspect_blueprint_class_defaults

只读读取一个或多个蓝图生成类默认对象的指定属性 用于检查继承变量在具体蓝图类上的最终默认值
参数 `asset_paths` 是蓝图资产路径数组 `property_names` 是属性名数组
输出同时包含生成类和默认对象路径 属性读取失败写入 `propertyErrors` 不修改或保存资产

## set_blueprint_class_defaults

更新一个蓝图生成类默认对象的指定属性 编译蓝图并在无编译错误后保存
参数 `asset_path` 是蓝图资产路径 `values` 是属性名到目标值的 对象
结构体属性使用嵌套对象表达 对象引用使用 `{"refPath":"/Game/...Asset.Asset"}` 表达
工具拒绝 PIE 期间修改 未独占签出 无效属性 无效引用 编译失败和保存失败
调用后必须使用 `inspect_blueprint_class_defaults` 与 PIE 运行时探针核对最终值和实际动画播放器

## remove_input_action_mappings

按动作资产包路径移除输入映射中的全部对应按键 保留其它映射及其修饰器和触发器
参数 `mapping_context_path` 是输入映射资产路径 `action_paths` 是待移除动作包路径数组
调用前须完成输入映射资产的 Perforce 独占签出 工具会拒绝缺失动作与重复路径 成功后保存该输入映射资产
UE5.8 以 `DefaultKeyMappings` 为实际映射来源 工具调用引擎的 `unmap_all_keys_from_action` 并清理旧 `Mappings` 字段 避免表面移除但运行时仍生效

## refresh_material_instances

刷新指定材质实例的缓存并强制保存，用于修改父材质或纹理参数后清理持久化的旧引用。只接受材质实例路径；类型错误或保存失败会明确报错。调用前须完成 Perforce 独占签出，新建资产须已纳入工作区。

```json
{
    "asset_paths": ["/Game/_Project/Environment/ScifiSkies06/Materials/Instances/MI_ScifiSkies_Skybox_Bg_Inst_06"]
}
```

## duplicate_loaded_actors_to_current_level

将已加载的其他关卡对象直接复制进当前关卡，返回独立对象路径，不创建 Level Instance 或源关卡引用。调用前须签出当前地图、确认无其他未保存地图，并在返回后校验对象数量与保存目标地图。源对象必须仍加载在编辑器内；无效路径或复制数量不符会报错。

```json
{
    "actor_paths": ["/Game/Maps/Source.Source:PersistentLevel.DirectionalLight_0"]
}
```

## 蓝图图表语言映射

实际发现的 `BBBBlueprintGraphToolset` 中 `write_graph` 复用官方蓝图 DSL 写入器 解决本地化节点名称和执行引脚类型与英文 DSL 不一致的问题. 参数为 `graph_path` `code` `node_aliases` `pin_aliases`.

节点映射为英文 DSL 类型到当前编辑器实际类型的 结构化对象。引脚映射为当前编辑器类型到 DSL 类型的对象，例如 `{"执行":"Exec"}`。先使用官方 `find_node_types` 和 `get_node_type_pins` 验证实际名称，不猜测名称。工具只接受 `/Game/` 蓝图直属图表，拒绝 PIE 期间编辑，不修改引擎或编辑器语言。写入会修改目标图表并编译，但不自动保存。失败会明确报警且可能留下部分图表，须检查或撤销，禁止在失败后保存。调用前完成资产独占签出。

编辑器启动由 `Content/Python/init_unreal.py` 加载 Bootstrap 统一注册。

同工具集的 `inspect_owned_objects(asset_path, class_path)` 只读列出指定资产内部的对象路径和类型。用于查找官方 ObjectTools 自动转为 CDO 后无法访问的蓝图内部对象，例如控件设计树或关卡蓝图。控件附带父控件、可见性和文本，不修改对象。后续编辑仍需使用返回的确切对象路径。

`asset_path` 为空时只读枚举指定类型的已加载对象，可用于定位运行时实例；返回结果包含默认对象和编辑器对象，不能把枚举结果直接当作 PIE 对象修改。

`blueprint.format_blueprint_graph(graph_path, node_guids=[])` 调用原版 Graph Formatter 的完整编辑器整理命令 不实现排列算法或自动布线 不修改两个第三方插件 详见 `Docs/BBBGraphFormatterMCP.md`

`invoke_pie_object_function(object_path, function_name, arguments)` 用于运行时蓝图接口验证，支持组件、控件和子系统持有的对象。目标或其所有者链必须属于当前 PIE 世界，否则拒绝。参数为 位置参数数组，结果会返回。此工具会改变运行时状态，调用前必须核对函数语义；不得用于编辑器资产编辑。

`schedule_pie_actor_function(action, actor_path, function_name, arguments, delay_seconds)` 在当前 PIE 世界按游戏秒提交一次公开 Actor 函数调用 同一宿主仅保留一项定时调用 `start` 返回请求时刻 `status` 返回实际执行时刻与返回值 游戏暂停时延迟不推进 PIE 或 Actor 结束时明确失败并注销回调 支持 `{"$guid":"明确的实例 Guid"}` 参数标记 不修改资产或私有黑板

阶段中断测试将定时调用与输入序列放在同一批次 请求时刻必须包含序列中开火与换弹前的游戏帧时长 完成后同时检查定时调用成功 实际手持对象变化 输入释放以及表现收尾 不将跨批次调用产生的等待解释为目标动作阶段

## 扩展原则

### 显式点集 PCG 图

`set_scene_actor_collision(expected_level, actor_paths, enabled)` 通过原生接口同步 Actor 总开关与组件 BlockAll/NoCollision 配置，回读实际状态。最多 400 个显式静态网格演员，要求当前关卡和编辑权限，不自动保存。大型背景与道路装饰面应关闭碰撞，避免导入时的简化凸包将玩家推出场地；必须在重新加载和 PIE 中复验。

`configure_static_mesh_surface_collision(mesh_path, apply_changes=False)` 默认只读检查所有 LOD 分段是否启用碰撞及复杂度。显式开启修改时要求编辑权限，启用各分段碰撞、双面几何和 ComplexAsSimple 并重建网格，不自动保存。适用于不模拟自身物理的静态地表；修改后必须通过实际角色落地验证，不能仅以编辑器射线命中判定通过。

`spawn_static_mesh_batch(expected_level, items)` 在校验关卡、编辑权限、全量输入变换、网格与唯一标签后创建最多400个独立静态网格演员。可选material、folder和collision，输入包含完整location/rotation/scale，不自动保存关卡。中途错误需按已返回/日志中的标签核对，禁止盲目重放。

`remove_scene_mesh_actors(expected_level, actor_paths, dry_run=True)` 只接受最多5000个明确对象路径；先用dry_run预览，再对同一列表执行。仅删除StaticMeshActor与TextRenderActor，其它Actor保留并报告，拒绝PIE、错误世界与无编辑权限。不删除网格资产，不自动保存关卡。

`create_static_mesh_points_graph(graph_path, mesh_path, points, collision=False)` 创建一个 CreatePoints 到 StaticMeshSpawner 的可编辑图。点列表每项包含 `location`、`rotation`、`scale` 三元数组，分别为世界厘米坐标、Pitch/Yaw/Roll 角度和正缩放。每图限制 1–12000 点，拒绝 PIE、非有限数值、无效网格及已有图覆盖，成功保存后日志报告点数。默认关闭实例碰撞，需阻挡的组显式开启。

使用已有 `generate_and_inspect_pcg` 在目标关卡的 PCG Actor 生成并回读实际实例数。输入点应提前完成地形贴合与道路/建筑避让；本工具不自行推断落点，不把点数当作视觉或性能验收。修改图后不得盲目重复生成，先检查生成状态。

点集较大时 `points` 可传入 `{"file":"<项目内布局 JSON 的绝对路径>","group":"<分组名>"}` 读取该文件的 `pcg_groups` 中对应分组. 尖括号内容需替换为本任务的实际输入. 文件必须是实际项目目录内的 JSON 不接受外部路径. 旋转数组始终按 Pitch Yaw Roll 解释 内部显式使用命名参数 禁止依赖 Unreal Python 构造器的位置参数顺序. 场景布置后应通过官方 ActorTools 回读至少一个非零角度对象 避免静态输入正确但实际轴错误.

`remove_empty_animation_notify_track(asset_path, track_name)` 支持动画序列和蒙太奇 只删除已清空的指定通知轨道
工具拒绝 PIE 未独占签出 非动画资产 不存在的轨道和仍含事件的轨道 成功后保存并返回完整通知列表
重建通知布局时先用 `replace_animation_notify_track` 清空旧事件 再调用本工具删除旧空轨道

### 网格实物缩略图

`render_asset_thumbnails(requests)` 接收显式列表 每项为 `source` 网格包路径 `destination` 纹理包路径以及可选 `yaw` 观察方向 默认七十五度 一次最多一百项

工具由 `BBBAssetThumbnailEditorLibrary` 在临时独立场景按真实顶点边界生成 512 方形 PNG 再导入普通 UI Texture2D 每项立即保存 已有目标必须独占签出成功 失败项明确返回 不修改源网格或当前关卡 需要启用渲染的宿主 不支持 NullRHI 组合预设需另行提供实际组合网格

输出源图位于项目 Saved/Diagnostics/AssetThumbnails 纹理不生成 mip 且不流送 用于解决衣物共用骨架导致取景过远的问题

工具拒绝 PIE 期间导入 等待源材质编译完成后分别捕获色调映射后的浮点颜色与反向不透明度 输出带透明背景的实际部件图 导入任务必须返回实际对象路径才允许报告成功 不将已有旧纹理当成新导入结果

遇到现有 MCP 无法完成的功能时，先判断是否只是对象路径、属性名或批量参数不足。能用通用输入表达时，扩展本工具；只有通用接口无法安全表达明确领域语义时，才新增领域工具。新增工具集时更新 `Content/Python/init_unreal.py`；扩展已注册工具集时无需改动注册文件。每次扩展都须更新本文档或 `AGENTS.md`，并通过`find_tools`、`describe_tool`、`submit_batch` 与结果回读 验证。

### 子弹表面反馈与曳光收尾

`create_projectile_sprite_material(material_path, kind)` 新建 Niagara Sprite 材质 `tracer` 提供亮头 收尖尾与少量光晕 `impact` 提供软边粒子 两者由粒子颜色控制颜色和淡出 拒绝覆盖已有资产

`configure_projectile_tracer_finish(system_path, channel_path, material_path)` 更新已有持续曳光图表 增加 `Ending` 通道字段 结束帧捕获末位置 尺寸与原色 后续不再应用槽位读取值 五十毫秒后回收粒子 防止槽位复用串弹 新生粒子首帧不额外更新

`configure_projectile_impact_system(channel_path, system_path, material_path)` 将命中通道配置为空间岛 创建或重建三个 CPU 发射器分别按 `Surface` 的 0 1 2 筛选硬表面 金属 血肉 表面事实仅含 `Position` `Normal` `Surface` 读取上一帧完整批次 后续粒子独立运动淡出 不持有命中历史

以上写入入口拒绝 PIE 新资产须处于 Perforce 可添加映射 已有资产须提前独占签出 原生图表构建由接入项目编辑器模块的 `BBBNiagaraEditorLibrary` 提供 写入后须通过 `inspect_niagara_graphs` 核对所有脚本编译状态

# 角色输入与自动化验证

`inspect_pie_characters` 同时只读检查当前宿主所有 PIE 世界中的角色阶段、生命、装备使用许可、速度、移动胶囊、动画来源阶段、关键骨骼及物理模拟。它不从显示结果推演远端玩法。

`apply_pie_damage` 使用引擎伤害入口提交真实伤害，来源必须是同一 PIE 世界本机控制的 Pawn。工具不改写生命字段，返回的只是适配器接受数值，实际结果需在后续帧通过只读查询验证。跨连接测试分别选取相应世界中的来源和目标副本。

`run_automation_tests` 在无 PIE 时启动已注册测试的明确前缀，拒绝包含命令分隔符的输入。启动返回值不表示测试通过，须读取引擎最终日志；测试运行期间不能启动 PIE 或重载被测试模块。

- HUD 网格轮廓请求可传 excluded_material_slots 逗号分隔材质槽名 排除皮肤等非物品几何 并按剩余几何重新取景 不修改源网格。

- 网格缩略图请求支持 excluded_material_slots 与 output_directory 排除非物品表面 输出到 Saved/temp 对应任务目录。
- `render_mesh_silhouettes` 请求可选 `line_art=true` 输出正交白色边缘线稿和微弱内部填充，尺寸为 512×512；不显示排除材质所属的人体表面。
- `render_asset_thumbnails` 请求可选 `orthographic=true` 使用无俯视的正交视角，以 `yaw` 明确物品正面方向，避免透视歪斜。
- `rebind_asset_import_sources(requests)` 将指定资产的第一个导入源文件绑定到项目 Content 内的永久文件，保留资产内容、逐项签出保存，用于清理临时生成目录前固定重导入来源。
- 图标和详情成图的 `mesh` 或 `source` 可用分号连接最多八个骨骼网格，组合物品按同一正面方向平放排开；不创建合并模型或第二份物品。
- 隐藏官方宿主启动脚本可选 `-EnableSlateInspector` 启用官方 Slate 树观察、按键、拖动和截图工具；视觉测试须同时启用 `-EnableRendering`，仍只允许一个可写宿主。
`render_asset_thumbnails` 的正交输出按非透明网格边界裁切并保留 12 像素留白 保持网格比例与水平观察方向 便于直接用于详情图。
`dispatch_slate_key(key_name, pressed)` 发送当前聚焦控件的真实 Slate 按下或松开事件 支持 Tab 等持续按键 调用者必须在操作结束后松开 使用 Two 等引擎按键名称。
成对物件的图标与缩略图请求支持 `pack_sides: true`。仅适用于分列 X 轴两侧的单个骨骼网格。工具先移除明确排除的材质三角面 再平移两侧物件以减少空隙 不旋转或改变外形 不修改源网格。
`activate_slate_button(label)` 直接执行包含完整文本的唯一可用 Slate 按钮委托 重名时拒绝执行 不移动系统光标 不发送系统按键 不激活窗口 适合前台运行其它程序时的后台界面验收。
PIE 反射调用中的 Guid 返回值按标准字符串序列化 位置参数可显式使用 `{"$guid":"有效 Guid 字符串"}` 传入稳定实例身份 格式无效时在调用前拒绝 不转换其它普通参数。

### 物品详情与轮廓清晰度

`spawn_configured_pie_actor(class_path, world_path, properties, location)` 只在明确的当前 PIE 世界中延迟生成演员 配置完成后才执行构造与 BeginPlay 不修改类默认对象或关卡资产 引用及引用数组使用 `refPath` 属性写入或完成生成失败时销毁本次演员 不会代替调用者判断后续行为是否成立。

此入口使用 `BBBBlueprintEditorLibrary.BeginTransientPIEActor` 与 `FinishTransientPIEActor` 的编辑器专用原生桥接 不依赖未暴露到 UE Python 的 GameplayStatics 内部生成函数 创建对象带有 Transient 标记 不会进入关卡保存。

`capture_niagara_asset(system_path, age_seconds, camera_offset, file_name)` 在带渲染的 PIE 世界中建立瞬态特效 以 120 Hz 推进到指定年龄并从明确方向拍摄 只写入 `Saved/temp/任务名/图像.png` 拒绝覆盖和目录链接 结束或失败均销毁预览演员 不修改源特效 不能代替实际开火时序验收。

特效拍摄返回 `pending` 后需用 `get_niagara_capture_status()` 读取跨帧渲染结果 DesiredAge 固定模拟年龄 并等待四个渲染帧及捕获提交后再导出 工具活动结束前不得停止 PIE 或让出宿主。

`configure_weapon_handling_graphs(camera=true)` 从 `BBBEquipmentAnimInstance` 的通用只读接口获取镜头贡献 不依赖 Rifle 类型 无装备时返回无贡献 每个具体装备动画实例可覆盖四个镜头参数 getter。

项目原生 `render_mesh_thumbnail` 使用 1024 方形采样后按真实透明边界裁切 用于背包的大幅详情图 避免将小图放大。
`render_mesh_silhouettes` 的线稿突出外轮廓和主要材质分界 抑制细碎折面 使用较宽描线保证普通背包格子中的可读性。

### 材质代表着色器统计

`editor.inspect_material_statistics(asset_paths)` 读取一至三十二个不重复的 `/Game/` 材质或材质实例包路径，拒绝对象子路径、非材质资产与缺失资产。完整批次先核对类型，不修改或保存资产，可在共享编辑宿主或受限测试宿主调用。

工具组合 UE `MaterialEditingLibrary.get_statistics` 返回代表顶点与像素着色器指令数、采样器数、顶点与像素纹理采样数、虚拟纹理采样数、UV 标量数和自定义插值标量数。引擎可能提交并等待着色器编译，因此读取可能耗时；该调用不代表角色 GPU 帧时间。

`platform` 来自引擎宿主平台查询；当前接口无法直接确认的 `shaderPlatform` 与 `featureLevel` 明确返回 `unknown`。`-NullRHI` 不调用统计 API，每项返回 `statisticsAvailable=false`、`statistics=null` 与 `NULL_RHI`。代表顶点或像素指令缺失、或统计含负值时同样返回空统计，并标记 `REPRESENTATIVE_SHADER_STATISTICS_INCOMPLETE` 与警告，不将零或缺失结果当作低成本。

前后成本只比较同一渲染宿主、相同配置与已核实资产版本的非空统计。无贴图材质的零采样器或零纹理采样可合法保留。

### 骨骼网格参考姿势与源蒙皮检查

`editor.inspect_skeletal_mesh_skinning(mesh_paths)` 只读接收一至八个不重复的 `/Game/` 骨骼网格包路径，支持官方绑定数组。完整批次先检查类型、骨架关联及目标网格未保存修改，再创建官方 `SkeletonModifier` 与 `SkinWeightModifier` 的临时数据副本；仅用 `set_skeletal_mesh` 加载副本，不调用骨架或权重编辑、提交、归一化、保存或标脏操作。

每项返回 `mesh`、`skeleton`、`vertexCount`、`boneCount`、`bones` 与 `weights`。`bones` 来自网格本身的实际参考骨架，包含 `name`、`parent` 及 `local.position/rotation/scale`；根骨父级为空，位置为厘米，旋转为 XYZW 四元数，变换在父骨局部空间，不使用关联 Skeleton 资产的参考姿势代替网格数据。

`weights` 为字符串顶点编号到 `骨名: 权重` 的完整字典，编号属于 LOD0 MeshDescription 源顶点，不等同于渲染顶点或重新导入后的 DCC 编号。不补全、不归一化、不过滤零值或空权重。缺少任一官方 modifier 类时返回 `supported=false`、`SKELETAL_MESH_MODIFIERS_UNAVAILABLE`、`missingClasses` 与空 `meshes`，不伪造数据。

读取失败、空参考骨架、无效顶点数或无法序列化的非有限源数据明确失败。该检查可在 editor/test 与 NullRHI 中运行，前提是插件已加载且资产具有 LOD0 MeshDescription；它用于参考骨架和蒙皮归因，不代表动态姿势或肉眼变形验收。

# 嵌套属性读取

`editor.configure_data_asset` 保存明确的数据资产属性 支持 `structType` 加 `properties` 的结构描述 `enumType` 加 `value` 的枚举 `classPath` 与 `refPath` 的引用 以及 `mapValues` 映射 数组逐项转换

`editor.inspect_pie_character_runtime` 只读当前 PIE 玩家动画与真实物品状态 `items` 返回实际主手实例 数量 使用序号 当前使用状态 两类快捷选择和有物品的格子 不更新角色或物品

`editor.repair_blueprint_function_references` 接受旧函数名到新函数名的明确映射 直接更新节点并编译保存 不创建运行时兼容函数

`editor.configure_boolean_pose_overlay` 在实际编译动画图的基础层前端插入混合 按线程安全布尔函数将非循环序列平滑混合到指定骨骼分支 下半身继续来自输入姿势 原有骨骼控制节点与连接完整保留 拒绝只继承资产覆盖的派生动画蓝图 避免图存在但不参与运行 可选 `sequence_property` 将序列引脚绑定到已有动画配置变量 派生层只覆盖该变量的默认序列

`editor.inspect_asset_properties` 的 `property_names` 支持点分隔路径 例如 `items.definition` 和 `items.appearance.mesh` 遇到数组时逐项读取剩余路径并保留原索引 不改变资产 数组和映射以 JSON 容器返回

`editor.set_pie_player_view` 需要当前 PIE 存在本地玩家 `position` 是三分量世界厘米坐标 `rotation` 是俯仰 偏航 滚转角度 `fov` 是水平视野角度 临时相机在同一世界复用并随 PIE 回收 不修改源相机 光照 画质或资产 可结合 `editor.capture_pie_player_view` 检查原场景亮部和阴影表现

2026-10-16 曲线编辑直接遵守资产写入网关和本地文件可写权限，不再查询 Perforce 独占签出，也不生成动画或 JSON 备份。仍保留未保存修改保护、有限数值与范围校验、写入后和保存后逐键回读，以及真实 Cubic 插值和水平切线检查。无备份边界及三次曲线的 8 项专项检查通过。


2026-10-17 动画层动作配置：新增 `editor.configure_animation_montage_selector` 为继承的无参纯函数配置同骨架蒙太奇固定返回值。拒绝非纯函数 不匹配返回类型及已有连线返回逻辑 编译成功后保存。`editor.configure_action_montage` 保留目标已有的 UpperBody 或 UpperBodyAdditive 槽位 并拒绝其它动作槽位。本轮按用户要求不运行自动化或 PIE 验收。

原生资产删除在明确目标包集合内解除动画数据模型临时控制器的根引用 避免无持久引用动画仍被临时控制器阻止删除 不处理其它包控制器 不直接删除资产文件 不创建备份。

## 保持参考姿势重挂网格插槽

`editor.reparent_skeletal_mesh_socket(mesh_path, socket_name, parent_bone_name, dry_run=true)` 只接受明确的自有骨骼网格、已存在的插槽和真实骨骼。原生计算新父骨参考空间的相对变换，并回报重挂前后参考姿势的位置与旋转误差；默认只读检查。设置 `dry_run=false` 后通过写入网关保存网格。

原插槽若来自共享 Skeleton，创建该网格自身的同名插槽，保持共享 Skeleton 原样；原插槽已属于网格时直接更新。工具保留静态参考位置与角度，运行时插槽随新父骨运动。此操作不验证完整运行时动画图，调用者还需检查目标机构的真实骨轨和最终握持几何。

## 原生定长数组属性只读检查

`editor.inspect_asset_properties` 的既有点路径读取现在同时识别 `unreal.FixedArray`，例如 `blend_parameters.min`、`blend_parameters.grid_num` 和 `interpolation_param.interpolation_time`。逐项保留原生定长数组顺序、剩余结构路径和值；直接读取定长数组叶值也按 JSON 数组序列化，不再把它降为字符串或对数组错误调用结构体属性读取。

没有新增工具或改变参数契约，不写资产，不推测不存在的字段；缺字段仍返回原错误。四项离线专项回归覆盖实际独立数组类型、轴字段顺序、数组叶值、动态与定长嵌套以及缺字段失败；原生宿主需与本轮其他工具修改统一重载后验收。

2026-10-19 原生核验：UE5.8 后台宿主实际读取两份 `BS_MM_Rifle_Jog_Leans` 的 32 项公共设置及 1D `scale_animation`，所有运行时设置、样本与定长轴和插值值逐项相等，无属性读取错误或脏包。预览网格字段未公开给 Python，单独尝试保留其真实读取错误，不把缺字段当作空值相等；比较证据在本次任务临时目录，工具本身不合并或删除资产。
