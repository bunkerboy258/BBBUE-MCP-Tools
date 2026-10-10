# BBB 通用编辑器 MCP

## 明确字体源导入

`import_font_faces(requests_json)` 每项指定项目 Content 内永久 `.ttf` 或 `.otf` 的 `source` 与新 `destination` 包路径。仅创建内联 `FontFace` 不生成额外 `Font` 不覆盖既有资源。批量一至十六项。导入前检查源文件与 Perforce 写入许可。

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
参数为 object_path array_property index object_property class_path properties_json
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
参数为 `asset_path` `struct_property` `array_property` `instances_json`
JSON 数组每项包含 `class` 原生类路径和可选的 `properties` 属性对象
适用于 Mass 配置的 `config.traits` 等实例数组
拒绝空引用并在写回后核对实际对象
修改现有资产前要求已独占签出

## create_asset_with_factory

使用原生工厂创建尚不存在的 Game 资产并保存
参数为 `asset_path` `asset_class_path` `factory_class_path` 和可选的 `factory_properties_json`
拒绝覆盖已有资产

## import_files_from_directory

参数为本地 `source_directory` `destination_path` `extensions_json` 和可选的 `recursive`
按扩展名调用 UE 原生资产工厂批量导入文件 保留源目录层级并保存生成资产
`extensions_json` 为 JSON 字符串数组 例如 `["wav"]` 或 `[".wav"]`
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

调用当前 PIE 世界中指定 Actor 的反射函数 参数为 `actor_path` `function_name` 和 JSON 位置参数数组 `arguments_json` 默认 `[]`
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
参数 `asset_path` 是蓝图资产路径 `values_json` 是属性名到目标值的 JSON 对象字符串
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

实际发现的 `BBBBlueprintGraphToolset` 中 `write_graph` 复用官方蓝图 DSL 写入器 解决本地化节点名称和执行引脚类型与英文 DSL 不一致的问题. 参数为 `graph_path` `code` `node_aliases_json` `pin_aliases_json`.

节点映射为英文 DSL 类型到当前编辑器实际类型的 JSON 字符串对象。引脚映射为当前编辑器类型到 DSL 类型的对象，例如 `{"执行":"Exec"}`。先使用官方 `find_node_types` 和 `get_node_type_pins` 验证实际名称，不猜测名称。工具只接受 `/Game/` 蓝图直属图表，拒绝 PIE 期间编辑，不修改引擎或编辑器语言。写入会修改目标图表并编译，但不自动保存。失败会明确报警且可能留下部分图表，须检查或撤销，禁止在失败后保存。调用前完成资产独占签出。

编辑器启动由 `Content/Python/init_unreal.py` 注册。已运行宿主可通过 `run_editor_script` 加载该工具集脚本本身完成注册，不创建临时任务脚本。

同工具集的 `inspect_owned_objects(asset_path, class_path)` 只读列出指定资产内部的对象路径和类型。用于查找官方 ObjectTools 自动转为 CDO 后无法访问的蓝图内部对象，例如控件设计树或关卡蓝图。控件附带父控件、可见性和文本，不修改对象。后续编辑仍需使用返回的确切对象路径。

`asset_path` 为空时只读枚举指定类型的已加载对象，可用于定位运行时实例；返回结果包含默认对象和编辑器对象，不能把枚举结果直接当作 PIE 对象修改。

`optimize_blueprint_node_layout(graph_path, horizontal_spacing=320, vertical_spacing=180, dry_run=False)` 使用原生引脚类型区分执行流 姿势流与数据流 不依赖编辑器显示语言 连续执行节点及动画姿势节点按真实主引脚高度保持水平主链 分支按照输出引脚顺序分道 汇合节点放在上游之后 纯数据节点向消费者左侧收紧 共享节点保持一份 没有执行线或姿势线的图表按输入 计算 输出排列 无固定注释框约束时独立逻辑链左对齐并上下分区 不沿用旧画布的散落位置

