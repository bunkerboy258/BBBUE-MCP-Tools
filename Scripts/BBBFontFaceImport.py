import json
import os
import re

import unreal

from BBBAssetWritePolicy import require_asset_write


def import_font_faces(requests_json):
    """
    /**
     * 导入明确的永久字体源文件 不生成额外 Font 或覆盖既有资产
     * @param requests_json\t每项包含 source 与 destination 包路径
     * @return\t已保存 FontFace 的路径与原始来源
     */
    """
    requests = json.loads(requests_json)
    if not isinstance(requests, list) or not 1 <= len(requests) <= 16:
        raise RuntimeError("字体请求必须为一至十六项")
    content = os.path.realpath(unreal.Paths.project_content_dir())
    prepared = []
    destinations = set()
    for request in requests:
        source = os.path.realpath(request["source"])
        destination = request["destination"]
        if not re.fullmatch(r"/Game/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+", destination) or destination in destinations:
            raise RuntimeError("字体目标必须是唯一的 Game 包路径")
        destinations.add(destination)
        if os.path.commonpath([content, source]) != content or not os.path.isfile(source):
            raise RuntimeError("字体源文件必须永久保存在项目 Content 内")
        if os.path.splitext(source)[1].lower() not in (".ttf", ".otf"):
            raise RuntimeError("字体源仅支持 TTF 与 OTF")
        if unreal.EditorAssetLibrary.does_asset_exist(destination):
            raise RuntimeError("字体目标已存在 拒绝覆盖: " + destination)
        prepared.append((source, destination))
    require_asset_write([], [destination for _, destination in prepared])
    results = []
    for source, destination in prepared:
        directory, name = destination.rsplit("/", 1)
        factory = unreal.FontFileImportFactory()
        factory.set_editor_property("batch_create_font_asset", unreal.BatchCreateFontAsset.NO)
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source)
        task.set_editor_property("destination_path", directory)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("factory", factory)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", False)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        face = unreal.EditorAssetLibrary.load_asset(destination)
        if not isinstance(face, unreal.FontFace):
            raise RuntimeError("字体未生成明确的 FontFace: " + destination)
        face.set_editor_property("loading_policy", unreal.FontLoadingPolicy.INLINE)
        if not unreal.EditorAssetLibrary.save_loaded_asset(face, False):
            raise RuntimeError("字体保存失败: " + destination)
        results.append({"asset": face.get_path_name(), "source": source})
    return json.dumps(results, ensure_ascii=False)
