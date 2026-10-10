# 独立仓库接入

## 公共契约与能力校验

项目工具通过 `BBBMcpCapabilities.mcp_tool` 进入官方注册表，保持既有公开工具名称、参数和 UE 返回包装。业务根结果 `success=false` 或非空 `error` 进入官方工具错误通道；嵌套的资产诊断字段不代表调用本身失败。客户端共用 `MCP.mcp_result.decode_tool_result` 解码文本或结构化返回。调用失败不自动重试。

`McpSession.call_many` 复用会话顺序发送请求 每项分别检查权限和结果 失败时保留 `McpBatchError.failed_index` `failed_call` 和 `completed_results`.
已经完成的动作继续保留 调用者据实际结果处理后续步骤.
共享宿主使用已注册的专用工具执行操作.

准备好完整参数后使用 `McpSession.run_write_batch` 完成持续排队 连续调用和阶段交接.
`McpWriteBatchError.phase` 标明排队 执行或交接阶段 `completed_results` 保留已完成请求.
等待结束后排队顺序保持 原任务可继续领取或调用 `cancel_editor_write` 取消申请.
执行或交接受阻时原任务继续持有阶段 并核对实际活动和操作结果.

占用信息通过 `inspect_editor_tasks` 以及 `result._meta["bbb/editor_state"]` 获取.
工具发现文字和使用指南同时展示当前占用.
按 `revision` 等待状态变化 根据 `summary.caller` 安排共享查询 参数准备和编辑领取.
工具描述中的 `bbb/access` 来自唯一 `MCP.mcp_access_policy` 分类 与网关实际权限检查保持一致.
实际编辑授权和阶段结束核对现场状态 详细参数见 [共享宿主任务保护](BBBMcpTaskProtection.md).

启动注册集合与项目领域路由来自唯一 `BBBMcpCapabilities.TOOLSET_ROUTES`。指南的 `routes` 只含当前已注册入口，`unavailable_routes` 单独报告未注册的官方入口。不得通过猜测名称或临时注册替代实际发现。

`inspect_mcp_dependencies.modules` 包含逐工具 `tools` 的静态可达原生类、函数及缺失符号。模块汇总为保守诊断，调用时按具体工具检查。参数控制的业务条件、动态反射路径、资产类型和渲染要求仍需工具自身预检。源码元数据只缓存至注册更新，不缓存资产、签出或实际注册状态。

第三方 `list_available_actions.domains` 只列当前可用动作，`actions` 保留完整白名单动作的参数、原生依赖和可用状态。缺失旧 `MCPythonHelper` 时 `editor.get_open_assets` 不可用且调用会明确拒绝；不新增旧接口兼容层。

项目资产写入共用 `BBBAssetWritePolicy.require_asset_write`，检查 PIE、明确包路径、Perforce 连接、最新状态、独占签出或待添加状态和新目标冲突。批量查询去重并关闭源控状态缓存，不自动签出、添加、保存或提交。`require_write_access` 对资产子对象检查所属包，对演员保留官方关卡实例编辑规则。原生写入及删除流程的专用安全检查仍保留；此公共模块不替代其业务约束。

工具更新同时更新 `Tests/tool_schema_baseline.json`。源码门禁要求注册集合和公开工具集合完全相等，宿主门禁逐项比对完整输入与输出结构；禁止只检查旧基线是新接口的子集。`verify_live_mcp.py` 输出的 `schemas_compared` 是实际完成契约比对数量。并行未提交工具需连同自身契约一起提交，不能混入其他任务。

统一重载在 PIE、运动采样、姿势截图或群体测量仍活动时拒绝，避免丢失其他会话的回调。重载完成后重新发现，保持宿主已有性能配置。

## 蓝图读取与请求内排版效率

AI 只需要节点 引脚 连接 引用和已有注释时优先调用 `BBBBlueprintGraphToolset.inspect_blueprint_graph_logic(graph_path)` 该入口通过原生 `InspectBlueprintGraphLogicalSnapshot` 导出逻辑快照 不创建 Slate 节点控件 不测量显示几何 `layoutSupported` 只表示图表结构支持布局 实际显示测量成功与否仍由排版阶段检查

需要完整显示尺寸和引脚锚点时调用既有 `inspect_blueprint_graph` 或明确的排版预览 两种读取共用逻辑导出和快照校验值 `snapshot` 包含逻辑 坐标及注释状态 不包含 Slate 测量几何 旧会话持有的校验值必须重新读取 不提供旧值兼容 不建立长期资产状态缓存