间距现在表示最小步距而非节点尺寸之外的额外大块留白 水平步距至少容纳节点宽度与六十四单位安全间隙 同列节点至少留三十二单位间隙 两个间距必须为正整数且不超过 `10000` 拒绝布尔值 浮点数和字符串伪整数 执行主链的数据块会为分支预留必要空间 不保证所有连线都能无交叉

固定注释框不移动也不缩放 原生归属和完全位于框内的节点共同作为分组约束 空间允许时在框内整理 框太小或成员归属嵌套交叠时保留成员原位并报警 其它逻辑链选择原分组附近的空位避开固定注释框 不统一推到画布底部 若跨框调整把原本前向的连线变成回流或增加重叠 则保留整条连通链原位并报警 环路只产生视觉回流 不删改真实连线

先传 `dry_run=True` 获取只读计划 预览不创建事务 不签出 不移动 不保存 节点位置位于返回的 `positions` 中 `before` 与 `after` 提供范围 重叠 逆向执行线 数据线 姿势线及 `wireNodeIntersections` 穿节点计数 `plannedMoves` 为拟移动数量 `moved` 为实际移动数量 `poseEdges` 为姿势连接数量 `measurement` 必须为 `SlateFullDetail` `estimatedSizes` 必须为空 不允许估算尺寸代替真实显示尺寸

连线检查使用真实引脚锚点与宿主前向 回流曲线样式 自适应细分后检查非端点节点并保留八单位安全区 有界调整辅助节点避开穿线 不移动固定注释框 不打散姿势主链 不添加重路由节点 不修改原始连接 无法消除时在 `wireNodeHits` 返回连线与阻挡节点并报警 该检查不等同于消除线与线交叉 自定义节点连接绘制策略仍需可视复核

确认目标图表并完成 Perforce 独占签出后传 `dry_run=False` 应用 工具拒绝 PIE 未签出 他人签出 冲突 或包含节点重叠及连线穿节点的写入 不自动签出 不自动保存 不提交 Perforce 写入在编辑器事务中进行 每个被移动节点单独记录撤销 写入后回读坐标和原始连线 固定注释 失败时只恢复本次坐标并报警 不宣称回滚其它并行编辑 完成后由调用方检查图表再决定是否保存

现有宿主更新本工具时 使用已发现的 `run_editor_script` 执行仓库 `Scripts/BBBBlueprintLayout.py` 该文件通过官方注册生命周期只重载排版计算与 `BBBBlueprintGraphToolset` 不重载其它并行工具 不重启编辑器 然后重新 `list_toolsets` 与 `describe_toolset` 确认 `dry_run` 参数 初次启动由正常注册入口加载 不能把脚本执行成功当作实际排版验证

几何预检依赖接入项目 `BBBBlueprintEditorLibrary.measure_blueprint_graph_visual_geometry` 原生只读接口 该接口复用基础节点及固定注释归属查询 使用标准 Slate 节点控件的完整详细显示尺寸和引脚锚点测量 返回姿势引脚类型与连线样式 在游戏线程和已初始化 Slate 的宿主中调用 支持隐藏 `-NullRHI` 宿主 不读取受保护的 Python 字段 不修改节点或保存资产 未提供此接口 测量失败 或连接引脚缺少显示锚点时明确拒绝 不回退估算尺寸 修改原生接口后必须先编译编辑器模块并重新启动宿主

`invoke_pie_object_function(object_path, function_name, arguments_json)` 用于运行时蓝图接口验证，支持组件、控件和子系统持有的对象。目标或其所有者链必须属于当前 PIE 世界，否则拒绝。参数为 JSON 位置参数数组，结果会返回。此工具会改变运行时状态，调用前必须核对函数语义；不得用于编辑器资产编辑。

## 扩展原则

### 显式点集 PCG 图

`set_scene_actor_collision(expected_level, actor_paths, enabled)` 通过原生接口同步 Actor 总开关与组件 BlockAll/NoCollision 配置，回读实际状态。最多 400 个显式静态网格演员，要求当前关卡和编辑权限，不自动保存。大型背景与道路装饰面应关闭碰撞，避免导入时的简化凸包将玩家推出场地；必须在重新加载和 PIE 中复验。

