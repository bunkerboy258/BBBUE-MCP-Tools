# 精确资产维护 MCP

单资产修复、材质辅助缓存、元数据归并、姿势更新和指定目录注册表刷新，按相关包检查待保存内容。明确引用者的软路径修复与分批重定向引用修复，按指定引用者及输入检查。其他独立资产保留自身编辑与保存归属。广泛资产移动、合并和范围待定清理采用完整基线核验。

`inspect_native_package_referencers(script_packages)` 只读查询明确 `/Script/模块名` 的全部直接资产引用者 最多 64 项. 使用完成扫描的资产注册表 同时检查硬引用 软引用及管理引用 不加载或修改资产. 用于移除原生模块前后核验资产依赖.

`delete_unreferenced_uncontrolled_assets(expected_files, dry_run=True)` 原生删除已排除版本控制的第三方无引用资产. 清单逐项指定 `package` 和检查阶段的 `sha256` 最多 32 项. 仅接受 `/Game/_ThirdParty/` 下真实可写文件 严格核对无引用 无脏包 无 PIE 及未受版本控制. 受控资产或他人签出拒绝执行. 不创建备份或重定向 不执行 P4 Add Submit 或 Revert. 返回物理文件清除结果 部分失败停止且不自动重试.

`fixup_redirector_references_batch(asset_paths, referencer_paths, dry_run=True)` 仅处理明确引用者, 单批最多 32 项. 预览只读注册表, 不加载目标. 执行前须备份并签出所选引用者; 工具逐包核对实际加载类型, 阻止本次加载新产生的项目蓝图错误、所选引用者自身已有的蓝图错误以及脏包, 不会因无关且既有的蓝图错误阻止本批保存. 使用原生软引用替换与逐包保存更新引用, 不修改蓝图图表, 不删除重定向器, 不执行签出/Submit/Get Latest/Revert. 保存后强制刷新引用者目录, remaining_selected 表示本批包是否仍残留旧路径; success 要求没有本批残留和脏包. 返回 saved 是已完成部分, 遇到失败不直接重试整批; 先核对磁盘, 日志和部分结果.

分批修复器同时接受明确的单主资产 `World` 地图包引用者，地图包也必须先备份并由当前用户独占签出；`__ExternalActors__` 引用者必须改用专用工具，其他多主资产包仍拒绝。

`make_current_editor_level_explicit(expected_package)` 核对 LevelEditorSubsystem 的活动层包名后调用官方 set_current_level_by_name，同步多世界编辑状态下的放置目标；不载入或保存关卡，PIE 中拒绝执行。UE5.8 的 EditorLevelUtils.make_level_current 接受 LevelStreaming，不能直接传入 Level。

Bootstrap 统一注册资产维护工具。通过 `find_tools` 搜索 `assets`，使用 `describe_tool` 获取选中工具的参数。宿主更新在空闲交接窗口进行。

`BBBAssetMaintenanceToolset.remove_unreferenced_loaded_redirectors(asset_paths)` 仅接受明确的 `/Game/` 包路径，逐项确认已加载对象的精确路径、ObjectRedirector 类型、无引用及可编辑状态，再删除重定向对象。不会通过重定向加载或删除目标资产。

`BBBAssetMaintenanceToolset.clean_unreferenced_redirectors_in_folder(folder_path, dry_run=True)` 先加载并盘点指定 `/Game/` 子目录中的对象，区分重定向器、仍有引用的重定向器、不可编辑项和普通资产。默认只审计；确认目录内全是无引用且可编辑的重定向器后，才可传 `dry_run=False` 批量删除。若存在引用、普通资产、加载失败或 Perforce 不可编辑项，会拒绝整批删除，不自动签出、不修引用、不提交。

`BBBAssetMaintenanceToolset.audit_asset_folder_move(source_folder, destination_folder)` 只读盘点目录迁移：递归列出源资产、检查按相对路径映射后的目标冲突，并统计源目录外的引用者及其内容根目录。它拒绝迁移 `__ExternalActors__` 和 `__ExternalObjects__`，不执行签出、移动、保存或删除。返回无冲突也不代表可以直接移动；仍须单独核对 Perforce 打开状态、脏包、代码或配置中的硬编码路径，以及关卡外部数据。

