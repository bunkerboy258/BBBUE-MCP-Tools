import json
import os
import re

import unreal


def export_textures(asset_paths, export_name):
    """
    /**
     * 使用原生 PNG 导出器交付明确纹理列表 保留完整源像素
     * @param asset_paths\tTexture2D 包路径列表
     * @param export_name\tSaved/Exports 下的新交付目录名称
     * @return\tJSON 文件与原始尺寸清单
     */
    """
    if unreal.EditorLevelLibrary.get_pie_worlds(False):
        raise RuntimeError("PIE 期间禁止导出纹理交付包")

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", export_name):
        raise RuntimeError("交付目录名称必须使用字母数字下划线或连字符")

    if not asset_paths or len(asset_paths) > 256 or len(set(asset_paths)) != len(asset_paths):
        raise RuntimeError("纹理列表必须为一至二百五十六个不重复包路径")

    directory = os.path.realpath(os.path.join(unreal.Paths.project_saved_dir(), "Exports", export_name))
    if os.path.exists(directory):
        raise RuntimeError("交付目录已存在 禁止覆盖 " + directory)

    assets = []
    for path in asset_paths:
        if not path.startswith("/Game/") or "." in path or ".." in path:
            raise RuntimeError("必须提供明确 Game 包路径 " + path)

        asset = unreal.EditorAssetLibrary.load_asset(path)
        if not isinstance(asset, unreal.Texture2D):
            raise RuntimeError("目标不是 Texture2D " + path)

        assets.append(asset)

    results = []
    for asset in assets:
        package = asset.get_path_name().split(".", 1)[0]
        relative = package.removeprefix("/Game/") + ".png"
        filename = os.path.join(directory, *relative.split("/"))
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        task = unreal.AssetExportTask()
        task.object = asset
        task.filename = filename
        task.exporter = unreal.TextureExporterPNG()
        task.automated = True
        task.prompt = False
        task.replace_identical = False
        task.write_empty_files = False
        if not unreal.Exporter.run_asset_export_task(task):
            raise RuntimeError("原生 PNG 导出失败 " + package)

        if not os.path.isfile(filename) or os.path.getsize(filename) < 24:
            raise RuntimeError("导出器没有产生有效文件 " + filename)

        results.append({"asset": package, "file": relative, "width": asset.blueprint_get_size_x(), "height": asset.blueprint_get_size_y(), "bytes": os.path.getsize(filename)})

    manifest = os.path.join(directory, "TextureManifest.json")
    with open(manifest, "x", encoding="utf-8") as output:
        json.dump(results, output, ensure_ascii=False, indent=4)

    unreal.log("[BBB][TextureExport] 已导出 " + str(len(results)) + " 张纹理至 " + directory)
    return json.dumps({"directory": directory, "count": len(results), "manifest": manifest}, ensure_ascii=False)