`configure_static_mesh_surface_collision(mesh_path, apply_changes=False)` 默认只读检查所有 LOD 分段是否启用碰撞及复杂度。显式开启修改时要求编辑权限，启用各分段碰撞、双面几何和 ComplexAsSimple 并重建网格，不自动保存。适用于不模拟自身物理的静态地表；修改后必须通过实际角色落地验证，不能仅以编辑器射线命中判定通过。

`spawn_static_mesh_batch(expected_level, items_json)` 在校验关卡、编辑权限、全量输入变换、网格与唯一标签后创建最多400个独立静态网格演员。可选material、folder和collision，输入包含完整location/rotation/scale，不自动保存关卡。中途错误需按已返回/日志中的标签核对，禁止盲目重放。

`remove_scene_mesh_actors(expected_level, actor_paths, dry_run=True)` 只接受最多5000个明确对象路径；先用dry_run预览，再对同一列表执行。仅删除StaticMeshActor与TextRenderActor，其它Actor保留并报告，拒绝PIE、错误世界与无编辑权限。不删除网格资产，不自动保存关卡。

`create_static_mesh_points_graph(graph_path, mesh_path, points_json, collision=False)` 创建一个 CreatePoints 到 StaticMeshSpawner 的可编辑图。点列表每项包含 `location`、`rotation`、`scale` 三元数组，分别为世界厘米坐标、Pitch/Yaw/Roll 角度和正缩放。每图限制 1–12000 点，拒绝 PIE、非有限数值、无效网格及已有图覆盖，成功保存后日志报告点数。默认关闭实例碰撞，需阻挡的组显式开启。

使用已有 `generate_and_inspect_pcg` 在目标关卡的 PCG Actor 生成并回读实际实例数。输入点应提前完成地形贴合与道路/建筑避让；本工具不自行推断落点，不把点数当作视觉或性能验收。修改图后不得盲目重复生成，先检查生成状态。

点集较大时 `points_json` 可传入 `{"file":"<项目内布局 JSON 的绝对路径>","group":"<分组名>"}` 读取该文件的 `pcg_groups` 中对应分组. 尖括号内容需替换为本任务的实际输入. 文件必须是实际项目目录内的 JSON 不接受外部路径. 旋转数组始终按 Pitch Yaw Roll 解释 内部显式使用命名参数 禁止依赖 Unreal Python 构造器的位置参数顺序. 场景布置后应通过官方 ActorTools 回读至少一个非零角度对象 避免静态输入正确但实际轴错误.

`remove_empty_animation_notify_track(asset_path, track_name)` 支持动画序列和蒙太奇 只删除已清空的指定通知轨道
工具拒绝 PIE 未独占签出 非动画资产 不存在的轨道和仍含事件的轨道 成功后保存并返回完整通知列表
重建通知布局时先用 `replace_animation_notify_track` 清空旧事件 再调用本工具删除旧空轨道

### 网格实物缩略图

`render_asset_thumbnails(requests_json)` 接收显式列表 每项为 `source` 网格包路径 `destination` 纹理包路径以及可选 `yaw` 观察方向 默认七十五度 一次最多一百项

工具由 `BBBAssetThumbnailEditorLibrary` 在临时独立场景按真实顶点边界生成 512 方形 PNG 再导入普通 UI Texture2D 每项立即保存 已有目标必须独占签出成功 失败项明确返回 不修改源网格或当前关卡 需要启用渲染的宿主 不支持 NullRHI 组合预设需另行提供实际组合网格

输出源图位于项目 Saved/Diagnostics/AssetThumbnails 纹理不生成 mip 且不流送 用于解决衣物共用骨架导致取景过远的问题

工具拒绝 PIE 期间导入 等待源材质编译完成后分别捕获色调映射后的浮点颜色与反向不透明度 输出带透明背景的实际部件图 导入任务必须返回实际对象路径才允许报告成功 不将已有旧纹理当成新导入结果