`annotate_blueprint_graph` 从逻辑快照准备请求 原生校验结果在同一次调用中复用 预览前后仍检查原图是否变化 正常 `dry_run` 只对瞬态预览图完成一次完整几何测量 无改动请求不进行几何测量 写入保留独立源控预检 写前测量 最终状态检查及写后回读 不自动保存或提交

连线避障使用双向横轴索引缩小碰撞候选范围 预建关联边集合并复用同一次计算的曲线采样 不缓存跨请求节点状态 不改变安全间隙 曲线精度 迭代上限及稳定候选顺序 碰撞计数仍通过原始精确线段检查产生

`Tests/benchmark_blueprint_read_layout.py --baseline <提交> --repeats 3` 在内存中载入指定提交的算法 对同输入比较完整排版结果与耗时 `--snapshot-stdin` 可读取单行含 `geometry` 的代表图表快照 `--graph <完整图表路径>` 则通过实际发现的官方 MCP 入口读取代表图表 两种输入互斥 不保存历史代码副本 不在基准中写入资产 不以质量下降换取耗时下降

本节为迁移后的权威入口 下方历史内容原文保留 其中项目内源码路径和 Game.Scripts 注册名称不再作为调用依据 必须实际发现新工具名称

源码与全部 MCP 专用文档位于本仓库 项目只保留 `Content/Python/init_unreal.py` 加载入口 不复制源码 不使用链接兼容 仓库目录与游戏项目目录是两个不同边界

新会话先核对目标项目唯一宿主 调用 `list_toolsets` 在返回列表寻找唯一类名为 `BBBMcpRuntimeToolset` 或 `BBBMcpRuntimeToolset_0x` 加八位十六进制哈希的工具集 使用实际返回的完整名称 描述后依次调用 `get_mcp_usage_guide` 和 `inspect_mcp_dependencies` 不猜测命名空间

核对指南的 `project_root` 为当前目标项目 `document_path` 与 `dependency_document_path` 位于当前仓库 核对依赖报告的源码路径 注册状态与原生依赖 再描述实际目标领域 缺失原生依赖的相关写入不得继续

`get_mcp_usage_guide.performance_toolset` 与项目领域路由从实际工具类包名生成 官方工具路由保持原官方名称 同一宿主会话复用参数结构 注册更新后重新发现 不缓存资产状态

启动命令现在要求显式项目与引擎路径

