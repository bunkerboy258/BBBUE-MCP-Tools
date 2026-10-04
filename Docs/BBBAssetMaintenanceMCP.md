# 精确资产维护 MCP

`fixup_redirector_references_batch(asset_paths, referencer_paths, dry_run=True)` 仅处理明确引用者, 单批最多 32 项. 预览只读注册表, 不加载目标. 执行前须备份并签出所选引用者; 工具逐包核对实际加载类型, 阻止本次加载新产生的项目蓝图错误、所选引用者自身已有的蓝图错误以及脏包, 不会因无关且既有的蓝图错误阻止本批保存. 使用原生软引用替换与逐包保存更新引用, 不修改蓝图图表, 不删除重定向器, 不执行签出/Submit/Get Latest/Revert. 保存后强制刷新引用者目录, remaining_selected 表示本批包是否仍残留旧路径; success 要求没有本批残留和脏包. 返回 saved 是已完成部分, 遇到失败不直接重试整批; 先核对磁盘, 日志和部分结果.

分批修复器同时接受明确的单主资产 `World` 地图包引用者，地图包也必须先备份并由当前用户独占签出；`__ExternalActors__` 引用者必须改用专用工具，其他多主资产包仍拒绝。

`make_current_editor_level_explicit(expected_package)` 核对 LevelEditorSubsystem 的活动层包名后调用官方 set_current_level_by_name，同步多世界编辑状态下的放置目标；不载入或保存关卡，PIE 中拒绝执行。UE5.8 的 EditorLevelUtils.make_level_current 接受 LevelStreaming，不能直接传入 Level。

`BBBAssetMaintenanceToolset` 已纳入 `BBBMcpBootstrap` 默认注册集合。正常启动或统一重载工具后，使用 `list_toolsets` 和 `describe_toolset` 读取实际工具名称与参数。源码更新不会自动替换当前宿主的已加载模块；未经允许不得为更新工具操作宿主。

`BBBAssetMaintenanceToolset.remove_unreferenced_loaded_redirectors(asset_paths)` 仅接受明确的 `/Game/` 包路径，逐项确认已加载对象的精确路径、ObjectRedirector 类型、无引用及可编辑状态，再删除重定向对象。不会通过重定向加载或删除目标资产。

`BBBAssetMaintenanceToolset.clean_unreferenced_redirectors_in_folder(folder_path, dry_run=True)` 先加载并盘点指定 `/Game/` 子目录中的对象，区分重定向器、仍有引用的重定向器、不可编辑项和普通资产。默认只审计；确认目录内全是无引用且可编辑的重定向器后，才可传 `dry_run=False` 批量删除。若存在引用、普通资产、加载失败或 Perforce 不可编辑项，会拒绝整批删除，不自动签出、不修引用、不提交。

`BBBAssetMaintenanceToolset.audit_asset_folder_move(source_folder, destination_folder)` 只读盘点目录迁移：递归列出源资产、检查按相对路径映射后的目标冲突，并统计源目录外的引用者及其内容根目录。它拒绝迁移 `__ExternalActors__` 和 `__ExternalObjects__`，不执行签出、移动、保存或删除。返回无冲突也不代表可以直接移动；仍须单独核对 Perforce 打开状态、脏包、代码或配置中的硬编码路径，以及关卡外部数据。

`BBBAssetMaintenanceToolset.move_assets_batch(moves_json, dry_run=True)` 将明确列出的资产和目录展开为精确资产映射，一次调用 UE5.8 原生 `AssetTools.rename_assets`。目录映射保留相对层级，可合并到已有目标目录；目标父目录可由原生保存过程创建。同名包、磁盘文件或资产与目录重名均拒绝覆盖。禁止重复源、父子源同时移动、链式或循环移动、仅大小写改名和目标落入正在移动的源目录。单批最多 1000 项请求，展开后最多 5000 个资产。

`moves_json` 是不带对象后缀的包路径映射数组，例如：