遇到现有 MCP 无法完成的功能时，先判断是否只是对象路径、属性名或批量参数不足。能用通用输入表达时，扩展本工具；只有通用接口无法安全表达明确领域语义时，才新增领域工具。新增工具集时更新 `Content/Python/init_unreal.py`；扩展已注册工具集时无需改动注册文件。每次扩展都须更新本文档或 `AGENTS.md`，并通过官方 MCP 的 `list_toolsets`、`describe_toolset`、`call_tool` 验证。

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
- `rebind_asset_import_sources(requests_json)` 将指定资产的第一个导入源文件绑定到项目 Content 内的永久文件，保留资产内容、逐项签出保存，用于清理临时生成目录前固定重导入来源。
- 图标和详情成图的 `mesh` 或 `source` 可用分号连接最多八个骨骼网格，组合物品按同一正面方向平放排开；不创建合并模型或第二份物品。
- 隐藏官方宿主启动脚本可选 `-EnableSlateInspector` 启用官方 Slate 树观察、按键、拖动和截图工具；视觉测试须同时启用 `-EnableRendering`，仍只允许一个可写宿主。
`render_asset_thumbnails` 的正交输出按非透明网格边界裁切并保留 12 像素留白 保持网格比例与水平观察方向 便于直接用于详情图。
`dispatch_slate_key(key_name, pressed)` 发送当前聚焦控件的真实 Slate 按下或松开事件 支持 Tab 等持续按键 调用者必须在操作结束后松开 使用 Two 等引擎按键名称。
成对物件的图标与缩略图请求支持 `pack_sides: true`。仅适用于分列 X 轴两侧的单个骨骼网格。工具先移除明确排除的材质三角面 再平移两侧物件以减少空隙 不旋转或改变外形 不修改源网格。
`activate_slate_button(label)` 直接执行包含完整文本的唯一可用 Slate 按钮委托 重名时拒绝执行 不移动系统光标 不发送系统按键 不激活窗口 适合前台运行其它程序时的后台界面验收。
PIE 反射调用中的 Guid 返回值按标准字符串序列化 位置参数可显式使用 `{"$guid":"有效 Guid 字符串"}` 传入稳定实例身份 格式无效时在调用前拒绝 不转换其它普通参数。

### 物品详情与轮廓清晰度

`spawn_configured_pie_actor(class_path, world_path, properties_json, location)` 只在明确的当前 PIE 世界中延迟生成演员 配置完成后才执行构造与 BeginPlay 不修改类默认对象或关卡资产 引用及引用数组使用 `refPath` 属性写入或完成生成失败时销毁本次演员 不会代替调用者判断后续行为是否成立。

此入口使用 `BBBBlueprintEditorLibrary.BeginTransientPIEActor` 与 `FinishTransientPIEActor` 的编辑器专用原生桥接 不依赖未暴露到 UE Python 的 GameplayStatics 内部生成函数 创建对象带有 Transient 标记 不会进入关卡保存。

`capture_niagara_asset(system_path, age_seconds, camera_offset, file_name)` 在带渲染的 PIE 世界中建立瞬态特效 以 120 Hz 推进到指定年龄并从明确方向拍摄 只写入 `Saved/temp/任务名/图像.png` 拒绝覆盖和目录链接 结束或失败均销毁预览演员 不修改源特效 不能代替实际开火时序验收。

特效拍摄返回 `pending` 后需用 `get_niagara_capture_status()` 读取跨帧渲染结果 DesiredAge 固定模拟年龄 并等待四个渲染帧及捕获提交后再导出 工具活动结束前不得停止 PIE 或让出宿主。

`configure_weapon_handling_graphs(camera=true)` 从 `BBBEquipmentAnimInstance` 的通用只读接口获取镜头贡献 不依赖 Rifle 类型 无装备时返回无贡献 每个具体装备动画实例可覆盖四个镜头参数 getter。

项目原生 `render_mesh_thumbnail` 使用 1024 方形采样后按真实透明边界裁切 用于背包的大幅详情图 避免将小图放大。
`render_mesh_silhouettes` 的线稿突出外轮廓和主要材质分界 抑制细碎折面 使用较宽描线保证普通背包格子中的可读性。
