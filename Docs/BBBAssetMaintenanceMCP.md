# 精确资产维护 MCP

`make_current_editor_level_explicit(expected_package)` 核对 LevelEditorSubsystem 的活动层包名后调用官方 set_current_level_by_name，同步多世界编辑状态下的放置目标；不载入或保存关卡，PIE 中拒绝执行。UE5.8 的 EditorLevelUtils.make_level_current 接受 LevelStreaming，不能直接传入 Level。

通过已有 `BBBAnimationMigrationToolset.run_editor_script` 加载 `Scripts/BBBAssetMaintenanceToolset.py`，然后使用 `list_toolsets` 和 `describe_toolset` 发现注册工具。

`BBBAssetMaintenanceToolset.remove_unreferenced_loaded_redirectors(asset_paths)` 仅接受明确的 `/Game/` 包路径，逐项确认已加载对象的精确路径、ObjectRedirector 类型、无引用及可编辑状态，再删除重定向对象。不会通过重定向加载或删除目标资产。

`BBBAssetMaintenanceToolset.clean_unreferenced_redirectors_in_folder(folder_path, dry_run=True)` 先加载并盘点指定 `/Game/` 子目录中的对象，区分重定向器、仍有引用的重定向器、不可编辑项和普通资产。默认只审计；确认目录内全是无引用且可编辑的重定向器后，才可传 `dry_run=False` 批量删除。若存在引用、普通资产、加载失败或 Perforce 不可编辑项，会拒绝整批删除，不自动签出、不修引用、不提交。

`BBBAssetMaintenanceToolset.audit_asset_folder_move(source_folder, destination_folder)` 只读盘点目录迁移：递归列出源资产、检查按相对路径映射后的目标冲突，并统计源目录外的引用者及其内容根目录。它拒绝迁移 `__ExternalActors__` 和 `__ExternalObjects__`，不执行签出、移动、保存或删除。返回无冲突也不代表可以直接移动；仍须单独核对 Perforce 打开状态、脏包、代码或配置中的硬编码路径，以及关卡外部数据。

`BBBAssetMaintenanceToolset.move_assets_batch(moves_json, dry_run=True)` 批量移动明确列出的资产或目录。`moves_json` 是 `[ {"source":"/Game/旧路径/资产","destination":"/Game/新路径/资产"} ]` 格式的 JSON 数组；资产路径不带对象名后缀，目录路径移动整棵目录。目标父目录必须已存在，目标必须不存在；每项源资产都必须可加载且可编辑，禁止同时移动父目录和其子项，单批上限为 1000 项。默认只预检；确认报告后用相同参数传 `dry_run=False` 执行。执行按输入顺序逐项调用 UE Rename API，不是事务；中途失败会返回已完成项和失败项，必须按报告核对，不会自动回滚。UE 负责迁移资产引用，但旧路径重定向器不会自动清理；工具不自动签出、不执行 Get Latest、Submit 或 Revert。

`BBBAssetMaintenanceToolset.resave_assets(asset_paths)` 校验每个精确 `/Game/` 包路径已加载且可编辑后强制重存该资产，可用于剔除已废弃属性留下的序列化依赖。执行前须备份目标并完成 Perforce 独占签出；所有路径先通过校验才开始保存，保存失败会报告已成功重存列表，不宣称事务回滚。

调用前保存移动后资产和引用者、确认无并行 PIE、备份旧包并处理 Perforce 独占签出。删除失败会报告已删除列表，不宣称事务回滚。此工具不替代通用引用修复，存在引用时停止。