```powershell
$projectFile = (Resolve-Path -LiteralPath (Read-Host '输入项目 .uproject 文件的完整路径')).Path
$engineRoot = (Resolve-Path -LiteralPath (Read-Host '输入 UE5.8 安装根目录')).Path
$publicPort = [int](Read-Host '输入为该宿主选择的本机 MCP 端口')
$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile GamingBackground
$hostInfo = $hostInfo | ConvertFrom-Json
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

性能档位与单宿主约束保持原设计 `BBBMcpBootstrap.register_mcp_toolsets` 注册或迁移加载位置 `BBBMcpBootstrap.reload_mcp_toolsets` 先注销原生工具类 再重载 Python 模块并通过官方注册表重新注册 保留实际宿主性能设置 更新后重新发现并回读

`run_editor_script` 仅允许当前项目 Scripts 或本仓库 Scripts 下的真实文件 解析真实路径防止父目录或链接越界 其它磁盘路径拒绝执行 本入口用于已经落地的工具与项目脚本 不用于生成临时脚本绕过缺失能力

原生扩展继续保留在项目 详细边界见 [项目依赖](ProjectDependencies.md) 本轮不重构游戏 C++ 不删除或改名原有公共工具 不因迁移自动启用原来可选的资产维护工具

推送目标和分支以接入项目的版本控制规则及实际远端配置为准 正常快进 不强推 不清空历史 游戏项目接入修改遵守所属项目规则

# 项目 UE MCP 唯一调用说明

本文件是 AI 识别本项目 Unreal MCP 的唯一入口说明。

## 唯一运行时入口

- Unreal Engine：UE5.8
- 服务插件：官方 `ModelContextProtocol`
- 工具注册：官方 `ToolsetRegistry`
- 客户端地址: 使用启动器返回的 `Endpoint`
- 启动脚本：`Scripts/MCP/Start-UE58OfficialMcpEditor.ps1`
- 启动参数: 由启动器依据明确的项目 引擎 端口和渲染配置生成

MCP 宿主必须使用 `-AutoDeclinePackageRecovery` 跳过包恢复模态窗口，避免隐藏编辑器已监听端口却无法处理请求。该参数不删除 `Saved/Autosaves` 中已有的自动保存资产。

同一项目只允许一个可写 UE MCP 宿主. 端口由启动配置指定 客户端使用实际返回的地址. 端口冲突先核对进程归属 不擅自连接其他宿主或创建第二实例.

## 唯一调用顺序

使用官方 MCP 客户端工具，固定按以下顺序：

1. 检查启动器返回的 `Endpoint` 是否可用并核对项目身份
2. 调用 `list_toolsets`
3. 调用 `describe_toolset` 获取目标工具集的精确工具名和参数结构
4. 调用 `call_tool` 执行具体工具
5. 解析工具返回的 `content[0].text`；项目工具的 `returnValue` 还需要再解析一层 JSON

不要根据文件名猜测工具名，不要直接调用旧 Python 脚本，不要把工具集名称省略。

## 项目工具集

### Control Rig 双向求解审计

`BBBControlRigAuthoringToolset.audit_control_rig_round_trip(asset_path, animation_path, mesh_path, sample_times, control_deltas_json, bone_names)`

在瞬态 Rig 实例中载入实际网格源姿势 执行 Backwards Solve 后应用控制器局部增量 再执行 Forwards Solve 返回全部骨骼局部误差及指定骨骼组件空间姿势 不修改或保存任何资产

`control_deltas_json` 使用控制器名称映射到 `position` 三元素数组及 `rotation` 四元数数组 空对象用于验证未调整时的姿势往返

工具未注册时通过现有 `run_editor_script` 加载 `Scripts/BBBControlRigAuthoringToolset.py` 加载后重新发现工具结构 不重启编辑器

### 单动作 FBX 覆盖导入

`BBBGenericEditorToolset.import_animation_fbx(source_file, asset_path, skeleton_path)`

将单动作 FBX 导入已有 AnimSequence 的原路径 只保存指定动画 不导入网格 材质或纹理
调用前必须备份目标并完成 Perforce 独占签出 工具拒绝骨骼不匹配 未签出或存在未保存修改的目标
导入后检查唯一返回对象 路径 骨骼与正时长 失败时不保存
多进程任务必须由用户明确允许 使用独立端口且仅修改不重叠资产 其它编辑器完成手头任务后再重新加载目标动画

| 用途 | 工具集名称 |
| --- | --- |
| 动画迁移 动画诊断和动画资产操作 | 实际发现的 `BBBAnimationMigrationToolset` 完整名称 |
| 外部移植的动画 Control Rig 重定向 关卡 编辑器和视口工具 | 实际发现的 `BBBExternalToolset` 完整名称 |
| 通用资产属性读取 | 实际发现的 `BBBGenericEditorToolset` 完整名称 |
| 项目级关卡操作 | 实际发现的 `BBBLevelEditingToolset` 完整名称 |

`BBBLevelEditingToolset.spawn_pie_mass_display(spawner_path, config_paths, center, radius)` 仅配置当前 PIE 世界的 `MassSpawner` 与其 `BBBMonsterSpawnGenerator`，按不重复的 Mass 实体配置各生成一只；`center` 是三个厘米坐标，`radius` 是零至二千厘米。调用前应通过 `invoke_pie_actor_function` 对该 PIE 生成器执行 `DoDespawning`，并读回表现 Actor 数量为零。调用后使用 `inspect_pie_actor_properties` 核对 PIE 世界的生成器配置和每种表现 Actor 数量，不以请求数量代替实际生成数量。此工具不修改或保存编辑器关卡。更新 `Scripts/BBBLevelEditingToolset.py` 后，可用已注册的 `run_editor_script` 执行该文件以仅注销、重载并注册此工具集，再重新发现准确工具名称及参数；不要重载其它并行会话正在修改的工具集。

`BBBLevelEditingToolset.set_pie_paused(paused)` 只切换唯一 PIE 世界的暂停状态，展示实体到位后可设为 `true` 留给用户检查。

`BBBAnimationMigrationToolset` 的动画数据访问迁移入口为：

```text
migrate_animation_data_accesses(blueprint_paths, getter_paths_json, duration_query, elapsed_path, removed_functions, nullable_object_getter, missing_value_defaults_json)
simplify_animation_data_accesses(blueprint_paths, node_class_path, removed_input_pins, removed_access_paths, direct_access_paths)
repair_raise_weapon_after_firing_transition(blueprint_path)
repair_main_anim_instance_accesses(blueprint_path)
```

`migrate_animation_data_accesses` 将函数调用、成员读取或旧 Property Access 路径统一迁移为指定的 Getter 链。映射键可以是函数名、成员名、完整旧路径，或 `函数名:输出引脚名`；映射值是点分路径。它保留时长查询的 Duration 连线与常量，改用经过时间比较，并移除明确列出的旧函数图。编译失败时报警且不保存。

单节点替换可使用 `32位大写节点GUID:输出引脚名`，优先于函数名映射，用于只迁移某一条旧链路而不影响同名节点。旧 Socket、Cast、表现 Actor 等已失去用途的中间节点，应使用官方 BlueprintTools 删除明确的节点，并再次严格编译。迁移前备份目标资产；失败时检查脏包，不得把部分迁移结果当作完成版本保存。

角色瞄准意图、瞄准目标和 AimIK Alpha 从 `UBBBAnimInstance` 自身 Getter 读取。武器瞄准来源、左手握持、开火及换弹使用 `GetWeaponAnimInstance` 两级 Getter；武器动画蓝图读取自身 Getter。`nullable_object_getter` 指定允许为空的根查询，工具用普通 Getter 调用、线程安全的对象非空比较和 `Select` 提供空对象默认值，防止 UE Property Access 跳过空引用赋值后残留旧缓存。角色的弱引用 Getter 已过滤失效对象；不用未声明线程安全的 `IsValid` 节点。未开火或无武器时，经过时间的默认值指定为 `1.0e+38`。

### Alpha 统一启停后的简化规则

AimIK 不再提供独立目标有效性输入。角色处理器把目标数值与方向有效性、武器实例的瞄准来源有效性合入角色动画事实中的 `AimIKAlpha`，再结合瞄准意图及动作锁定权重；无已绑定武器或输入失效时最终 Alpha 直接为零。角色动画实例提供 `IsAiming`、`GetAimIntentAlpha`、`GetAimIKAlpha`、`GetAimTargetComponentSpace`；武器动画实例不接收逐帧 `AimState`。武器瞄准来源在装备时绑定一次。不要把世界坐标零向量当作无目标。

`simplify_animation_data_accesses` 使用节点类路径和输入名称删除旧引脚，仅沿失去用途的上游纯节点清理旧调用链；`removed_access_paths` 用于检查并移除废弃路径，仍有消费者时失败且不保存。`direct_access_paths` 用于移除指定位置或变换路径外围的空对象默认值 Select，只处理明确匹配同一根 Getter 非空判断的节点。

目标位置从角色 Getter 直接读取，来源变换和左手握持位置从武器 Getter 直接读取。角色代码已经在没有已绑定武器时把最终 Alpha 归零；已有蓝图 Alpha 空武器 Select 仍可保留，不重复添加。状态机使用的开火、换弹等查询保留独立默认值处理，不受 IK Alpha 代替。

使用通用迁移工具创建新路径后，应按上述规则调用简化工具并检查最终 Alpha 保护，避免重新形成逐项位置保护的冗余结构。修改后严格编译相关主蓝图与继承层，保存前检查旧引脚和废弃路径已无残留。

旧 `rebuild_current_left_hand_ik_layer` 已删除，不得重新创建角色侧 Socket 查询函数。左手 Socket 名称、组件空间偏移和 `hand_r` 骨骼空间 IK 偏移由装备领域 `FBBBEquipFragment` 的 `LeftHandSocketName`、`LeftHandSocketOffset`、`LeftHandIKOffset` 配置，并在装备时绑定到武器动画实例；动画实例只发布转换后的角色 `hand_r` 骨骼空间事实，`hand_l` Two Bone IK 效果保留。

`repair_raise_weapon_after_firing_transition` 清除 Idle 状态机中已失效的开火标签转换绑定，直接创建武器经过时间的两级 Getter、时长比较及空对象默认值选择，不再创建旧角色查询函数。

`repair_main_anim_instance_accesses` 仅将下游接受 `UBBBAnimInstance` 基类的普通调用，以及后续成员已声明在该基类上的属性路径，替换为原生 `GetBBBMainAnimInstanceThreadSafe`。仍需 `BBBABP_0` 或 `BBBABP_UA` 专属字段的访问保持原路径，避免类型不兼容；这些路径要求角色主网格绑定对应的正确主动画蓝图。

`BBBExternalToolset` 的领域入口为：

```text
animation(action, params_json)
control_rig(action, params_json)
data_table(action, params_json)
editor(action, params_json)
game(action, params_json)
layer(action, params_json)
level(action, params_json)
level_sequence(action, params_json)
retarget(action, params_json)
util(action, params_json)
vision(action, params_json)
```

`params_json` 必须是 JSON 对象字符串；无参数动作传入 `{}`。GAS 不在本项目 MCP 工具集中。

## 注册关系

`Content/Python/init_unreal.py` 只负责把项目 Python Toolset 注册到官方 Toolset Registry：

```text
Content/Python/init_unreal.py
    -> Scripts/BBBAnimationMigrationToolset.py
    -> Scripts/BBBExternalToolset.py
    -> Scripts/BBBGenericEditorToolset.py
    -> Scripts/BBBLevelEditingToolset.py
    -> 官方 ModelContextProtocol
