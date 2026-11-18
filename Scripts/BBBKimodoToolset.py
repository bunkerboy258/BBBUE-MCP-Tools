import json
import uuid

import unreal
from BBBMcpCapabilities import mcp_tool
from toolset_registry.registration import Registration


MCP_INPUTS = {
    "prepare_kimodo_generation_batch": {
        "jobs_json": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "sequence_path": {"type": "string", "minLength": 1},
                    "output_asset_path": {"type": "string", "minLength": 1},
                    "start_frame": {"type": "integer", "minimum": 0},
                    "seed": {"type": "integer", "minimum": 0},
                    "prompt": {"type": "string", "minLength": 1, "maxLength": 1200},
                },
                "required": ["sequence_path", "output_asset_path", "start_frame", "seed", "prompt"],
                "additionalProperties": False,
            },
        },
    },
}


_batches = {}


def _object_path(asset_path):
    name = asset_path.rsplit("/", 1)[-1]
    return asset_path + "." + name


def _workspace_root(asset_path, marker):
    if marker not in asset_path:
        raise ValueError("资产路径必须位于武器型号的 Animation/" + marker.strip("/") + " 目录")
    return asset_path.rsplit(marker, 1)[0]


def _validate_asset_path(value):
    return isinstance(value, str) and value.startswith("/Game/_Project/Characters/") and "." not in value


def _normalize_path_array(value, field_name, empty_message):
    if isinstance(value, (str, bytes)):
        raise ValueError(field_name + " 必须是路径数组")
    try:
        paths = list(value)
    except TypeError as error:
        raise ValueError(field_name + " 必须是路径数组") from error
    if not paths:
        raise ValueError(empty_message)
    return paths


def _set_editor_property(obj, name, value):
    obj.set_editor_property(name, value)


def _finish_batch(batch_id, state):
    handle = state.get("tick_handle")
    if handle is not None:
        unreal.unregister_slate_post_tick_callback(handle)
        state["tick_handle"] = None


def _fail_batch(batch_id, state, message):
    state["status"] = "failed"
    state["error"] = str(message)
    _finish_batch(batch_id, state)
    unreal.log_error("[BBBKimodoToolset] " + str(message))


def _configure_generated_section(section, job):
    generator = section.get_editor_property("poseGenerator")
    if generator is None:
        raise RuntimeError("AnimGenOffline 没有为生成区段建立 Pose Generator")
    _set_editor_property(generator, "animDescriptionOverride", job["prompt"])
    _set_editor_property(generator, "randomSeed", int(job["seed"]))
    output_path = job["output_asset_path"]
    _set_editor_property(section, "outputAsset", unreal.SoftObjectPath(_object_path(output_path)))
    _set_editor_property(section, "bIncludeInBatchExport", True)
    _set_editor_property(section, "bStartAtOrigin", True)


def _tick_batch(batch_id, _delta_seconds):
    state = _batches.get(batch_id)
    if state is None or state["status"] != "preparing":
        return
    try:
        result = state.get("pending_result")
        if result is not None:
            if not result.get_editor_property("is_complete"):
                return
            error = result.get_editor_property("error")
            if error:
                raise RuntimeError(error)
            section = result.get_editor_property("value")
            if section is None or not isinstance(section, unreal.AnimGenOfflineGeneratorSection):
                raise RuntimeError("AnimGenOffline 返回了无效生成区段")
            job = state["jobs"][state["job_index"]]
            _configure_generated_section(section, job)
            state["sections"].append(section.get_path_name())
            state["pending_result"] = None
            state["job_index"] += 1

        if state["job_index"] >= len(state["jobs"]):
            for sequence in state["sequences"].values():
                unreal.EditorAssetLibrary.save_loaded_asset(sequence)
            state["status"] = "ready"
            state["outputs"] = [job["output_asset_path"] for job in state["jobs"]]
            state["sequence_paths"] = list(state["sequences"].keys())
            unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(
                next(iter(state["sequences"].values()))
            )
            unreal.LevelSequenceEditorBlueprintLibrary.force_update()
            _finish_batch(batch_id, state)
            unreal.log("[BBBKimodoToolset] Kimodo 批次准备完成 " + batch_id)
            return

        job = state["jobs"][state["job_index"]]
        track = state["tracks"][job["sequence_path"]]
        state["pending_result"] = state["mixer_extensions"].add_generated_animation_section_async(
            track, 0, int(job["start_frame"]), state["generator_class"]
        )
    except Exception as error:
        _fail_batch(batch_id, state, error)