```json
[
    {"source": "/Game/Old/Animations", "destination": "/Game/_Project/Characters/Animations"},
    {"source": "/Game/Old/Materials/M_Floor", "destination": "/Game/_Project/Environment/Materials/M_Floor"}
]
```

默认预览不加载资产，不创建目录，不查询或更改 Perforce 文件状态。返回 `assets` 完整映射、源和目标磁盘路径、注册表引用者以及 `blockers`。`can_execute_after_checkout` 仅表示静态检查通过，不代表已经签出或实际移动必然成功。资产注册表扫描期间拒绝生成计划；普通资产的源包必须已经保存。重定向器、World、MapBuildDataRegistry、多资产包和 `__ExternalActors__` / `__ExternalObjects__` 数据需专项处理，本工具拒绝迁移。存在项目外或外部关卡数据引用者也会阻断。

执行使用相同请求并传 `dry_run=False`，重新预检后要求连接 Perforce，源资产和所有注册表引用者必须已由当前工作区签出或待添加且可编辑；仓库已有包必须最新、无冲突、无其他用户签出。目标还需通过仓库状态检查，防止磁盘未同步但仓库已有同名包。项目存在任何未保存脏包时拒绝执行；加载源资产后再次检查，以避免保存其它会话的修改。官方 `require_editable` 只检查关卡实例编辑权限，不能代替签出检查。

UE 原生 `rename_assets` 内部具有自动签出和保存逻辑，本工具通过执行前检查要求相关现有包已可编辑，工具自身不调用签出、Get Latest、Submit 或 Revert。若执行期间另一会话或原生扩展回调改变引用集合，仍需核对 Perforce 实际打开列表。引擎可能因代码默认对象引用要求确认或取消，不能把原生入口声明为绝对无弹窗。移动可能保存资产和引用者、产生重定向器及 Perforce 待提交变更，并非事务。

返回 `engine_success`、每个源对象的 `actual_object` / `renamed`、自动回读的 `verification`、最终 `success` 与 `partial`。引擎返回成功仍须核验通过才报告成功。失败可能已经移动部分资产，不自动回滚，不直接重试整批；先用预览清单核验，再为尚未完成的资产生成新请求。日志前缀为 `[BBBAssetMove]`。

`BBBAssetMaintenanceToolset.verify_asset_moves(moves_json)` 接受预览或执行报告的 `assets` 数组序列化结果，必须保留 `class_path`，不接受未展开的目录映射。只读检查目标注册类型、名称和磁盘文件，旧包是否消失或是否存在直接指向目标的重定向器，并报告旧引用者、未保存相关包和旧父目录中的剩余文件及注册资产。不加载对象、不修引用、不删除文件；该检查不证明内容逐字节一致，也不证明代码与配置中的路径字符串已更新。日志前缀为 `[BBBAssetMoveVerify]`。

迁移通过不代表旧目录可删除：正确重定向器和仍引用旧路径的包可以继续存在。`source_folders` 的 `empty_on_disk_and_registry` 只描述当前磁盘和注册表是否为空，不自动授权清理。引用修复和旧目录清理按明确范围另外执行，禁止直接在资源管理器搬运 `.uasset` 或删除仍被引用的重定向器。目录内非资产文件不会由本工具迁移，核验报告会显示它们。

蓝图包按 `AssetData.is_u_asset()` 只选择主资产，生成类、默认对象和类重定向记录由 UE 随主资产维护，不作为独立迁移项。预检和核验均采用该规则，避免把同包对象误判为重复包。

类型检查从 `TopLevelAssetPath.package_name` 和 `asset_name` 拼接稳定路径，不使用包含内存地址的结构调试文本；重定向器与关卡数据始终单独阻断，不作为普通资产移动。

`inspect_asset_packages(asset_paths)` 只读检查明确包的全部注册对象、已加载的主对象与蓝图生成类/默认对象、重定向目标标签、引用者、磁盘存在及脏包状态。不加载资产或跟随重定向，可用于排查原生批量迁移后的旧包残留。

