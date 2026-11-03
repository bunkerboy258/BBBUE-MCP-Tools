import hashlib
import json
import pathlib
import re
import shutil

import unreal

from BBBAssetWritePolicy import require_asset_write


def import_packages(content_directory, relative_packages, destination_root, dry_run):
    """/** @param content_directory 外部 Content @param relative_packages 明确相对包名 @param destination_root 第三方目标 @param dry_run 预检 @return 导入及原生引用重写结果 */"""
    source = pathlib.Path(content_directory).resolve()
    content = pathlib.Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir())).resolve()
    if not source.is_dir() or source == content or not re.fullmatch(r'/Game/_ThirdParty/\w+/\w+', destination_root):
        raise RuntimeError('要求外部 Content 与明确第三方资源包根')
    if not 1 <= len(relative_packages) <= 512 or len(set(relative_packages)) != len(relative_packages):
        raise RuntimeError('要求一至五百一十二个唯一包')
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    files = []
    originals = []
    targets = []
    hashes = {}
    for relative in relative_packages:
        if not re.fullmatch(r'\w+(?:/\w+)+', relative) or relative.startswith('_'):
            raise RuntimeError('外部包名无效')
        original = '/Game/' + relative
        target = destination_root + '/' + relative
        originals.append(original)
        targets.append(target)
        if unreal.EditorAssetLibrary.does_asset_exist(target):
            raise RuntimeError('目标已经存在 拒绝覆盖: ' + relative)
        filename = source / (relative + '.uasset')
        if not filename.is_file():
            raise RuntimeError('来源包不存在: ' + relative)
        for suffix in ('.uasset', '.uexp', '.ubulk', '.uptnl'):
            item = source / (relative + suffix)
            if item.is_file():
                staged = content / (relative + suffix)
                if staged.exists() and hashlib.sha256(staged.read_bytes()).digest() != hashlib.sha256(item.read_bytes()).digest():
                    raise RuntimeError('原始文件路径已占用且与来源不同: ' + str(staged))
                files.append((item, staged))
                hashes[str(item)] = hashlib.sha256(item.read_bytes()).hexdigest()
    size = sum(item.stat().st_size for item, _ in files)
    if size > 512 * 1024 * 1024:
        raise RuntimeError('明确导入清单超过五百一十二 MB')
    options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True, include_hard_package_references=True)
    allowed = set(originals)
    missing = sorted({str(value) for original in originals for value in registry.get_dependencies(original, options)
                      if str(value).startswith('/Game/') and str(value) not in allowed
                      and not unreal.EditorAssetLibrary.does_asset_exist(str(value))})
    report = {'dryRun': dry_run, 'packages': len(originals), 'bytes': size, 'source': str(source), 'destination': destination_root,
              'unresolvedDependencies': missing}
    if dry_run:
        return report
    existing = [name for name in originals if unreal.EditorAssetLibrary.does_asset_exist(name)]
    require_asset_write(existing, [name for name in originals + targets if name not in existing])
    dirty = list(unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages())
    dirty.extend(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages())
    if any(package.get_path_name() not in allowed for package in dirty):
        raise RuntimeError('导入前需要保存范围外现有脏包')
    # 原始资源先以原有包名导入 再统一交由引擎重命名改写硬软引用
    for item, staged in files:
        staged.parent.mkdir(parents=True, exist_ok=True)
        if not staged.exists():
            shutil.copyfile(item, staged)
    registry.scan_files_synchronous([str(staged) for _, staged in files if staged.suffix == '.uasset'], force_rescan=True)
    missing = set()
    for original in originals:
        for dependency in registry.get_dependencies(original, options):
            name = str(dependency)
            if name.startswith('/Game/') and name not in allowed and not unreal.EditorAssetLibrary.does_asset_exist(name):
                missing.add(name)
    if missing:
        raise RuntimeError('缺少依赖 保留导入现场: ' + json.dumps(sorted(missing)))
    if existing:
        result = unreal.EditorLoadingAndSavingUtils.reload_packages([unreal.load_package(name) for name in existing])
        if not result[0]:
            raise RuntimeError('重新载入原始导入包失败: ' + str(result[1]))
    loaded = []
    for original in originals:
        data = unreal.EditorAssetLibrary.find_asset_data(original)
        if not data.is_valid() or str(data.asset_class_path.asset_name) == 'ObjectRedirector':
            raise RuntimeError('清单必须为真实主资产 不接受跳转: ' + original)
        asset = unreal.load_asset(original)
        if asset is None or asset.get_outermost().get_path_name() != original:
            raise RuntimeError('原始资源未完整加载: ' + original)
        loaded.append(asset)
    renames = [unreal.AssetRenameData(asset=asset, new_package_path=target.rsplit('/', 1)[0], new_name=asset.get_name())
               for asset, target in zip(loaded, targets)]
    if not unreal.AssetToolsHelpers.get_asset_tools().rename_assets(renames):
        raise RuntimeError('引擎重命名未完成 保留现场 禁止整批重试')
    mapping = {unreal.SoftObjectPath(old + '.' + asset.get_name()): unreal.SoftObjectPath(asset.get_path_name())
               for old, asset in zip(originals, loaded)}
    packages = [asset.get_outermost() for asset in loaded]
    unreal.AssetToolsHelpers.get_asset_tools().rename_referencing_soft_object_paths(packages, mapping)
    for asset in loaded:
        if isinstance(asset, unreal.Blueprint):
            unreal.BlueprintEditorLibrary.compile_blueprint(asset)
            if asset.get_editor_property('status') != unreal.BlueprintStatus.BS_UP_TO_DATE:
                raise RuntimeError('导入蓝图编译未通过 不保存: ' + asset.get_path_name())
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages, False):
        raise RuntimeError('目标包保存失败')
    registry.scan_paths_synchronous([destination_root], force_rescan=True)
    for asset, target in zip(loaded, targets):
        if asset.get_outermost().get_path_name() != target:
            raise RuntimeError('目标包回读不符')
        if any(str(value) in allowed for value in registry.get_dependencies(target, options)):
            raise RuntimeError('目标仍引用原始包: ' + target)
    redirects = []
    for original in originals:
        obj = unreal.load_object(None, original + '.' + original.rsplit('/', 1)[1], follow_redirectors=False)
        if obj and obj.get_class().get_name() == 'ObjectRedirector':
            if registry.get_referencers(original, options):
                raise RuntimeError('原始跳转仍被引用 保留现场: ' + original)
            redirects.append(obj)
    if redirects:
        unreal.BBBAssetRepairEditorLibrary.delete_redirector_packages(redirects)
    for item, _ in files:
        if hashlib.sha256(item.read_bytes()).hexdigest() != hashes[str(item)]:
            raise RuntimeError('外部来源指纹发生变化')
    report.update({'saved': True, 'sourceUnchanged': True, 'assets': targets, 'redirectorsRemoved': len(redirects)})
    unreal.log('[BBBExternalPackageImport]已保存并核对 ' + str(len(targets)) + ' 个资产')
    return report
