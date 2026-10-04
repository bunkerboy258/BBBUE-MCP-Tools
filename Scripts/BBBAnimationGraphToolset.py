import json

import unreal
import toolset_registry
from toolset_registry.registration import Registration
from toolset_registry.helpers import require_editable
from editor_toolset.toolsets.asset import AssetTools


@unreal.uclass()
class BBBAnimationGraphToolset(unreal.ToolsetDefinition):
    """
    /**
     * 创建显式时间双通道动画图并配置明确的骨骼表现组件
     */
    """

    @toolset_registry.tool_call
    @staticmethod
    def create_sequence_crossfade_blueprint(asset_path: str, parent_class_path: str, mesh_path: str, preview_animation_path: str, getter_names: list[str]) -> str:
        """
        /**
         * 创建新动画蓝图 连接标准序列求值器及布尔姿势混合并严格编译保存
         * @param asset_path			不存在的新资产路径
         * @param parent_class_path		提供线程安全查询的动画实例类
         * @param mesh_path			同骨架预览网格
         * @param preview_animation_path		同骨架预览动画
         * @param getter_names			甲乙序列 甲乙时间 乙启用 混合时间六个查询名
         * @return 新蓝图路径 生成类与编译状态
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止创建动画蓝图")

        library = getattr(unreal, "BBBAnimationGraphEditorLibrary", None)
        if library is None:
            raise RuntimeError("缺少原生动画图创建能力 请先编译项目编辑器模块")

        if not asset_path.startswith("/Game/") or "." in asset_path or unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            raise RuntimeError("目标必须为不存在的项目资产路径")

        mesh = unreal.load_asset(mesh_path)
        animation = unreal.load_asset(preview_animation_path)
        parent = unreal.load_class(None, parent_class_path)
        if not isinstance(mesh, unreal.SkeletalMesh) or not isinstance(animation, unreal.AnimSequence) or parent is None:
            raise RuntimeError("网格 预览动画或动画父类无效")

        skeleton = mesh.get_editor_property("skeleton")
        if skeleton != animation.get_editor_property("skeleton") or len(getter_names) != 6:
            raise RuntimeError("必须使用同骨架动画及六个查询")

        factory = unreal.AnimBlueprintFactory()
        factory.set_editor_property("parent_class", parent)
        factory.set_editor_property("target_skeleton", skeleton)
        factory.set_editor_property("preview_skeletal_mesh", mesh)
        directory, name = asset_path.rsplit("/", 1)
        blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, directory, unreal.AnimBlueprint, factory)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图创建失败")

        if not library.build_sequence_crossfade_graph(blueprint, animation, [unreal.Name(name) for name in getter_names]):
            raise RuntimeError("动画图连接失败 尚未保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        status = blueprint.get_editor_property("status")
        if status != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图必须无警告编译通过 尚未保存: " + str(status))

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")

        unreal.log("[BBBAnimationGraph] SAVED " + asset_path)
        return json.dumps({"asset": blueprint.get_path_name(), "generatedClass": blueprint.generated_class().get_path_name(), "status": str(status), "saved": True}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def configure_actor_animation_blueprint(actor_blueprint_path: str, mesh_component_property: str, animation_blueprint_path: str) -> str:
        """
        /**
         * 在独占签出的演员蓝图默认骨骼组件上配置同骨架动画蓝图
         * @param actor_blueprint_path		明确演员蓝图
         * @param mesh_component_property		持有骨骼组件的默认对象属性
         * @param animation_blueprint_path		已编译的同骨架动画蓝图
         * @return 保存后回读的动画类与播放模式
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改演员蓝图")

        blueprint = unreal.load_asset(actor_blueprint_path)
        animation = unreal.load_asset(animation_blueprint_path)
        if not isinstance(blueprint, unreal.Blueprint) or not isinstance(animation, unreal.AnimBlueprint):
            raise RuntimeError("演员或动画蓝图无效")

        require_editable(blueprint)
        state = unreal.SourceControl.query_file_state(actor_blueprint_path, True, False)
        if state.get_editor_property("is_checked_out_other"):
            raise RuntimeError("演员蓝图被其它工作区占用")

        if not AssetTools.is_checked_out(actor_blueprint_path) and not state.get_editor_property("is_added"):
            raise RuntimeError("写入前必须独占签出演员蓝图")

        component = unreal.get_default_object(blueprint.generated_class()).get_editor_property(mesh_component_property)
        if not isinstance(component, unreal.SkeletalMeshComponent):
            raise RuntimeError("指定属性不是骨骼网格组件")

        mesh = component.get_editor_property("skeletal_mesh_asset")
        if mesh is None or mesh.get_editor_property("skeleton") != animation.get_editor_property("target_skeleton"):
            raise RuntimeError("演员网格与动画蓝图骨架不一致")

        if animation.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画蓝图尚未无警告编译通过")

        blueprint.modify()
        component.modify()
        component.set_editor_property("animation_mode", unreal.AnimationMode.ANIMATION_BLUEPRINT)
        component.set_editor_property("anim_class", animation.generated_class())
        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("演员蓝图编译失败或存在警告 尚未保存")

        component = unreal.get_default_object(blueprint.generated_class()).get_editor_property(mesh_component_property)
        if component.get_editor_property("anim_class") != animation.generated_class():
            raise RuntimeError("编译后动画类回读失败 尚未保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("演员蓝图保存失败")

        unreal.log("[BBBAnimationGraph] BOUND " + actor_blueprint_path)
        return json.dumps({"asset": blueprint.get_path_name(), "component": component.get_path_name(), "animationClass": component.get_editor_property("anim_class").get_path_name(), "animationMode": str(component.get_editor_property("animation_mode")), "saved": True}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def bind_sequence_crossfade_getters(asset_path: str, getter_names: list[str]) -> str:
        """
        /**
         * 将标准双通道动画图输入连接到只读纯函数并编译保存
         * @param asset_path		明确独占签出或待添加的标准动画蓝图
         * @param getter_names		六个快照查询名称
         * @return 编译和保存结果
         */
        """
        if unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world() is not None:
            raise RuntimeError("PIE 期间禁止修改动画图")

        blueprint = unreal.load_asset(asset_path)
        if not isinstance(blueprint, unreal.AnimBlueprint):
            raise RuntimeError("动画蓝图不存在")

        require_editable(blueprint)
        state = unreal.SourceControl.query_file_state(asset_path, True, False)
        if state.get_editor_property("is_checked_out_other") or not (AssetTools.is_checked_out(asset_path) or state.get_editor_property("is_added")):
            raise RuntimeError("动画蓝图必须由本工作区独占持有")

        if not unreal.BBBAnimationGraphEditorLibrary.bind_sequence_crossfade_getters(blueprint, [unreal.Name(name) for name in getter_names]):
            raise RuntimeError("图表结构或快照查询不符合要求 尚未保存")

        unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
        if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
            raise RuntimeError("动画图未无警告编译通过 尚未保存")

        if not unreal.EditorAssetLibrary.save_loaded_asset(blueprint, False):
            raise RuntimeError("动画蓝图保存失败")

        return json.dumps({"asset": blueprint.get_path_name(), "saved": True}, ensure_ascii=False)


_registration = Registration([BBBAnimationGraphToolset])