`BBBAssetMaintenanceToolset.move_assets_batch(moves, dry_run=True)` 将明确列出的资产和目录展开为精确资产映射，一次调用 UE5.8 原生 `AssetTools.rename_assets`。目录映射保留相对层级，可合并到已有目标目录；目标父目录可由原生保存过程创建。同名包、磁盘文件或资产与目录重名均拒绝覆盖。禁止重复源、父子源同时移动、链式或循环移动、仅大小写改名和目标落入正在移动的源目录。单批最多 1000 项请求，展开后最多 5000 个资产。

`moves` 是不带对象后缀的包路径映射数组，例如：

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

移动报告提供 `timings_ms` 与 `query_counts`。预览仅包含 `preflight` 耗时；执行另包含 `write_preflight`、`source_load`、`native_rename`、`verification`，单位为毫秒，使用单调墙钟计时。`native_rename` 包含 UE 原生调用内部的引用维护、源代码控制处理及保存，不单独代表重命名对象耗时。各阶段在日志中以 `[BBBAssetMoveTiming]` 标记开始和完成；阶段抛错也记录耗时，预检或加载异常仍遵循原有错误返回机制，不保证提供完整 JSON 报告。日志耗时不包含开始和完成日志输出自身的耗时，阶段之和不等于整个 MCP 请求端到端耗时。

`query_counts` 仅统计移动静态预检：`package_assets`、`folder_assets`、`directory_exists`、`referencers` 表示实际查询次数，相应的 `_cache_hits` 表示本请求复用次数，未发生的类别不出现；`dependencies` 表示依赖闭包实际查询次数。共享包和父路径只在当前预检内复用，依赖闭包仍完整遍历；下一请求重新读取注册表，写前状态检查和写后核验不复用预检缓存。该统计不包含 UE 内部查询、磁盘检查或整个宿主的调用次数。

AI 应先读取上述阶段统计再判断瓶颈，不将查询次数减少等同于实际移动提速。本工具仍按明确输入执行一次原生批量移动，不自动拆批、不增加强制垃圾回收、不省略引用修复或包保存，也不修改资源包导入的追加修复流程。大规模迁移的实际耗时比较必须使用经用户指定的代表性资产与相同最终核验标准，不能为了测试擅自移动或自动保存项目资产。存在部分失败时保留完成结果，先核验再生成剩余请求。

`BBBAssetMaintenanceToolset.verify_asset_moves(moves)` 接受预览或执行报告的 `assets` 数组序列化结果，必须保留 `class_path`，不接受未展开的目录映射。只读检查目标注册类型、名称和磁盘文件，旧包是否消失或是否存在直接指向目标的重定向器，并报告旧引用者、未保存相关包和旧父目录中的剩余文件及注册资产。不加载对象、不修引用、不删除文件；该检查不证明内容逐字节一致，也不证明代码与配置中的路径字符串已更新。日志前缀为 `[BBBAssetMoveVerify]`。

迁移通过不代表旧目录可删除：正确重定向器和仍引用旧路径的包可以继续存在。`source_folders` 的 `empty_on_disk_and_registry` 只描述当前磁盘和注册表是否为空，不自动授权清理。引用修复和旧目录清理按明确范围另外执行，禁止直接在资源管理器搬运 `.uasset` 或删除仍被引用的重定向器。目录内非资产文件不会由本工具迁移，核验报告会显示它们。

蓝图包按 `AssetData.is_u_asset()` 只选择主资产，生成类、默认对象和类重定向记录由 UE 随主资产维护，不作为独立迁移项。预检和核验均采用该规则，避免把同包对象误判为重复包。

类型检查从 `TopLevelAssetPath.package_name` 和 `asset_name` 拼接稳定路径，不使用包含内存地址的结构调试文本；重定向器与关卡数据始终单独阻断，不作为普通资产移动。

