import json
import re

import unreal
from BBBMcpCapabilities import mcp_tool
from BBBAssetWritePolicy import require_asset_write
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBMonsterGoreToolset(unreal.ToolsetDefinition):
    """/** 统一血腥资源制作及原生预览 不承担伤害逻辑 */"""

    @mcp_tool
    @staticmethod
    def configure_monster_wound_materials(definition_path: str) -> str:
        """
        /**
         * @param definition_path\tShared/Injury 中已配置的预制伤口数据资产
         * @return 保存并回读的共享投影材质 不生成身体或组织网格
         */
        """
        if not re.fullmatch(r"/Game/_Project/Mass/Monster/Zombie/Shared/Injury/[A-Za-z0-9_/]+", definition_path):
            raise RuntimeError("需要明确的自有伤口配置路径")
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止适配共享材质")
        if unreal.SourceControl.is_enabled() and unreal.SourceControl.current_provider() == "Perforce":
            raise RuntimeError("本项目不使用 Perforce")
        definition = unreal.load_asset(definition_path)
        if not isinstance(definition, unreal.BBBMonsterGoreDefinition):
            raise RuntimeError("需要伤口表现配置")
        folder = definition_path.rsplit("/", 1)[0]
        material_folder = "/Game/_Project/Mass/Monster/Zombie/Shared/Injury/Materials"
        existing = list(unreal.EditorAssetLibrary.list_assets(folder, recursive=True, include_folder=False))
        existing.extend(unreal.EditorAssetLibrary.list_assets(material_folder, recursive=True, include_folder=False))
        destinations = [folder, material_folder]
        for wound in definition.get_editor_property("wounds"):
            for field in ("tissue", "detached_skin", "detached_mesh"):
                resource = wound.get_editor_property(field)
                if resource is not None:
                    if not resource.get_path_name().startswith("/Game/_Project/Mass/Monster/Zombie/Shared/Injury/"):
                        raise RuntimeError("预制资源必须位于本轮自有路径")
                    existing.append(resource.get_path_name())
        require_asset_write(existing, destinations=destinations)
        result = str(unreal.BBBMonsterGoreEditorLibrary.configure_wound_materials(definition))
        if result.startswith("失败"):
            raise RuntimeError(result)
        saved = str(unreal.BBBMonsterGoreEditorLibrary.save_gore_configuration(definition))
        if saved.startswith("失败"):
            raise RuntimeError(saved)
        report = json.loads(str(unreal.BBBMonsterGoreEditorLibrary.inspect_gore_assets(definition)))
        report["saved"] = True
        report["bodyTopologyModified"] = False
        return json.dumps(report, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_monster_gore_assets(definition_path: str) -> str:
        """
        /**
         * @param definition_path\t当前统一血腥配置包路径
         * @return 资源状态 不运行世界 不保存
         */
        """
        definition = unreal.load_asset(definition_path)
        if not isinstance(definition, unreal.BBBMonsterGoreDefinition):
            raise RuntimeError("需要统一血腥表现配置")
        return str(unreal.BBBMonsterGoreEditorLibrary.inspect_gore_assets(definition))


_registration = Registration([BBBMonsterGoreToolset])