@unreal.uclass()
class BBBKimodoToolset(unreal.ToolsetDefinition):
    """用 UE 5.9 Kimodo 与 AnimGenOffline 准备可批量生成和导出的动作序列。"""

    @mcp_tool
    @staticmethod
    def prepare_kimodo_generation_batch(
        target_mesh_path: str,
        sequence_paths: list[str],
        output_asset_paths: list[str],
        jobs_json: str,
    ) -> str:
        """
        /**
         * 为指定骨骼网格建立 Kimodo 生成区段与明确导出位置 不启动模型推理
         * @param target_mesh_path 目标角色 SkeletalMesh 资产路径
         * @param sequence_paths 新建的武器 Animation/work LevelSequence 资产路径
         * @param output_asset_paths 新建的武器 Animation/Sequence AnimSequence 资产路径
         * @param jobs_json JSON 数组 每项包含 sequence_path output_asset_path start_frame seed prompt
         * @return 批次编号及区段创建状态 完成后序列在 Sequencer 中打开
         */
        """
        if not _validate_asset_path(target_mesh_path):
            raise ValueError("目标网格必须是项目 Content/_Project 中的资产路径")
        sequence_paths = _normalize_path_array(
            sequence_paths, "sequence_paths", "sequence_paths 必须包含至少一个 Animation/work 序列"
        )
        output_asset_paths = _normalize_path_array(
            output_asset_paths, "output_asset_paths", "output_asset_paths 必须包含导出 AnimSequence 路径"
        )
        if len(set(sequence_paths)) != len(sequence_paths) or len(set(output_asset_paths)) != len(output_asset_paths):
            raise ValueError("序列和输出资产路径不能重复")
        for path in list(sequence_paths) + list(output_asset_paths):
            if not _validate_asset_path(path):
                raise ValueError("所有目标资产必须是项目 Content/_Project 中的新资产路径")
        try:
            jobs = json.loads(jobs_json)
        except Exception as error:
            raise ValueError("jobs_json 不是有效 JSON: " + str(error))
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= 12:
            raise ValueError("Kimodo 批次需包含 1 到 12 个动作")

        normalized_jobs = []
        for job in jobs:
            if not isinstance(job, dict) or set(job) != {
                "sequence_path", "output_asset_path", "start_frame", "seed", "prompt"
            }:
                raise ValueError("每项动作必须且只能包含 sequence_path output_asset_path start_frame seed prompt")
            sequence_path = job["sequence_path"]
            output_path = job["output_asset_path"]
            if sequence_path not in sequence_paths or output_path not in output_asset_paths:
                raise ValueError("jobs_json 中的资产路径必须同时列入写入范围")
            sequence_root = _workspace_root(sequence_path, "/Animation/work/")
            output_root = _workspace_root(output_path, "/Animation/Sequence/")
            if sequence_root != output_root:
                raise ValueError("每个动作序列和导出动画必须归属同一武器型号目录")
            if not isinstance(job["prompt"], str) or not job["prompt"].strip() or len(job["prompt"]) > 1200:
                raise ValueError("动作提示词不能为空且不能超过 1200 字符")
            start_frame = int(job["start_frame"])
            seed = int(job["seed"])
            if start_frame < 0 or start_frame % 150 != 0 or seed < 0:
                raise ValueError("起始帧需为非负 5 秒边界且随机种子不能为负数")
            normalized_jobs.append({
                "sequence_path": sequence_path,
                "output_asset_path": output_path,
                "start_frame": start_frame,
                "seed": seed,
                "prompt": job["prompt"].strip(),
            })
        if set(job["sequence_path"] for job in normalized_jobs) != set(sequence_paths):
            raise ValueError("每个工作序列至少要有一个动作区段")
        if set(job["output_asset_path"] for job in normalized_jobs) != set(output_asset_paths):
            raise ValueError("输出资产列表必须与 jobs_json 一一对应")
        if len(set((job["sequence_path"], job["start_frame"]) for job in normalized_jobs)) != len(normalized_jobs):
            raise ValueError("同一序列中的动作起始帧不能重复")

        mesh = unreal.EditorAssetLibrary.load_asset(target_mesh_path)
        if mesh is None or not isinstance(mesh, unreal.SkeletalMesh):
            raise RuntimeError("目标网格不存在或不是 SkeletalMesh: " + target_mesh_path)
        skeleton = mesh.get_editor_property("skeleton")
        if skeleton is None:
            raise RuntimeError("目标 SkeletalMesh 没有 Skeleton")

        mixer_extensions = getattr(unreal, "AnimGenOfflineMixerExtensions", None)
        track_class = getattr(unreal, "MovieSceneAnimationMixerTrack", None)
        generator_class = unreal.load_class(None, "/Script/Kimodo.KimodoPoseGenerator")
        if mixer_extensions is None or track_class is None or generator_class is None:
            raise RuntimeError("UE 5.9 Kimodo 与 AnimGenOffline 尚未加载 请先启用插件并重启编辑器")
        all_paths = list(sequence_paths) + list(output_asset_paths)
        existing = [path for path in all_paths if unreal.EditorAssetLibrary.does_asset_exist(path)]
        if existing:
            raise RuntimeError("拒绝覆盖已有资产: " + ", ".join(existing))

        grouped = {}
        for job in normalized_jobs:
            grouped.setdefault(job["sequence_path"], []).append(job)
        created_paths = []
        sequences = {}
        tracks = {}
        try:
            for sequence_path in sequence_paths:
                folder, name = sequence_path.rsplit("/", 1)
                unreal.EditorAssetLibrary.make_directory(folder)
                sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                    name, folder, unreal.LevelSequence, unreal.LevelSequenceFactoryNew()
                )
                if sequence is None:
                    raise RuntimeError("无法创建 LevelSequence: " + sequence_path)
                created_paths.append(sequence_path)
                sequence.set_display_rate(unreal.FrameRate(30, 1))
                sequence.set_playback_start(0)
                final_frame = max(job["start_frame"] + 150 for job in grouped[sequence_path])
                sequence.set_playback_end(final_frame)

                actor_system = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                actor = actor_system.spawn_actor_from_class(
                    unreal.SkeletalMeshActor, unreal.Vector(), unreal.Rotator(), transient=True
                )
                if actor is None:
                    raise RuntimeError("无法创建临时 SkeletalMeshActor")
                try:
                    actor.set_actor_label("Kimodo_PLA_Generation")
                    actor.skeletal_mesh_component.set_skeletal_mesh_asset(mesh)
                    actor.skeletal_mesh_component.set_editor_property("disable_post_process_blueprint", True)
                    binding = sequence.add_spawnable_from_instance(actor)
                finally:
                    actor_system.destroy_actor(actor)
                if not binding or not binding.is_valid():
                    raise RuntimeError("无法将 PLA 网格绑定为 LevelSequence Spawnable")
                tracks[sequence_path] = binding.add_track(track_class)
                if tracks[sequence_path] is None:
                    raise RuntimeError("无法创建 Animation Mixer Track: " + sequence_path)
                sequences[sequence_path] = sequence
                unreal.EditorAssetLibrary.save_loaded_asset(sequence)
        except Exception:
            for path in reversed(created_paths):
                if unreal.EditorAssetLibrary.does_asset_exist(path):
                    unreal.EditorAssetLibrary.delete_asset(path)
            raise

        batch_id = uuid.uuid4().hex[:16]
        state = {
            "status": "preparing",
            "error": "",
            "jobs": sorted(normalized_jobs, key=lambda item: (sequence_paths.index(item["sequence_path"]), item["start_frame"])),
            "job_index": 0,
            "pending_result": None,
            "sequences": sequences,
            "tracks": tracks,
            "sections": [],
            "target_mesh": target_mesh_path,
            "target_skeleton": skeleton.get_path_name(),
            "sequence_paths": list(sequence_paths),
            "outputs": list(output_asset_paths),
            "generator_class": generator_class,
            "mixer_extensions": mixer_extensions,
            "tick_handle": None,
        }
        _batches[batch_id] = state
        state["tick_handle"] = unreal.register_slate_post_tick_callback(
            lambda delta: _tick_batch(batch_id, delta)
        )
        return json.dumps({
            "batch_id": batch_id,
            "status": "preparing",
            "job_count": len(normalized_jobs),
            "target_mesh": target_mesh_path,
            "target_skeleton": skeleton.get_path_name(),
            "sequence_paths": list(sequence_paths),
            "output_asset_paths": list(output_asset_paths),
            "next": "inspect_kimodo_generation_batch",
        }, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def inspect_kimodo_generation_batch(batch_id: str) -> str:
        """读取 Kimodo 生成批次的准备进度、序列和导出位置 不启动推理。"""
        state = _batches.get(batch_id)
        if state is None:
            raise ValueError("Kimodo 批次编号不存在或编辑器会话已重启")
        return json.dumps({
            "batch_id": batch_id,
            "status": state["status"],
            "error": state["error"],
            "completed_sections": len(state["sections"]),
            "total_sections": len(state["jobs"]),
            "sequence_paths": state["sequence_paths"],
            "output_asset_paths": state["outputs"],
            "next": "open_kimodo_generation_sequence" if state["status"] == "ready" else "inspect_kimodo_generation_batch",
        }, ensure_ascii=False)

    @mcp_tool
    @staticmethod
    def open_kimodo_generation_sequence(batch_id: str, sequence_index: int) -> str:
        """在 Sequencer 打开已准备的 Kimodo 工作序列。"""
        state = _batches.get(batch_id)
        if state is None or state["status"] != "ready":
            raise RuntimeError("Kimodo 批次尚未准备完成")
        paths = state["sequence_paths"]
        if not isinstance(sequence_index, int) or not 0 <= sequence_index < len(paths):
            raise ValueError("sequence_index 超出序列范围")
        sequence = state["sequences"][paths[sequence_index]]
        unreal.LevelSequenceEditorBlueprintLibrary.open_level_sequence(sequence)
        unreal.LevelSequenceEditorBlueprintLibrary.force_update()
        return json.dumps({"batch_id": batch_id, "sequence_index": sequence_index, "sequence_path": paths[sequence_index]}, ensure_ascii=False)


_registration = Registration([BBBKimodoToolset])
