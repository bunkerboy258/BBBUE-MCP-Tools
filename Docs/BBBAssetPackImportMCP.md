# 独立资源包导入

`BBBAssetMaintenanceToolset.import_asset_pack_archive` 接收 ZIP 原件 原始内容根 原始 `/Game` 根和目标 `/Game/_ThirdParty` 根。默认只预检。目标和临时原始挂载目录必须不存在。执行阶段提取 UE 包 使用 AssetTools 原生批量重命名和软路径迁移 保存后核对旧根引用 再删除迁移跳转。第三方包保留内部结构。原件不修改 不覆盖已有资产 不创建兼容跳转。

原生依赖为 `BBBAssetRepairEditorLibrary.delete_redirector_packages`。禁止在 PIE 或存在脏包时执行。部分失败保留现场以便诊断 禁止盲目重试整个导入。最终以 `success` 和 `old_root_removed` 为真为完成条件。

迁移主体已保存而清理阶段中断时 显式设置 `finalize_only=true`。该阶段不解压 不移动 不覆盖 先验证目标无旧根引用 源仅包含无引用跳转且全部指向目标目录 再加载精确跳转对象并通过引擎删除。先预检后执行 禁止把普通源资产当作导入残留删除。