`inspect_asset_packages(asset_paths)` 只读检查明确包的全部注册对象、已加载的主对象与蓝图生成类/默认对象、重定向目标标签、引用者、磁盘存在及脏包状态。不加载资产或跟随重定向，可用于排查原生批量迁移后的旧包残留。

原生迁移待添加资产时可能留下没有任何子对象的旧脏包和旧磁盘副本。通用 `reload_assets_from_disk` 仅在包确实为空且逐项列入 `discard_dirty_packages` 时允许从磁盘重载这种空包，不丢弃含对象的加载失败包。该能力不等于允许删除旧文件。

`consolidate_verified_asset_copies(moves, dry_run=True)` 只处理明确列出的旧副本和保留目标。每项须提供备份校验后的 `source_sha256` 和稳定 `class_path`；源文件有变化、类型不一致、存在脏包、关卡或重定向器时拒绝。执行要求源、目标和引用者已在 Perforce 可编辑，通过原生 `consolidate_assets` 归并引用并保存；失败报告部分进度，不重试、不回滚。该操作不是内容相同证明，调用者必须先确认目标确为应保留版本并备份。

`fixup_redirector_references(asset_paths, dry_run=True)` 修复明确重定向包的项目内硬/软引用，只保存这些引用者，保留重定向器。原生加载解析硬引用，`rename_referencing_soft_object_paths` 更新软路径，`save_packages` 支持明确的普通地图包。禁止外部 Actor/Object 包及未保存修改，执行前须备份并签出全部引用者，返回剩余旧引用，不宣称自动清理。

`fixup_external_actor_redirector_references(asset_paths, referencer_paths, dry_run=True)` 专门修复明确的 `/Game/__ExternalActors__/` 包对普通资产重定向器的引用。每批最多 64 个重定向包和 32 个外部 Actor 包；预检只读注册表和磁盘。执行前须备份引用者、Perforce 已连接且每个引用者已由当前用户独占签出或待添加、无脏包且不在 PIE。工具只加载清单中的外部 Actor 包，只改写它们对清单重定向器的引用并逐包保存，之后强制重扫这些包所在目录以核验旧引用，保留重定向器；不处理 `__ExternalObjects__`、地图包或清单外引用者，不自动签出、提交、回滚或删除。失败时报告已保存包，不得整批盲目重试；完成后冷启动复核旧引用和包内容。

`delete_asset_redirectors(asset_paths, dry_run=True)` 只删除明确且完全由重定向对象组成的无引用包。默认仅审计，执行要求已备份、Perforce 可编辑、无脏包；加载使用 `follow_redirectors=False` 并再次核对精确路径/类型及引用。原生批量删除后回读磁盘与注册表，不触碰目标资产，不删除含普通对象的包。

原生删除可能因内存中的临时蓝图类仍引用旧包而留下磁盘文件，即使注册表条目已移除，也不能认为清理成功。工具返回剩余文件、注册包和脏包；须冷启动重新预检，不得直接按旧报告删除磁盘文件。引擎自身的删除流程可能办理待添加包撤销及已签出包转删除，工具不主动执行 Perforce Revert/Submit/Get Latest。删除时加载目标还可能触发 Control Rig 的延迟自动编译，需再次检查脏包，不保存无关领域改动。

`refresh_asset_registry_folders(folder_paths)` 从明确的 `/Game/` 子目录强制同步扫描磁盘状态，仅更新注册表，不加载或改写资产。存在脏包时拒绝；可用于核实原生删除后磁盘文件与注册表是否一致，不能代替引用核验或授权删除。

`BBBAssetMaintenanceToolset.resave_assets(asset_paths)` 校验每个精确 `/Game/` 包路径已加载且可编辑后强制重存该资产，可用于剔除已废弃属性留下的序列化依赖。执行前须备份目标并完成 Perforce 独占签出；所有路径先通过校验才开始保存，保存失败会报告已成功重存列表，不宣称事务回滚。