原生迁移待添加资产时可能留下没有任何子对象的旧脏包和旧磁盘副本。通用 `reload_assets_from_disk` 仅在包确实为空且逐项列入 `discard_dirty_packages` 时允许从磁盘重载这种空包，不丢弃含对象的加载失败包。该能力不等于允许删除旧文件。

`consolidate_verified_asset_copies(moves_json, dry_run=True)` 只处理明确列出的旧副本和保留目标。每项须提供备份校验后的 `source_sha256` 和稳定 `class_path`；源文件有变化、类型不一致、存在脏包、关卡或重定向器时拒绝。执行要求源、目标和引用者已在 Perforce 可编辑，通过原生 `consolidate_assets` 归并引用并保存；失败报告部分进度，不重试、不回滚。该操作不是内容相同证明，调用者必须先确认目标确为应保留版本并备份。

`fixup_redirector_references(asset_paths, dry_run=True)` 修复明确重定向包的项目内硬/软引用，只保存这些引用者，保留重定向器。原生加载解析硬引用，`rename_referencing_soft_object_paths` 更新软路径，`save_packages` 支持明确的普通地图包。禁止外部 Actor/Object 包及未保存修改，执行前须备份并签出全部引用者，返回剩余旧引用，不宣称自动清理。

`fixup_external_actor_redirector_references(asset_paths, referencer_paths, dry_run=True)` 专门修复明确的 `/Game/__ExternalActors__/` 包对普通资产重定向器的引用。每批最多 64 个重定向包和 32 个外部 Actor 包；预检只读注册表和磁盘。执行前须备份引用者、Perforce 已连接且每个引用者已由当前用户独占签出或待添加、无脏包且不在 PIE。工具只加载清单中的外部 Actor 包，只改写它们对清单重定向器的引用并逐包保存，之后强制重扫这些包所在目录以核验旧引用，保留重定向器；不处理 `__ExternalObjects__`、地图包或清单外引用者，不自动签出、提交、回滚或删除。失败时报告已保存包，不得整批盲目重试；完成后冷启动复核旧引用和包内容。

`delete_asset_redirectors(asset_paths, dry_run=True)` 只删除明确且完全由重定向对象组成的无引用包。默认仅审计，执行要求已备份、Perforce 可编辑、无脏包；加载使用 `follow_redirectors=False` 并再次核对精确路径/类型及引用。原生批量删除后回读磁盘与注册表，不触碰目标资产，不删除含普通对象的包。

原生删除可能因内存中的临时蓝图类仍引用旧包而留下磁盘文件，即使注册表条目已移除，也不能认为清理成功。工具返回剩余文件、注册包和脏包；须冷启动重新预检，不得直接按旧报告删除磁盘文件。引擎自身的删除流程可能办理待添加包撤销及已签出包转删除，工具不主动执行 Perforce Revert/Submit/Get Latest。删除时加载目标还可能触发 Control Rig 的延迟自动编译，需再次检查脏包，不保存无关领域改动。

`refresh_asset_registry_folders(folder_paths)` 从明确的 `/Game/` 子目录强制同步扫描磁盘状态，仅更新注册表，不加载或改写资产。存在脏包时拒绝；可用于核实原生删除后磁盘文件与注册表是否一致，不能代替引用核验或授权删除。

`BBBAssetMaintenanceToolset.resave_assets(asset_paths)` 校验每个精确 `/Game/` 包路径已加载且可编辑后强制重存该资产，可用于剔除已废弃属性留下的序列化依赖。执行前须备份目标并完成 Perforce 独占签出；所有路径先通过校验才开始保存，保存失败会报告已成功重存列表，不宣称事务回滚。

调用前保存移动后资产和引用者、确认无并行 PIE、备份旧包并处理 Perforce 独占签出。删除失败会报告已删除列表，不宣称事务回滚。此工具不替代通用引用修复，存在引用时停止。

