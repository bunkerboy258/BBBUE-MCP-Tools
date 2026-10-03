# 精确资产维护 MCP

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

`BBBAssetMaintenanceToolset.resave_assets(asset_paths)` 校验每个精确 `/Game/` 包路径已加载且可编辑后强制重存该资产，可用于剔除已废弃属性留下的序列化依赖。执行前须备份目标并完成 Perforce 独占签出；所有路径先通过校验才开始保存，保存失败会报告已成功重存列表，不宣称事务回滚。

调用前保存移动后资产和引用者、确认无并行 PIE、备份旧包并处理 Perforce 独占签出。删除失败会报告已删除列表，不宣称事务回滚。此工具不替代通用引用修复，存在引用时停止。