调用前保存移动后资产和引用者、确认无并行 PIE、备份旧包并处理 Perforce 独占签出。删除失败会报告已删除列表，不宣称事务回滚。此工具不替代通用引用修复，存在引用时停止。

`move_assets_preserving_external_actor_references(moves, dry_run=True)` 用于普通资产存在明确外部 Actor 引用时的原生批量迁移，单批最多 64 个资产。它复用普通移动的映射、类型、目标冲突、脏包和 Perforce 独占签出检查，只允许磁盘存在的 `/Game/__ExternalActors__/` 引用者通过专用预检；外部 Object、项目外引用、关卡、关卡构建数据和重定向器仍拒绝。源与全部引用者必须先备份并签出。工具不会移动外部 Actor 文件，也不宣称引用已清理；移动后的已加载引用修改须明确保存，再用外部 Actor 引用修复工具和普通引用修复工具分批清零，核验后才删除旧重定向器。部分失败保留逐对象执行结果，不得盲重试整个批次。

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

`remap_missing_soft_object_paths(referencer_paths, replacements, dry_run=True)` 对明确缺失包的软路径执行 UE 原生替换，保留对象的子路径与编辑文档信息。每批最多 64 个已备份引用者，每项映射必须给出顶层 source/destination 对象路径，目标须为唯一真实主资产或其蓝图生成类/默认对象。源文件仍存在、目标缺失、无实际引用、脏包、PIE、加载类型变化或蓝图错误均拒绝；按当前 Perforce 签出状态保存并报告部分结果。不会创建兼容重定向器，也不删除未知引用。
依赖完整性检查支持只读核验外部 Actor/Object 包，并分别返回缺失的硬包与软包依赖；不使用普通资产移动入口处理外部包。

`inspect_loaded_package_soft_paths` 只读列出已经加载包中的实际软对象路径。`create_missing_path_recovery_redirector` 为明确缺失源包和唯一真实目标建立临时原生重定向，禁止覆盖源包；只在修复硬引用时使用，保存引用者并验收后必须删除临时重定向。软路径修复拒绝加载具有缺失硬依赖的包，防止保存时丢失配置。

`normalize_material_auxiliary_data` 按引擎 `SortTextureStreamingData(true, true)` 的正式烘焙规则整理旧流送缓存，记录实际纹理绑定前后一致性；可明确选择清理物理文件缺失的可选编辑预览网格，不修改材质图和参数，缺失硬引用时拒绝加载后保存。

`refresh_blueprint_reflection_metadata` 对已备份且签出的蓝图或关卡蓝图执行原生 `RefreshAllNodes`，核对节点和连线数量，不编译或保存。`inspect_loaded_package_soft_paths` 同时读取物理包头软引用，区分反射读取与实际保存路径。

`remap_package_metadata_owner_paths` 处理 UE5.8 包内独立 `FMetaData.ObjectMetaDataMap` 的旧所属路径；重建映射表并保留全部元数据值，合并同一目标时拒绝不同值冲突。普通 UObject 软引用序列化不会遍历此包元数据表，因此迁移验收须同时检查元数据所属路径和物理包头软依赖。


## 弃用接口和构造缓存维护

- `modernize_deprecated_blueprint_nodes(asset_path)` 只替换三种明确弃用接口：组件 `SkeletalMesh` 属性读取、`GetSkeletalMesh` 查询以及 `AddInstanceWorldSpace`。前两者改用 `GetSkeletalMeshAsset`，后者改用 `AddInstance` 并保留世界坐标语义。原有连线、节点位置和注释保持。调用方先备份，再执行警告作为错误的编译并保存。
- `rebuild_loaded_actor_construction(actor_paths)` 仅操作当前已加载编辑器世界中的明确非分区角色。重建后核对角色 GUID、变换、样条控制点，并报告剩余零长度样条段。拒绝脏包、PIE、其它世界或外部角色包，不保存关卡。