`move_assets_preserving_external_actor_references(moves_json, dry_run=True)` 用于普通资产存在明确外部 Actor 引用时的原生批量迁移，单批最多 64 个资产。它复用普通移动的映射、类型、目标冲突、脏包和 Perforce 独占签出检查，只允许磁盘存在的 `/Game/__ExternalActors__/` 引用者通过专用预检；外部 Object、项目外引用、关卡、关卡构建数据和重定向器仍拒绝。源与全部引用者必须先备份并签出。工具不会移动外部 Actor 文件，也不宣称引用已清理；移动后的已加载引用修改须明确保存，再用外部 Actor 引用修复工具和普通引用修复工具分批清零，核验后才删除旧重定向器。部分失败保留逐对象执行结果，不得盲重试整个批次。

`move_partitioned_world(source_package, destination_package, dry_run=True)` 迁移唯一分区关卡主资产及其外部 Actor/Object 包。预检输出明确的 `affected_packages` 和外部文件清单；须先备份全部包并独占签出。执行要求源关卡未加载、目标关卡和外部目录不存在内容、无脏包和 PIE。原生 `BBBAssetRepairEditorLibrary.MovePartitionedWorld` 复用 UE 的 `WorldPartitionRenameDuplicateBuilder`，按 Actor 引用簇加载和保存，保留源关卡重定向，不执行 Submit。返回真实修改文件和源目标外部包数量回读；数量不一致、源外部包残留、脏包或保存失败时禁止盲重试。每个关卡应在干净宿主中处理，结束后冷启动核对 Actor GUID、关卡引用和外部包。构建器生成的临时关卡 `.ini` 由原生接口在同次调用结束时清理；源已有该配置文件时拒绝执行。

外部 Actor 引用修复允许重定向目标为目标包的生成类或默认对象。预检要求目标包具有唯一真实主资产；实际执行在加载任何引用者之前，使用 `follow_redirectors=False` 精确加载每个目标并核对对象路径，拒绝缺失对象或仍为重定向器的目标。生成类与默认对象不会被再次追加 `_C` 后缀。

## 缺失动画骨架恢复

`inspect_external_actor_packages(package_paths)` 只读加载明确的外部 Actor 注册对象，读取实际 Actor GUID、所属对象路径和附着父级。每批最多 64 个包，脏包或 PIE 期间拒绝执行，不修改、重存或移动 Actor；用于核对旧版关卡升级和原生迁移后的实际连接，不能用文件名替代 Actor 身份验收。

`inspect_physics_asset_material_bindings(package_path)` 使用原生接口读取每个骨骼刚体的物理材质、实例覆盖材质和碰撞形状数量，并返回预览网格与脏包状态。该检查不保存物理资产，用于原生依赖恢复、引用迁移前后绑定核对；Python 未暴露的刚体数组也可核验。

`inspect_native_dependency_packages(asset_paths)` 只读遍历明确包的内容依赖闭包，核对原生 `/Script/` 包是否已加载，不加载或保存资产。普通资产迁移预检复用该检查；源资产或引用者的间接依赖缺少原生模块时拒绝执行，避免重存时丢失无法反序列化的属性或子对象。

repair_missing_animation_skeleton(asset_path, skeleton_path) 仅处理没有骨架的动画；原生核验所有动画骨骼轨道均存在于目标骨架，已有骨架或轨道不兼容时拒绝。调用前备份当前动画并独占签出，必须确认目标骨架属于同一资源包。返回兼容性、骨骼轨道数量和保存结果。

inspect_package_objects(package_path) 读取包文件摘要及实际对象，供未注册包和非主资产包核验；只加载，不保存，不删除。返回导出数量、导入数量、对象类型和资产标记。

## 仅元数据的空包清理

delete_metadata_only_package(package_path, dry_run=True) 只接受无注册资产、无引用、单一旧版 MetaData 导出的精确包。执行前必须备份并独占签出；原生入口重复检查文件摘要、对象类型与脏包状态，使用引擎空包清理并核验磁盘文件消失。不会将未知或无法加载的包当作空包删除。

