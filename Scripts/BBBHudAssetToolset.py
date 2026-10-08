import json
import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBHudAssetToolset(unreal.ToolsetDefinition):
    """按真实网格生成透明白色正投影图标 不依赖渲染宿主"""

    @mcp_tool
    @staticmethod
    def render_mesh_silhouettes(requests_json: str) -> str:
        """
        /**
         * @param requests_json	每项包含 mesh output 以及可选 horizontal_axis vertical_axis flip_horizontal
         * @return Saved/temp 下新建 PNG 路径列表 不修改源资产 不覆盖文件
         */
        """
        requests = json.loads(requests_json)
        if not isinstance(requests, list) or not 1 <= len(requests) <= 100:
            raise RuntimeError("轮廓图请求数量必须为一到一百")
        results = []
        for request in requests:
            path = unreal.BBBAssetThumbnailEditorLibrary.render_mesh_silhouette(
                request["mesh"], request["output"], int(request.get("horizontal_axis", 0)),
                int(request.get("vertical_axis", 2)), bool(request.get("flip_horizontal", False)))
            if not path:
                raise RuntimeError("轮廓图生成失败: " + request["mesh"])
            results.append({"mesh": request["mesh"], "image": path})
        return json.dumps(results, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def set_input_action_keys(mapping_context_path: str, mappings_json: str) -> str:
        """
        /**
         * @param mapping_context_path	需要更新的输入映射资产
         * @param mappings_json	每项包含 action 资产路径和 key 按键名称
         * @return 更新后的按键映射和保留映射数量
         */
        """
        from BBBAssetWritePolicy import require_write_access

        context = unreal.EditorAssetLibrary.load_asset(mapping_context_path)
        if not isinstance(context, unreal.InputMappingContext):
            raise RuntimeError("目标不是输入映射资产")

        requests = json.loads(mappings_json)
        if not isinstance(requests, list) or not requests or len(requests) > 100:
            raise RuntimeError("按键映射数量必须为一到一百")

        actions = {}
        for request in requests:
            action = unreal.EditorAssetLibrary.load_asset(request["action"])
            if not isinstance(action, unreal.InputAction):
                raise RuntimeError("输入动作不存在: " + request["action"])
            path = action.get_path_name()
            if path in actions:
                raise RuntimeError("每个动作只能指定一个按键")
            key = unreal.Key()
            key.set_editor_property("key_name", request["key"])
            if not unreal.InputLibrary.key_is_valid(key=key):
                raise RuntimeError("按键名称无效: " + request["key"])
            actions[path] = (action, key)

        require_write_access(context)
        before = list(context.get_editor_property("default_key_mappings").get_editor_property("mappings"))
        retained = [entry for entry in before if not entry.get_editor_property("action")
            or entry.get_editor_property("action").get_path_name() not in actions]

        with unreal.ScopedEditorTransaction("更新输入动作按键"):
            context.modify()
            for action, key in actions.values():
                context.unmap_all_keys_from_action(action)
                context.map_key(action, key)

        after = list(context.get_editor_property("default_key_mappings").get_editor_property("mappings"))
        actual = {}
        for entry in after:
            action = entry.get_editor_property("action")
            if action and action.get_path_name() in actions:
                actual.setdefault(action.get_path_name(), []).append(str(entry.get_editor_property("key").get_editor_property("key_name")))

        expected = {path: [str(key.get_editor_property("key_name"))] for path, (_, key) in actions.items()}
        if actual != expected or len(after) != len(retained) + len(actions):
            raise RuntimeError("输入映射验证失败 禁止保存")
        if not unreal.EditorAssetLibrary.save_loaded_asset(context, False):
            raise RuntimeError("输入映射保存失败")

        return json.dumps({"asset": context.get_path_name(), "mappings": actual,
            "retainedCount": len(retained)}, ensure_ascii=False)


_registration = Registration([BBBHudAssetToolset])