`update_pose_assets_from_source(expected_reports, dry_run=True)` 使用引擎 `UPoseAsset::UpdatePoseFromAnimation` 正式更新已有姿势。要求检查报告未变化、姿势结构与曲线兼容、骨架相同，执行前必须备份并独占签出；更新后核对全部姿势名称、加法基准和当前源 GUID，再保存。源动画不修改。该工具用于不能通过严格姿势数据一致性证明的旧缓存，不放宽 GUID 单独修复的误差限制。


`delete_unreferenced_asset_packages(asset_paths, backup_directory, dry_run=True)` 用于已经决定隔离的明确无组外引用资产。要求已有 Content 外永久备份且逐文件 SHA-256 一致、Perforce 可编辑、无脏包或 PIE。执行直接调用资产原生删除，不使用按目录优先分派的通用删除工具，并以物理文件消失为成功条件。部分失败返回完整已完成结果并报警，不继续删除。


## 植被挂接缓存只读核验

`inspect_foliage_base_cache(world_package)` 只检查当前编辑器世界，拒绝 PIE；返回每个植被 Actor 的正向及反向缓存数量、重复基础组件、缓存变换及实例指纹。不加载、不改动、不保存，世界路径不匹配时返回失败。用于保存前后以及冷加载后的实例数量、位置和挂接关系核对。

`repair_foliage_base_cache(world_package, dry_run=True)` 只合并相同组件且缓存位置、旋转、缩放完全一致的编号，拒绝分区世界及外部 Actor。修改前拒绝 PIE、脏包并核对独占签出；重建实例基础组件索引及反向缓存，保持实例数据，不保存。调用方先永久备份，再对比修复前后及冷加载后实例数量和指纹；失败必须保留现场。


## 原生完整数据验证的独立进程批次

`BBBDataValidation` 保留官方项目资产范围及验证器，可通过 `-BBBValidationBatchSize=512 -BBBValidationBatchIndex=0` 选择按对象路径排序的稳定批次。每批独立启动命令let，使用相同大小与完整清单哈希；只有全部批次成功、覆盖数量等于清单总数、警告和错误为零，才允许完整验收。`-BBBValidationManifest=绝对路径` 可将对象路径及类型写入 Content 外的永久验收清单。非法参数、越界批次、清单写入失败均报警且验收失败；清单漂移必须补验，不允许丢弃失败批次或修改官方验证规则掩盖问题。

## 普通资产移动的显式保存边界

`assets.move_assets_batch` 和共用执行器的普通资产移动在重命名之前完整加载精确引用者包，保留原始包对象；重命名之后直接对实际目标包、引用者和原包调用原生 `EditorLoadingAndSavingUtils.save_packages`，随后刷新受影响目录，最后执行原有磁盘及注册表核验。保存不再依赖网关按旧资产路径加载空的原包。

执行报告新增 `persistence` 与对应阶段耗时，包含请求保存包、成功保存清单和未保存包。原生保存失败时不将整批标为成功，也不自动再次重命名；即使只移动了一部分，仍保留逐对象状态并核验已发生的更改。保留旧重定向器的情况仍使用原有精确目标检查，不把重定向器当作正式整理已结束。

2026-10-19 离线回归：35 项资产路径、预检、部分执行及持久化测试通过，包含新目标与引用者保存次序、重复包去重、保存失败不重试、剩余脏包以及范围外包拒绝。实际两项角色动作资产的原生移动验收仍待统一重载后执行；离线模拟不代表 UE 已完成磁盘迁移。

补充一次完整执行次序回归：真实执行辅助函数确认引用者加载→原生改名→保存→目录刷新→核验，每步仅调用一次；资产迁移专项合计36项通过。

2026-10-19 原生验证发现：UE `SavePackages` 对无对象旧包返回成功仍可能保留旧文件和脏标记，因此不能将该返回值当作空原包已经持久化。现执行器先只保存真实目标、引用者和非空原包；对本次确已改名、完全没有任何子对象、原文件摘要未变、目标已保存且无组外引用的原包，限定这些包调用原生 `reload_packages(..., ASSUME_POSITIVE)`。重载后再次检查旧磁盘对象的精确路径、真实类型、摘要、脏包与引用，原生整体删除这些旧对象；不清除未知对象，不丢弃其它会话的修改，不直接操作包文件。