```

`MCPClientToolset` 是 UE 内的客户端工具集，不是第二个 MCP 服务端，不得当作服务地址或替代入口。

## 禁止识别为运行入口的历史内容

以下内容不是工具注册、不是 MCP 服务，也不能作为调用入口：

- 项目根目录历史 `mcp_*.log`、`mcp_*.json`、`mcp_*.err` 探测文件
- `Scripts/__pycache__` 中历史 `mcp_*.pyc` 缓存
- `Docs/Archive/` 中关于旧 socket、stdio 或 headless 服务的交接记录
- `Scripts/MCP/ThirdParty/GenOrca/` 中的源动作模块本身

GenOrca 动作只能通过 `BBBExternalToolset` 的白名单和官方 Toolset Registry 调用。项目不启动其第三方 MCP server，不安装其专用插件，不使用其 `MCPythonHelper`。

## 写入前规则

- 修改 `.uasset`、`.umap` 或其它 UE 资产前先在 Perforce 中独占签出
- 已被他人签出的资产不得覆盖
- AI 应先完成 `describe_toolset` 和参数确认，再执行写入工具
- 未经用户授权不得执行 `Get Latest`、批量 `Add`、`Submit` 或 `Revert`
- MCP 宿主默认使用隐藏 `NullRHI` 编辑器；需要用户查看界面时才使用有窗口编辑器

## 编辑器界面截图

通用工具 `BBBGenericEditorToolset.capture_editor_screenshot(widget_ref, file_name)` 复用官方 `SlateInspectorToolset.Screenshot` 原始分辨率截图 保存到当前工程 `Saved/Screenshots/MCP` 返回路径和像素尺寸 与 ThemeEnginePro 及亚克力功能无关

截图宿主须启用官方 `SlateInspectorToolset` 插件 可在启动参数中加入 `-EnablePlugins=SlateInspectorToolset` 官方插件经 Toolset Registry 自动注册 使用真实渲染 不得使用 `-NullRHI` 需要不干扰桌面时使用 `-RenderOffscreen` 并隐藏启动 遵循单宿主规则 不为截图擅自重启其他会话的编辑器

调用顺序为 `list_toolsets` → `describe_toolset` → 官方 Slate `Snapshot` 获取明确窗口引用 → 通用 `capture_editor_screenshot` 文件名仅接受 PNG 名称 不允许目录穿越或覆盖已有截图

截图直接读取 UE 的 Slate 渲染 不抓取桌面 不激活窗口 不发送鼠标键盘输入 空引用 无效 PNG 和缺少截图插件会明确报错

该实现已在 UE5.8 独立离屏宿主验证 PNG 保存及空引用 路径越界 重名保护 主工程脚本更新后在下次正常启动时加载 不要求重建或恢复亚克力试验工程

## 宿主退出检查

`BBBGenericEditorToolset.inspect_dirty_packages()` 只读返回未保存的内容包和关卡包. 停止宿主或编译 C++ 前先检查结果 有脏包时不得直接丢弃. 共享宿主先结束本任务活动并释放占用 全部任务和活动结束后调用 `shutdown_editor_host` 随后核实对应编辑器及网关进程已退出. 详细条件见 [共享宿主任务保护](BBBMcpTaskProtection.md).

## MCP 速度优先规范

AI 默认直接使用已连接的 `ue58_official` MCP 工具 不为每个动作启动 `mcp_call.py` 不启动额外代理服务

首次连接当前宿主时执行工具发现并核对参数 已确认的工具结构在同一会话内复用 宿主重启 工具重新注册 或收到 `notifications/tools/list_changed` 后重新发现 不缓存资产状态与编辑器查询结果

相关操作优先使用官方 `editor_toolset.toolsets.programmatic.ProgrammaticToolset` 合并往返 使用前调用 `get_execution_environment` 并阅读返回说明 核对每个被调用工具的输入与输出结构 不以任意 Python 脚本代替已注册工具 不并行修改同一资产

### 宿主性能档位

所有档位关闭后台 CPU 节流与失去前台时的空闲策略 档位只修改当前进程内存 不保存用户配置 不修改资产 不自动停止其他会话

| 档位 | 默认帧率上限 | 进程优先级 | 使用目的 |
| --- | --- | --- | --- |
| `Speed` | 120 | `Normal` | 默认速度优先 |
| `Balanced` | 60 | `Normal` | 降低持续资源消耗 |
| `Economy` | 30 | `BelowNormal` | 接受更高调度延迟换取资源节约 |

`Start-UE58OfficialMcpEditor.ps1` 使用 `-PerformanceProfile` 选择档位 使用 `-MaxFPS` 指定零至二百四十的帧率上限 零表示不限制 负一使用档位默认值 不限制帧率或低于三十时报警

```powershell
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile Speed
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile Balanced
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile Economy
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile Speed -MaxFPS 0
```

默认宿主使用隐藏 `-NullRHI -Unattended` 离屏渲染使用 `-EnableRendering` 与 `-RenderOffscreen -Unattended` 不再默认限为五帧 现有离屏低成本渲染参数保留

启动器通过互斥锁防止同时启动 发现不匹配的编辑器或端口时明确失败 不创建第二实例 就绪必须完成 MCP 协议握手并确认性能工具返回正确的进程与档位 不把端口监听当作工具就绪 失败时只关闭本次启动器自己创建的宿主

运行时工具集使用实际发现的 `BBBMcpRuntimeToolset` 完整名称

```text
inspect_mcp_performance()
configure_mcp_performance(profile="Speed", max_fps=-1)
```

`inspect_mcp_performance` 只读返回配置上限而非实测帧率 并报告后台节流风险 `configure_mcp_performance` 应用后回读验证 失败恢复调用前设置并报警 实际资源消耗取决于当前关卡 渲染与工具负载 不保证固定 CPU 或 GPU 百分比

交互式编辑器全部窗口隐藏时仍可能进入 UE 节流分支 仅提高 `t.MaxFPS` 不能消除该机制 MCP 默认使用上述专用隐藏宿主 有窗口宿主的使用必须协调现有会话

项目下次正常启动时由 `Content/Python/init_unreal.py` 注册性能工具并应用启动档位 未提供档位参数时使用 `Speed` 不为加载脚本擅自重启有未保存资产或正在工作的宿主

### 命令行辅助客户端

`mcp_call.py` 保留单次调用入口 新增 `batch` 接收请求数组 在同一 Python 进程与 MCP 会话内顺序执行 减少重复启动与握手 这不是服务端批处理 每项仍是独立 MCP 请求

先在仓库根目录完成启动配置并设置 `BBB_MCP_URL` 再执行下面的工具发现命令. 批量调用中的工具集名称使用本次实际发现结果.

```powershell
python -B .\Scripts\MCP\mcp_call.py call list_toolsets
```

程序调用使用 `with McpSession(URL) as session` 配合 `call_many` 复用连接 会话退出只释放本客户端的 MCP 会话与 HTTP 连接 不关闭编辑器

客户端只缓存工具发现信息 收到工具列表变更通知时清空缓存 调用方明确重新注册工具后也可调用 `invalidate_discovery` 资产查询始终重新请求

协议错误与工具错误均返回失败退出码 传输失败不自动重放任何工具 批量请求失败立即停止并报告已完成数量 已完成写入不会回滚 必须检查实际资产与编辑器状态后再决定下一步

## AI 新会话最小入口与后台游戏模式

本节在原有三档基础上增加 `GamingBackground` 默认仍为 `Speed` 现有注释不修改 旧参数注释中的三个档位示例不是完整白名单 可选项必须从运行时指南获取

### 新会话入口

先确认端口对应本项目唯一宿主 工具未连接时核对实际 Unreal Editor 进程与项目路径 不连接到其他项目后继续执行写入 不擅自关闭并行会话或启动第二实例

按以下顺序调用 原生 MCP 工具的参数为 JSON 对象

下面的 `<实际发现的性能工具集完整名称>` 必须替换为本次 `list_toolsets` 返回的唯一对应名称.

```text
list_toolsets({})
describe_toolset({"toolset_name":"<实际发现的性能工具集完整名称>"})
call_tool({"toolset_name":"<实际发现的性能工具集完整名称>","tool_name":"get_mcp_usage_guide","arguments":{}})
```

`get_mcp_usage_guide` 返回当前可选档位 精确的性能工具集名称 文档绝对路径 和按领域选择工具集的路由 先核对 `document_path` 属于当前仓库并确认项目身份 再描述实际目标工具集 不为一个属性查询加载所有动画和 Control Rig 工具描述

指南不是目标工具的完整参数结构 仍须通过官方 `describe_toolset` 核对目标 API 同一宿主会话复用已确认结构 宿主重启或工具重新注册后重新发现 未列出的工具集不能仅凭文件名猜测或擅自加载

### 显式性能切换

性能工具集使用实际发现的 `BBBMcpRuntimeToolset` 完整名称

进入后台游戏档

```json
{"toolset_name":"<实际发现的性能工具集完整名称>","tool_name":"configure_mcp_performance","arguments":{"profile":"GamingBackground","max_fps":-1}}
```

更低持续调度预算可显式使用 `max_fps` 为 10 不需要再增加一个常驻服务或独立控制系统

回到速度优先

```json
{"toolset_name":"<实际发现的性能工具集完整名称>","tool_name":"configure_mcp_performance","arguments":{"profile":"Speed","max_fps":-1}}
```

切换后必须回读

```json
{"toolset_name":"<实际发现的性能工具集完整名称>","tool_name":"inspect_mcp_performance","arguments":{}}
```

核对 `process_id` 与目标宿主一致 核对 `profile` `max_fps` `priority` 以及 `matches_configured_settings` 为 true 该字段为 false 时表示最近应用档位与实际设置不一致 可能被旧工具或其他会话改变 先协调再配置 不连续抢写

`available_profiles` 和指南中的 `profiles` 直接来自同一份实现定义 `configured_max_fps` 为最近请求的上限 `max_fps` 为实际读回上限 均不是实测帧率

| 档位 | 默认帧率上限 | 优先级 |
| --- | --- | --- |
| `Speed` | 120 | `Normal` |
| `Balanced` | 60 | `Normal` |
| `Economy` | 30 | `BelowNormal` |
| `GamingBackground` | 15 | `BelowNormal` |

后台游戏档继续关闭隐式后台节流 使用明确的帧率上限 不检测游戏进程 不自动切换档位或提速 不修改资产 不保存用户性能配置

启动专用隐藏宿主仍须先确认没有其他编辑器 与现有有窗口宿主不可并行

```powershell
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile GamingBackground
& .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort -PerformanceProfile GamingBackground -MaxFPS 10
```

不需要渲染的任务优先 NullRHI 需要渲染时选择 `-EnableRendering` 必须接受 GPU 与显存开销 不能在有脏资产或并行任务时为了省电擅自重启宿主

后台游戏档只降低持续调度预算 不限制每次工具操作的资源峰值 编译 批量导入 烘焙 截图与渲染前说明影响并协调当前任务 不保证前台游戏帧数 功耗上限或显存下降 交互式编辑器全部窗口隐藏时仍可能进入 UE 节流分支

### 工具选型与结果判断

| 需求 | 首选入口 | 边界 |
| --- | --- | --- |
| 对象属性与普通资产查询 | 官方 `ObjectTools` 与 `AssetTools` | 只请求所需属性 不先导出全部图表 |
| 蓝图基础节点编辑 | 官方 `BlueprintTools` | 参数结构以实际发现结果为准 |
| 蓝图排版与项目语言映射 | `BBBBlueprintGraphToolset` | 优先完整项目动作而非多次手动移动 |
| 动画迁移与项目防呆流程 | `BBBAnimationMigrationToolset` | 保留项目范围 骨架 签出 编译与保存保护 |
| Control Rig 基础操作 | 官方 `ControlRigTools` | 项目组合流程再选择 `BBBControlRigAuthoringToolset` |
| Sequencer 基础操作 | 官方 `SequencerTools` | 相关导出与控制器操作按领域路由选择 |
| 相关工具组合 | 官方 `ProgrammaticToolset` | 先读取执行环境和每个被调用工具结构 |
| 当前宿主性能设置 | `BBBMcpRuntimeToolset` | 不再通过分散的工具只修改帧率 |

解析结果时先读取 MCP 的文本内容 按输出结构解析第一层 JSON 字符串 `returnValue` 再解析第二层 JSON 不把字符串直接当作对象

协议 `error` 工具 `isError` 项目报告的 `success` 为 false 或根 `error` 非空均不能当作成功 例如 `run_editor_script` 的根 `error` 必须为空 控制台工具接受命令不等于命令实际成功 修改后必须使用目标领域的读回或编译检查

批量执行只是减少往返 不是事务 不会回滚已经完成的写入 失败时报告已完成操作并核对实际状态 不自动重放资产写入

### 现有工具无法解决时的处理顺序

先发现相关工具集并描述目标参数 再检查是否能通过已有工具或官方 ProgrammaticToolset 组合完成 不把参数错误 结果解析错误或失效注册误判为能力缺口

确认确有编辑器能力缺口后 优先拓展职责相符的旧工具 旧工具不适合承载时再新增最小通用工具 输入以明确的目标对象和参数表达需求 不将某个资产路径或一次性修复流程硬编码为新入口 不为解决当前需求建立额外框架

扩展必须遵守所属 Law 和已批准范围 明确新增或改动命名 在 `Scripts/` 中实现与注册 同步专用文档与必要的运行时指南 增加关键预检 日志和结果回读 重新发现工具后通过实际 MCP 调用验证 新会话能够直接复用才视为完成 不使用临时 py 脚本绕过缺失能力

权限缺失 文件锁 Law 冲突或外部服务故障必须先准确定位 按各自约束处理 不以扩展工具绕过权限 不盲目重试 新工具或重构超出批准计划时先报告影响范围并请求批准

工具模块更新应使用官方 `toolset_registry.reload_module` 管理已有注册 或先撤销原注册再重载并注册 不直接重载仍在注册表中的 Python 工具类 更新后须重新发现并实际调用 防止旧类失效而名称仍留在工具列表

`BBBExternalToolset.py` 已提供与项目已有工具相同的 `run_editor_script` 加载入口 在类重实例化后的 Slate 回调中替换注册 成功与失败均记录日志 回调只执行一次 文件执行响应不能替代重新发现与实际调用检查

### 本轮效率与体积审查结果

本轮静态检查覆盖八个项目 Toolset 脚本 运行时观测到七个注册工具集共一百六十一个工具 新增使用指南后性能工具集增加一个工具 未删除或改名任何公共入口

七个项目工具集完整描述合计约七万九千七百四十八字符 工具选择应先读取短指南并只描述所需领域 不以源码文件大小推断 MCP 延迟或编辑器内存消耗 不缓存资产状态来伪造加速

八个脚本的私有函数 AST 严格比对未发现完全相同的多份实现 未据此建立新的通用框架 或把业务流程合并成失去参数约束的巨型 action 接口

`BBBExternalToolset._dispatch` 改为直接检查领域白名单 再加载所需模块 不为单个调用重复导入 排序和扫描动作列表 白名单列举接口保留 九十四个允许动作的隔离测试验证返回语义一致 非法请求不导入模块

隔离 Python 分发逻辑中位耗时约从五点五微秒降到二点二微秒 该数字不代表整个 MCP 请求加速倍数

本轮在现有有窗口编辑器中对同一只读性能检查各测八次 每档附加约两秒资源短采样 观测如下

| 配置 | MCP 中位耗时 | 编辑器 CPU 占整机逻辑处理器预算 | 该进程 GPU 三维引擎计数器 |
| --- | --- | --- | --- |
| Speed 120 FPS | 20 点 5 毫秒 | 20 点 08 百分比 | 61 百分比 |
| GamingBackground 15 FPS | 66 毫秒 | 4 点 38 百分比 | 9 百分比 |
| GamingBackground 10 FPS | 100 毫秒 | 3 点 66 百分比 | 7 百分比 |

资源值是当前场景短采样 不是整机 GPU 总占用 不是前台游戏帧数 也不是固定功耗保证 工作集均约三点七 GiB 没有因为降低帧率明显下降 本轮未为对比重启为 NullRHI 或创建第二宿主

默认后台游戏档选择十五帧 需要更低持续占用时显式选择十帧 使用者必须接受更长请求等待 测试结束恢复 Speed 并验证实际设置一致

最终版本通过新建 HTTP MCP 会话验证 从工具发现 使用指南 到目标领域参数读取的完整入口 验证十一条路由属于已注册工具集 九十四个外部动作可发现且非法动作拒绝执行 这是全新 MCP 会话测试 不是另一个 AI 模型会话的行为测试

启动器通过模拟进程与 HTTP 响应验证 GamingBackground 十五帧 十帧覆盖 启用渲染 档位大小写归一化和拒绝第二实例 未为启动测试创建真实宿主 Python 与 PowerShell 语法检查通过 原有函数与类的文档注释未修改

候选整理入口为 `BBBControlRigAuthoringToolset.set_background_budget` 其职责与统一性能工具重叠 但仍有文档引用且所属文件有并行改动 本轮保留 新任务统一走性能工具

动画预览网格三个入口 `set_animation_sequence_preview_meshes` `set_animation_asset_preview_meshes` `set_animation_folder_preview_meshes` 可进一步评估内部逻辑收敛 但目录限制与处理范围不完全一致 不能直接视为等价接口删除

`repair_raise_weapon_after_firing_transition` 与 `repair_main_anim_instance_accesses` 仍有项目文档引用 没有证据证明已经失去用途 本轮不删除 一次性修复入口的清理需要明确消费者检查与用户确认