重定向包删除验收同时检查 .uasset 和 .umap 两种物理文件；旧地图产生的 .umap 重定向文件也必须实际消失，不能仅按注册表结果判断成功。

启动器 Start-UE58OfficialMcpEditor.ps1 支持 Culture 参数，默认不设置；资产验收隐藏宿主可显式传入 Culture=en，避免引擎按英文比较文本的自测受中文本地化影响。隐藏 NullRHI 宿主同时使用 RenderOffscreen，使引擎采用空平台应用并跳过不需要的绘图板硬件初始化；不改变项目插件配置。宿主复用必须匹配渲染模式与显式指定的语言。

verify_asset_moves 对旧包读取全部注册对象，非主资产规范化后产生的旧重定向对象也须核对其目标。目标包仍要求唯一主资产且名称、类型、磁盘文件均正确，不以忽略非主记录代替验收。

原生移动蓝图或包含导演蓝图的序列时，旧包可能同时保留主对象、生成类和类默认对象的重定向器。`verify_asset_moves` 逐一核对它们的目标包及对象名称，并要求主目标存在；残留真实对象或指向其它包的重定向仍拒绝验收。

`inspect_external_actor_package_metadata(package_paths)` 只读核对最多 64 个精确外部 Actor 包的注册对象、类型及硬软包引用。此工具不加载 Actor，因此可以核验所属关卡缺失的历史外部包；无引用记录本身不代表允许删除，清理前仍须确认所属关卡缺失、检查 Perforce 状态并保留逐文件备份。

`inspect_external_actor_packages` 对 Niagara Actor 同步读取原生 `GetDestroyOnSystemFinish` 开关，供旧结束事件回调的实际行为核验使用；该读取不更改事件绑定、特效参数或资产。

外部 Actor 引用修复和保留外部引用的资产迁移，均在加载前核验所属 `.umap` 与注册表中的实际 World。所属关卡缺失或已变成旧重定向包时立即拒绝操作；加载后还必须确认注册对象全部为实际 Actor，防止把加载失败的历史副本报告为已保存。

`delete_ownerless_external_actor_packages(package_paths, backup_directory, dry_run=True)` 用于已核对的历史外部 Actor 副本。最多 2048 个精确包，所属真实关卡必须缺失且没有组外引用；工具不加载 Actor，核对 Perforce 后逐文件备份并校验 SHA256，再调用 UE 原生 `SourceControl.mark_files_for_delete`。该原生删除流程同时处理未提交添加的文件，不执行独立的批量回退或提交。原件永久保留在 Content 外，完成后须关闭并重启宿主刷新注册表。

`inspect_external_object_package_metadata` 和 `delete_ownerless_external_object_packages` 对历史外部 Object 提供对应的只读核验及备份后清理，采用与 Actor 历史包相同的所属关卡、组外引用、Perforce 与 SHA256 条件。两种类型的包使用各自严格限定的根目录入口，不通过普通资产移动处理。

`inspect_content_dependency_integrity(asset_paths)` 对最多 5000 个明确包只读核验项目硬包和软包依赖。返回物理目录缺失的 `/Game/` 包及对应引用者；同时认可 `.uasset` 与 `.umap`，不加载、不保存、不修改资产。该检查覆盖已经没有重定向包的旧失效路径，须与重定向清零、原生依赖和运行验收共同使用。

`remap_missing_soft_object_paths(referencer_paths, replacements_json, dry_run=True)` 对明确缺失包的软路径执行 UE 原生替换，保留对象的子路径与编辑文档信息。每批最多 64 个已备份引用者，每项映射必须给出顶层 source/destination 对象路径，目标须为唯一真实主资产或其蓝图生成类/默认对象。源文件仍存在、目标缺失、无实际引用、脏包、PIE、加载类型变化或蓝图错误均拒绝；按当前 Perforce 签出状态保存并报告部分结果。不会创建兼容重定向器，也不删除未知引用。
依赖完整性检查支持只读核验外部 Actor/Object 包，并分别返回缺失的硬包与软包依赖；不使用普通资产移动入口处理外部包。

