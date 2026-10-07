import json
from pathlib import Path
import re
import stat
import wave

import unreal


def _paths(asset_paths):
    """
    /**
     * @param asset_paths	声音路径
     * @return 已验证且去重前一致的路径
     */
    """
    if not isinstance(asset_paths, (list, unreal.Array)):
        raise RuntimeError("声音检查需要列表 实际类型=" + str(type(asset_paths)))
    if not 1 <= len(asset_paths) <= 256:
        raise RuntimeError("声音检查每批需要 1 至 256 个路径")
    packages = []
    for path in asset_paths:
        if not isinstance(path, str) or not re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?", path):
            raise RuntimeError("声音资产路径无效")
        package = path.split(".")[0]
        if "." in path and path.split(".")[1] != package.rsplit("/", 1)[1]:
            raise RuntimeError("资产对象名与包名不一致")
        packages.append(package)
    if len(set(path.casefold() for path in packages)) != len(packages):
        raise RuntimeError("声音资产路径重复")
    return packages


def _value(value):
    """
    /**
     * @param value	UE 属性
     * @return 可序列化的值
     */
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, unreal.Object):
        return value.get_path_name()
    if isinstance(value, (list, tuple, unreal.Array, unreal.Set)):
        return [_value(item) for item in value]
    return str(value)


def _properties(obj, names):
    """
    /**
     * @param obj	属性宿主
     * @param names	属性名称
     * @return 值及失败原因
     */
    """
    values, errors = {}, {}
    for name in names:
        try:
            values[name] = _value(obj.get_editor_property(name))
        except Exception as error:
            errors[name] = str(error)
    return {"values": values, "unavailable": errors}


def _nodes(cue):
    """
    /**
     * @param cue	声音提示
     * @return 可达节点及波形引用检查
     */
    """
    root = cue.get_editor_property("first_node")
    pending = [root] if root else []
    visited, rows = set(), []
    while pending:
        node = pending.pop()
        path = node.get_path_name()
        if path in visited:
            continue
        visited.add(path)
        children = list(node.get_editor_property("child_nodes"))
        row = {"path": path, "class": node.get_class().get_name(), "children": [_value(child) for child in children]}
        if isinstance(node, unreal.SoundNodeWavePlayer):
            row["wave_player"] = _properties(node, ["sound_wave", "sound_wave_asset_ptr", "looping"])
            wave_object = node.get_editor_property("sound_wave")
            row["wave_loaded"] = isinstance(wave_object, unreal.SoundWave)
        rows.append(row)
        pending.extend(child for child in children if child is not None)
    return rows


def inspect_sounds(asset_paths):
    """
    /**
     * @param asset_paths	声音资产路径
     * @return 只读音频审计 JSON
     */
    """
    packages = _paths(asset_paths)
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions(include_hard_package_references=True, include_soft_package_references=True)
    rows = []
    for package in packages:
        asset = unreal.EditorAssetLibrary.load_asset(package)
        if not isinstance(asset, (unreal.SoundWave, unreal.SoundCue)):
            raise RuntimeError("资产不是可读取的 SoundWave 或 SoundCue: " + package)
        row = {"asset": asset.get_path_name(), "class": asset.get_class().get_name(), "dependencies": [str(item) for item in registry.get_dependencies(package, options)]}
        row["properties"] = _properties(asset, ["duration", "attenuation_settings", "concurrency_set", "override_concurrency", "concurrency_overrides", "virtualization_mode", "priority", "sound_class_object", "sound_submix_object"])
        if isinstance(asset, unreal.SoundWave):
            row["wave"] = _properties(asset, ["num_channels", "sample_rate", "imported_sample_rate", "looping", "compression_quality", "loading_behavior", "volume", "pitch"])
        else:
            row["cue"] = _properties(asset, ["volume_multiplier", "pitch_multiplier", "override_attenuation"])
            row["attenuation"] = _properties(asset.get_editor_property("attenuation_overrides"), ["attenuate", "spatialize", "attenuation_shape", "attenuation_shape_extents", "falloff_distance"])
            row["nodes"] = _nodes(asset)
        rows.append(row)
    return json.dumps({"asset_count": len(rows), "assets": rows}, ensure_ascii=False)


def _directory(output_directory):
    """
    /**
     * @param output_directory	导出目录
     * @return 无链接的 Saved/temp 子目录
     */
    """
    if not isinstance(output_directory, str) or not output_directory:
        raise RuntimeError("导出目录不能为空")
    root = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir())).absolute() / "temp"
    candidate = Path(output_directory)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeError("导出目录需要无父级跳转的绝对路径")
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise RuntimeError("导出目录必须位于 Saved/temp 内") from error
    if not relative.parts:
        raise RuntimeError("不能直接写入 Saved/temp 根目录")
    for parent in [candidate, *candidate.parents]:
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError("导出路径包含链接")
    return candidate


def export_waves(asset_paths, output_directory):
    """
    /**
     * @param asset_paths	波形路径
     * @param output_directory	临时目录
     * @return 原生导出 WAV 清单
     */
    """
    packages = _paths(asset_paths)
    directory = _directory(output_directory)
    assets, files = [], []
    for package in packages:
        asset = unreal.EditorAssetLibrary.load_asset(package)
        if not isinstance(asset, unreal.SoundWave):
            raise RuntimeError("只能导出 SoundWave: " + package)
        filename = directory / (asset.get_name() + ".wav")
        if filename.exists():
            raise RuntimeError("禁止覆盖导出文件: " + str(filename))
        assets.append(asset)
        files.append(filename)
    if len(set(str(path).casefold() for path in files)) != len(files):
        raise RuntimeError("不同包的导出文件名重复")
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for asset, filename in zip(assets, files):
        task = unreal.AssetExportTask()
        task.object = asset
        task.exporter = unreal.SoundExporterWAV()
        task.filename = str(filename)
        task.automated = True
        task.prompt = False
        task.replace_identical = False
        task.write_empty_files = False
        if not unreal.Exporter.run_asset_export_task(task):
            raise RuntimeError("WAV 导出失败: " + asset.get_path_name())
        with wave.open(str(filename), "rb") as source:
            row = {"asset": asset.get_path_name(), "file": str(filename), "channels": source.getnchannels(), "sample_rate": source.getframerate(), "sample_width": source.getsampwidth(), "frames": source.getnframes(), "duration": source.getnframes() / source.getframerate()}
        rows.append(row)
    return json.dumps({"export_count": len(rows), "files": rows}, ensure_ascii=False)