公共只读核验入口保留原参数、报告与行为，内部执行复用同一未装饰核验函数，防止工具装饰器把结构化失败报告转换成错误文本。新增摘要不匹配、组外引用、旧类型变化和目标保存失败的保护回归，专项共40项通过。

真实 Rifle03 两条 QuickMelee/UseReturn：首次重命名及目标保存成功，空旧包问题如实记录为失败；仅原空包原生重载、SHA绑定原生删除后，最终独立核验两条成功，旧文件、旧引用及相关脏包均为零，没有再次重命名。通用执行器新增自动收口分支仍须统一重载后用下一批真实资产验证，不把这次分步恢复冒充单批自动成功。

2026-10-19 第二次原生小批发现依赖注册表在保存后仍保留旧引用缓存，已把既有保存目录强制扫描前移到空原包无组外引用检查之前，没有忽略或放宽真实引用保护。新增缓存时序回归，专项合计41项通过。Pistol两AS的新路径及蒙太奇实际回读正确；分步限定重载、刷新、严格摘要原生删除后，独立最终核验旧文件、旧引用、相关脏包均为零。该分步恢复没有重复执行改名，自动第三版仍等待下一次加载后的真实小批验证。

### 删除目标的动画控制器根引用边界

普通资产删除与重定向器删除共用项目原生 `ReleaseTargetAnimationControllerRoots` 实现。在所有删除对象通过验证并收集目标包之后 只解除瞬态包内已根化的 `IAnimationDataController` 且其实际数据模型必须属于本批明确目标包。其它包的动画控制器以及非控制器根对象保持原状。随后仍走 `ForceDeleteObjects` 与 `CleanupAfterSuccessfulDelete` 原生流程 不绕过上层摘要或组外引用检查 不直接删除包文件。

原生自动化 `BBB.Editor.AssetRepair.ControllerRootScope` 使用两个独立临时包的真实动画控制器 验证只解除目标控制器 其它包及普通根对象不变 并检查重复调用和空范围没有额外修改。代码已加入 仍需统一编译加载后执行该测试及实际迁移回归。Python 执行器另在原生清理前释放已无用途的精确包包装引用 资产迁移离线专项42项通过 不把离线结果当成实际文件已删除。

2026-10-19 原生构建15.14秒成功且没有新增编译警告 新宿主35856实际执行 `BBB.Editor.AssetRepair.ControllerRootScope` 为 Success 目标控制器解除数1且其它包与普通根对象保持。Rifle03剩余9个旧动画及制作包按原摘要原生删除均通过 最终18条独立移动核验的旧文件 旧引用 重定向器及脏包均为零 6个蒙太奇真实片段和DA实际动画类也指向保存的新路径。此处仍明确为既有迁移的收口 不冒称新执行器已通过一批从重命名到清理的完整自动迁移。

随后 Sniper02 两AS的完整自动入口仍如实返回失败 新目标及引用者已保存但同宿主存在空原包及原文件。原生控制器隔离测试通过不代表该包持有问题已全部解决。当前按明确交接采用集中收口 每型号保存新目标及引用者后 仅对实际只剩UPackage且无对象的旧脏包精确原生重载 静态实际资产adopt核验通过后释放该型号故障占用 已存目标不重复改名。原文件保留最初SHA到唯一临时待清单 在最终新宿主冷加载后按真实引用顺序严格原生删除并独立核验 旧残留未清零前不得把迁移标为完成 不为该现象增加兼容跳转或绕过引用保护。

同日 SMG03 唯一原始弹匣预览的单项实际调用完整通过自动链 原生重命名后保存真实目标及原有HandEdit序列引用者 限定空原包重载及原生删除成功 独立核验旧文件 旧引用 重定向器及脏包均为零。该单项证明入口具备成功路径 不覆盖上述特定既有资产仍需最终冷清理的已知边界。目标为本枪 `Animation/Sequence/ANI_BBB_SMG_03_ReloadMagazinePreview` 没有新增第二份预览或兼容跳转。

