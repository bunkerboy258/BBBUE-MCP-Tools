import json
import pathlib
import re
import zipfile

import unreal


def finalize_import(source_package_root, destination_root, dry_run):
    """
    /**
     * 核验目标引用并清理已经迁移的无引用跳转 不重复迁移主资产
     * @param source_package_root 已迁移的原始挂载根
     * @param destination_root 已完成迁移的第三方根
     * @param dry_run 仅检查源跳转与目标引用
     * @return 目标数量 跳转数量和清理结果
     */
    """
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    registry.scan_paths_synchronous([source_package_root, destination_root], force_rescan=True)
    targets = list(registry.get_assets_by_path(destination_root, recursive=True))
    if not targets:
        raise RuntimeError("目标目录没有迁移资产")
    options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True, include_hard_package_references=True)
    for data in targets:
        if any(str(value).startswith(source_package_root + "/") for value in registry.get_dependencies(str(data.package_name), options)):
            raise RuntimeError("目标资产仍引用源目录")
    redirectors = []
    for data in registry.get_assets_by_path(source_package_root, recursive=True):
        package = str(data.package_name)
        if str(data.asset_class_path.asset_name) != "ObjectRedirector" or registry.get_referencers(package, options):
            raise RuntimeError("迁移源存在主资产或引用 拒绝清理: " + package)
        obj = unreal.load_object(None, package + "." + str(data.asset_name), follow_redirectors=False)
        if obj is None or obj.get_class().get_name() != "ObjectRedirector":
            raise RuntimeError("不能加载精确跳转对象")
        resolved = unreal.load_object(None, obj.get_path_name())
        if resolved is None or not resolved.get_path_name().startswith(destination_root + "/"):
            raise RuntimeError("跳转目标不在迁移目录")
        redirectors.append(obj)
    report = {"dry_run": dry_run, "asset_count": len(targets), "redirector_count": len(redirectors)}
    if dry_run:
        return report
    if redirectors:
        unreal.BBBAssetRepairEditorLibrary.delete_redirector_packages(redirectors)
    registry.scan_paths_synchronous([source_package_root], force_rescan=True)
    content = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
    source = content.joinpath(*source_package_root.split("/")[2:])
    for path in sorted(source.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    if source.exists() and not any(source.iterdir()):
        source.rmdir()
    if source.exists() or registry.get_assets_by_path(source_package_root, recursive=True):
        raise RuntimeError("导入源仍有残留 禁止再次迁移")
    report.update({"success": True, "old_root_removed": True})
    return report


def import_archive(archive_path, archive_content_root, source_package_root, destination_root, dry_run, finalize_only=False):
    """
    /**
     * 从原始压缩包导入独立资源包 使用原生重命名重写引用 不保留跳转
     * @param archive_path	原始 ZIP 文件
     * @param archive_content_root	ZIP 内对应原始包根的目录
     * @param source_package_root	资源包原有的 Game 根
     * @param destination_root	尚不存在的第三方目标根
     * @param dry_run	仅检查路径 冲突和文件清单
     * @param finalize_only	仅完成已迁移包的清理 不解压或移动主资产
     * @return 导入清单及最终依赖核验结果
     */
    """
    for value in (source_package_root, destination_root):
        if not re.fullmatch(r"/Game/(?:\w+/)*\w+", value):
            raise RuntimeError("包根必须是明确的 Game 路径")
    if not destination_root.startswith("/Game/_ThirdParty/"):
        raise RuntimeError("外部资源必须导入第三方目录")
    if source_package_root.split("/")[2].startswith("_"):
        raise RuntimeError("原始挂载根不得使用项目受保护目录")
    content = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
    source = content.joinpath(*source_package_root.split("/")[2:])
    destination = content.joinpath(*destination_root.split("/")[2:])
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    dirty = list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
    dirty.extend(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
    from MCP.mcp_asset_scope import conflicting_packages
    dirty = conflicting_packages([package.get_path_name() for package in dirty], [source_package_root, destination_root])
    if dirty or unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
        raise RuntimeError("脏包或 PIE 期间拒绝导入")
    if finalize_only:
        return json.dumps(finalize_import(source_package_root, destination_root, dry_run), ensure_ascii=False)
    if source.exists() or destination.exists():
        raise RuntimeError("源挂载目录或目标目录已经存在 拒绝覆盖")
    if registry.get_assets_by_path(source_package_root, recursive=True) or registry.get_assets_by_path(destination_root, recursive=True):
        raise RuntimeError("源或目标包根已在注册表占用")
    prefix = archive_content_root.replace("\\", "/").strip("/") + "/"
    entries = []
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = pathlib.PurePosixPath(info.filename[len(prefix):])
            if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                raise RuntimeError("压缩包包含越界路径")
            if relative.suffix.lower() not in {".uasset", ".umap", ".ubulk", ".uexp", ".uptnl"}:
                continue
            if not all(re.fullmatch(r"[\w.\-]+", part) for part in relative.parts):
                raise RuntimeError("包内路径包含无效字符")
            entries.append((info, relative))
        if not entries or len(entries) > 5000 or sum(info.file_size for info, _ in entries) > 8 * 1024 ** 3:
            raise RuntimeError("资源清单为空或超过导入上限")
        names = [str(relative).casefold() for _, relative in entries]
        if len(set(names)) != len(names):
            raise RuntimeError("压缩包包含重复文件")
        report = {"dry_run": dry_run, "archive": archive_path, "file_count": len(entries), "destination": destination_root}
        if dry_run:
            return json.dumps(report, ensure_ascii=False)
        for info, relative in entries:
            target = source.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    files = [str(source.joinpath(*relative.parts)) for _, relative in entries if relative.suffix in {".uasset", ".umap"}]
    registry.scan_files_synchronous(files, force_rescan=True)
    records = list(registry.get_assets_by_path(source_package_root, recursive=True))
    assets = []
    aliases = {}
    for data in records:
        package = str(data.package_name)
        object_path = package + "." + str(data.asset_name)
        asset = unreal.load_object(None, object_path)
        if asset is None:
            raise RuntimeError("导入包不能加载: " + object_path)
        if str(data.asset_class_path.asset_name) == "ObjectRedirector":
            aliases[object_path] = asset
            continue
        if asset.get_path_name() != object_path:
            raise RuntimeError("主资产路径与注册表不一致: " + object_path)
        assets.append((package, asset))
    if not assets:
        raise RuntimeError("资源包没有可导入主资产")
    renames = []
    mapping = {}
    for package, asset in assets:
        target = destination_root + package[len(source_package_root):]
        mapping[unreal.SoftObjectPath(asset.get_path_name())] = unreal.SoftObjectPath(target + "." + asset.get_name())
        renames.append(unreal.AssetRenameData(asset=asset, new_package_path=target.rsplit("/", 1)[0], new_name=asset.get_name()))
    if not unreal.AssetToolsHelpers.get_asset_tools().rename_assets(renames):
        raise RuntimeError("原生导入重命名失败 保留现场 禁止整批重试")
    for path, asset in aliases.items():
        mapping[unreal.SoftObjectPath(path)] = unreal.SoftObjectPath(asset.get_path_name())
    packages = [unreal.load_package(asset.get_path_name().split(".", 1)[0]) for _, asset in assets]
    unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, mapping)
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, False):
        raise RuntimeError("导入资产保存失败 保留现场")
    registry.scan_paths_synchronous([destination_root, source_package_root], force_rescan=True)
    options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True, include_hard_package_references=True)
    stale = {}
    for _, asset in assets:
        package = asset.get_path_name().split(".", 1)[0]
        old = [str(value) for value in registry.get_dependencies(package, options) if str(value).startswith(source_package_root + "/")]
        if old:
            stale[package] = old
    if stale:
        raise RuntimeError("导入后仍存在旧根引用: " + json.dumps(stale))
    finalize_import(source_package_root, destination_root, False)
    report.update({"success": True, "asset_count": len(assets), "alias_count": len(aliases), "old_root_removed": True,
                   "assets": [asset.get_path_name().split(".", 1)[0] for _, asset in assets]})
    unreal.log("[BBBAssetPackImport]完成 {} 个资产 无旧根引用".format(len(assets)))
    return json.dumps(report, ensure_ascii=False)