`inspect_loaded_package_soft_paths` 只读列出已经加载包中的实际软对象路径。`create_missing_path_recovery_redirector` 为明确缺失源包和唯一真实目标建立临时原生重定向，禁止覆盖源包；只在修复硬引用时使用，保存引用者并验收后必须删除临时重定向。软路径修复拒绝加载具有缺失硬依赖的包，防止保存时丢失配置。

`normalize_material_auxiliary_data` 按引擎 `SortTextureStreamingData(true, true)` 的正式烘焙规则整理旧流送缓存，记录实际纹理绑定前后一致性；可明确选择清理物理文件缺失的可选编辑预览网格，不修改材质图和参数，缺失硬引用时拒绝加载后保存。

`refresh_blueprint_reflection_metadata` 对已备份且签出的蓝图或关卡蓝图执行原生 `RefreshAllNodes`，核对节点和连线数量，不编译或保存。`inspect_loaded_package_soft_paths` 同时读取物理包头软引用，区分反射读取与实际保存路径。

`remap_package_metadata_owner_paths` 处理 UE5.8 包内独立 `FMetaData.ObjectMetaDataMap` 的旧所属路径；重建映射表并保留全部元数据值，合并同一目标时拒绝不同值冲突。普通 UObject 软引用序列化不会遍历此包元数据表，因此迁移验收须同时检查元数据所属路径和物理包头软依赖。


## 弃用接口和构造缓存维护

- `modernize_deprecated_blueprint_nodes(asset_path)` 只替换三种明确弃用接口：组件 `SkeletalMesh` 属性读取、`GetSkeletalMesh` 查询以及 `AddInstanceWorldSpace`。前两者改用 `GetSkeletalMeshAsset`，后者改用 `AddInstance` 并保留世界坐标语义。原有连线、节点位置和注释保持。调用方先备份，再执行警告作为错误的编译并保存。
- `rebuild_loaded_actor_construction(actor_paths)` 仅操作当前已加载编辑器世界中的明确非分区角色。重建后核对角色 GUID、变换、样条控制点，并报告剩余零长度样条段。拒绝脏包、PIE、其它世界或外部角色包，不保存关卡。


`update_pose_assets_from_source(expected_reports_json, dry_run=True)` 使用引擎 `UPoseAsset::UpdatePoseFromAnimation` 正式更新已有姿势。要求检查报告未变化、姿势结构与曲线兼容、骨架相同，执行前必须备份并独占签出；更新后核对全部姿势名称、加法基准和当前源 GUID，再保存。源动画不修改。该工具用于不能通过严格姿势数据一致性证明的旧缓存，不放宽 GUID 单独修复的误差限制。


`delete_unreferenced_asset_packages(asset_paths, backup_directory, dry_run=True)` 用于已经决定隔离的明确无组外引用资产。要求已有 Content 外永久备份且逐文件 SHA-256 一致、Perforce 可编辑、无脏包或 PIE。执行直接调用资产原生删除，不使用按目录优先分派的通用删除工具，并以物理文件消失为成功条件。部分失败返回完整已完成结果并报警，不继续删除。


## 植被挂接缓存只读核验

`inspect_foliage_base_cache(world_package)` 只检查当前编辑器世界，拒绝 PIE；返回每个植被 Actor 的正向及反向缓存数量、重复基础组件、缓存变换及实例指纹。不加载、不改动、不保存，世界路径不匹配时返回失败。用于保存前后以及冷加载后的实例数量、位置和挂接关系核对。

`repair_foliage_base_cache(world_package, dry_run=True)` 只合并相同组件且缓存位置、旋转、缩放完全一致的编号，拒绝分区世界及外部 Actor。修改前拒绝 PIE、脏包并核对独占签出；重建实例基础组件索引及反向缓存，保持实例数据，不保存。调用方先永久备份，再对比修复前后及冷加载后实例数量和指纹；失败必须保留现场。