### 明确删除组的单次原生调用

2026-10-19 前台宿主22444对61个迁移旧包完成严格原摘要和组外硬软引用检查后原生删除，独立61条映射核验全部通过；另8个已获制作者交接的旧手工LS严格删除通过。公共Other首16项通过完整自动移动、保存、原包清理及核验链，耗时87秒。上述实际结果对应批量化修改之前的实现。

原实现对每个对象分别调用原生删除，61包耗时231秒、8个LS耗时36秒。现明确删除入口和移动后的空原包清理分别收集完整已校验对象组，仅调用一次既有 `delete_asset_packages(objects)`，随后逐文件检查不存在；移动清理仍逐包核验原路径和真实类型，注册表逐包确认无旧对象。严格SHA、明确范围、组外硬软引用和脏包保护保持，正式删除在全部对象加载后再次检查组外引用及脏包，缺对象或路径变化则整组拒绝执行。原生部分失败不重试、不将残留文件记为成功，不直接操作uasset文件。

离线回归43项资产移动测试、5项整组删除保护测试及7项既有动作/删除测试通过，共55项；覆盖相互引用组单次原生调用、末项SHA错误阻止全部删除、加载引入外引、缺对象、原生失败和文件残留。批量化后的真实原生验收等待统一重载，再以独立实际小批验证；不把此前16项成功冒充新实现已验收。

统一重载后的前台宿主37312已实际验证：LMG01唯一Preview原生完整移动成功且旧包清零；另16项公共Other资产原生批量改名、目标保存、整组空原包删除及逐条独立核验完整通过，脏包为零。新16项耗时22秒，旧16项87秒；这是同样数量不同实际资产的耗时观测，不宣称所有资产固定提速倍率。当时剩余1624项公共归整继续按明确小批执行，每批重新绑定当前SHA并保留真实结果，不因小批成功跳过后续类型、引用及保存核验。

随后Other1656项全部分批完成原生移动并通过独立全量1656映射核验，旧文件、旧引用、重定向器及脏包为零；原LMG旧底稿清理后，单独延后的公共Shotgun Reload也完整通过自动链。11个另获制作交接的旧LS在全组SHA及零引用检查后通过整组原生删除，未删除当前Grip LS、Preview或原始AS输入。

包含循环蓝图依赖的Used242项及两个R1制作输入合并批次仍如实报告部分失败：244对象均实际改名，新目标与引用者429个实际正式包保存、文件存在且无包脏标记，但旧源产生LinkerPlaceholderClass和空包脏标记。源资产不再次改名，不把旧路径加载和网关保存重试视为正式整理完成；仅对230个已核实只有UPackage且无任何对象的旧包精确原生重载，剩余3个明确旧源脏包交统一冷重启处理。新Base蓝图当时状态BS_DIRTY但包未脏，须新宿主编译及核验。该批尚未冷清终验前不声称完整自动成功，不为占位类扩大清除范围或绕过引用保护。

同轮最终在新前台宿主1156重新读取全部244旧源，当前SHA与关闭前边界一致、真实类型存在、组外硬软及内存引用为零。按真实引用顺序以64/64/64/52四组严格原生删除全部成功；独立244映射核验通过，旧文件、重定向器和残留引用为零。新Base重新编译保存后，实际读取Main、Base、ALI及四动画层状态全部BS_UP_TO_DATE，dirty为空。此为前述已实际移动批次的最终冷清理，不将其改写为同宿主自动链一次成功。

另66个具有完整真实骨轨的公共可编辑LS从私有work同名原生迁入公共Used/hold，完整自动移动和独立66映射核验均通过，dirty为空；其Control Rig继续引用现有真实Items制作源，没有复制或建立兼容跳转。该用途判定与目录验收不等同于底稿和输出AS的全帧姿势等价证明。项目永久目录说明保存最终1901次原清单移动、1真实去重及额外66制作输入的精确计数。
