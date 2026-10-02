import builtins
import csv
import json
import math
import os
import time
import traceback

import unreal


OUTPUT_PATH = os.path.join(
    unreal.Paths.project_saved_dir(),
    "Diagnostics",
    "BBBLocomotionRuntime.jsonl",
)
FEET_OUTPUT_PATH = os.path.join(
    unreal.Paths.project_saved_dir(),
    "Diagnostics",
    "BBBLocomotionFeet.csv",
)


class BBBLocomotionSyncRuntimeProbe:
    def __init__(self):
        self.callback_handle = None
        self.output_file = None
        self.feet_file = None
        self.feet_writer = None
        self.start_time = time.time()
        self.frame_index = 0
        self.log_enabled_worlds = set()
        self.last_states = {}
        self.previous_pose_samples = {}
        self.prepared_mesh_paths = set()
        self.original_mesh_tick_options = {}

    def start(self):
        self.stop()

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        self.output_file = open(OUTPUT_PATH, "w", encoding="utf-8", buffering=1)
        self.feet_file = open(
            FEET_OUTPUT_PATH,
            "w",
            encoding="utf-8",
            newline="",
            buffering=1,
        )
        self.feet_writer = csv.DictWriter(
            self.feet_file,
            fieldnames=[
                "frame",
                "probe_time",
                "world_time",
                "state",
                "velocity_2d",
                "actual_displacement_speed",
                "anim_displacement_speed",
                "actor_x",
                "actor_y",
                "actor_z",
                "pelvis_x",
                "pelvis_y",
                "pelvis_z",
                "foot_l_x",
                "foot_l_y",
                "foot_l_z",
                "foot_r_x",
                "foot_r_y",
                "foot_r_z",
                "foot_l_world_speed",
                "foot_r_world_speed",
                "foot_l_mesh_relative_speed",
                "foot_r_mesh_relative_speed",
                "disable_leg_ik",
                "disable_foot_locking",
                "use_foot_placement",
            ],
        )
        self.feet_writer.writeheader()
        self.write_record({
            "event": "probe_started",
            "native_runtime_snapshot": True,
            "feet_output": FEET_OUTPUT_PATH,
        })

        self.callback_handle = unreal.register_slate_post_tick_callback(self.tick)
        unreal.log_warning("[BBB Runtime Locomotion Probe] 已启动，请进入 PIE 复现踏步")
        unreal.log_warning(f"[BBB Runtime Locomotion Probe] 全链路报告：{OUTPUT_PATH}")
        unreal.log_warning(f"[BBB Runtime Locomotion Probe] 脚部轨迹：{FEET_OUTPUT_PATH}")
        unreal.log_warning("[BBB Runtime Locomotion Probe] 不会修改或保存任何动画资产")

    def stop(self):
        self.disable_runtime_logs()

        for mesh, tick_option in self.original_mesh_tick_options.values():
            try:
                mesh.set_editor_property("visibility_based_anim_tick_option", tick_option)
            except Exception:
                unreal.log_warning("[BBB Runtime Locomotion Probe] PIE 网格已销毁 无需恢复求值策略")

        self.original_mesh_tick_options.clear()
        self.prepared_mesh_paths.clear()

        if self.callback_handle is not None:
            try:
                unreal.unregister_slate_post_tick_callback(self.callback_handle)
            except Exception:
                pass

        self.callback_handle = None

        if self.output_file is not None:
            self.write_record({"event": "probe_stopped"})
            self.output_file.close()

        if self.feet_file is not None:
            self.feet_file.close()

        self.output_file = None
        self.feet_file = None
        self.feet_writer = None
        unreal.log_warning("[BBB Runtime Locomotion Probe] 已停止")

    def disable_runtime_logs(self):
        worlds = self.get_pie_worlds()

        if not worlds:
            try:
                subsystem = unreal.get_editor_subsystem(
                    unreal.UnrealEditorSubsystem,
                )
                editor_world = subsystem.get_editor_world()
                if editor_world is not None:
                    worlds.append(editor_world)
            except Exception:
                pass

        if not worlds:
            return

        unreal.SystemLibrary.execute_console_command(
            worlds[0],
            "bbb.Animation.LocomotionProbe 0",
        )
        unreal.SystemLibrary.execute_console_command(
            worlds[0],
            "Log LogAnimMarkerSync Warning",
        )

    def write_record(self, record):
        if self.output_file is None:
            return

        record["probe_time"] = round(time.time() - self.start_time, 6)
        record["frame"] = self.frame_index
        self.output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_pie_worlds(self):
        worlds = []
        editor_level_library = getattr(unreal, "EditorLevelLibrary", None)

        if editor_level_library is not None:
            try:
                worlds.extend(editor_level_library.get_pie_worlds(False))
            except Exception:
                pass

        if worlds:
            return worlds

        try:
            subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            game_world = subsystem.get_game_world()
            if game_world is not None:
                worlds.append(game_world)
        except Exception:
            pass

        return worlds

    def enable_runtime_logs(self, world):
        world_path = world.get_path_name()
        if world_path in self.log_enabled_worlds:
            return

        unreal.SystemLibrary.execute_console_command(
            world,
            "bbb.Animation.LocomotionProbe 1",
        )
        unreal.SystemLibrary.execute_console_command(
            world,
            "Log LogAnimMarkerSync Log",
        )
        self.log_enabled_worlds.add(world_path)
        self.write_record({
            "event": "runtime_logs_enabled",
            "world": world_path,
        })
        unreal.log_warning("[BBB Runtime Locomotion Probe] 已启用原生逐帧探针")

    def find_local_anim_instances(self, world):
        results = []
        actors = unreal.GameplayStatics.get_all_actors_of_class(
            world,
            unreal.Character,
        )

        for actor in actors:
            try:
                if not actor.is_locally_controlled():
                    continue

                mesh = actor.get_component_by_class(unreal.SkeletalMeshComponent)
                if mesh is None:
                    continue

                anim_instance = mesh.get_anim_instance()
                if anim_instance is None:
                    continue

                results.append((actor, mesh, anim_instance))
            except Exception:
                continue

        return results

    def read_curves(self, anim_instance):
        result = {}

        for curve_name in (
            "DisableLegIK",
            "DisableFootLocking",
            "Distance",
            "Speed",
            "FootLock_L",
            "FootLock_R",
        ):
            try:
                result[curve_name] = float(
                    anim_instance.get_curve_value(curve_name),
                )
            except Exception:
                result[curve_name] = None

        return result

    def read_blueprint_state(self, anim_instance):
        return {
            "world_velocity": self.vector_to_dict(
                self.read_property(anim_instance, "worldVelocity"),
            ),
            "local_velocity_2d": self.vector_to_dict(
                self.read_property(anim_instance, "localVelocity2D"),
            ),
            "local_acceleration_2d": self.vector_to_dict(
                self.read_property(anim_instance, "localAcceleration2D"),
            ),
            "displacement_speed": self.to_float(
                self.read_property(anim_instance, "displacementSpeed"),
            ),
            "direction_angle": self.to_float(self.read_property(
                anim_instance,
                "localVelocityDirectionAngle",
            )),
            "has_velocity": self.read_property(anim_instance, "hasVelocity_0"),
            "has_acceleration": self.read_property(
                anim_instance,
                "hasAcceleration_0",
            ),
            "use_foot_placement": self.read_property(
                anim_instance,
                "useFootPlacement",
            ),
            "enable_control_rig": self.read_property(
                anim_instance,
                "enableControlRig",
            ),
        }

    def read_movement(self, actor, movement, actual_displacement_speed):
        return {
            "actor_location": self.vector_to_dict(actor.get_actor_location()),
            "actor_rotation": self.rotator_to_dict(actor.get_actor_rotation()),
            "control_rotation": self.rotator_to_dict(actor.get_control_rotation()),
            "velocity": self.vector_to_dict(movement.get_editor_property("velocity")),
            "current_acceleration": self.vector_to_dict(
                movement.get_current_acceleration(),
            ),
            "last_input_vector": self.vector_to_dict(
                movement.get_last_input_vector(),
            ),
            "actual_displacement_speed": actual_displacement_speed,
            "max_acceleration": movement.get_editor_property("max_acceleration"),
            "braking_deceleration": movement.get_editor_property(
                "braking_deceleration_walking",
            ),
            "ground_friction": movement.get_editor_property("ground_friction"),
            "braking_friction": movement.get_editor_property("braking_friction"),
            "braking_friction_factor": movement.get_editor_property(
                "braking_friction_factor",
            ),
            "orient_to_movement": movement.get_editor_property(
                "orient_rotation_to_movement",
            ),
            "controller_desired_rotation": movement.get_editor_property(
                "use_controller_desired_rotation",
            ),
            "controller_yaw": actor.get_editor_property(
                "use_controller_rotation_yaw",
            ),
        }

    def sample_pose(
        self,
        world,
        actor,
        mesh,
        anim_instance,
        state_name,
        movement,
    ):
        mesh_path = mesh.get_path_name()

        if mesh_path not in self.prepared_mesh_paths:
            self.original_mesh_tick_options[mesh_path] = (
                mesh,
                mesh.get_editor_property("visibility_based_anim_tick_option"),
            )
            mesh.set_editor_property(
                "visibility_based_anim_tick_option",
                unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES,
            )
            self.prepared_mesh_paths.add(mesh_path)

        world_time = float(unreal.SystemLibrary.get_game_time_in_seconds(world))
        actor_location = actor.get_actor_location()
        pelvis_location = mesh.get_socket_location("pelvis")
        left_foot_location = mesh.get_socket_location("foot_l")
        right_foot_location = mesh.get_socket_location("foot_r")
        pelvis_rotation = mesh.get_socket_rotation("pelvis")
        left_thigh_rotation = mesh.get_socket_rotation("thigh_l")
        right_thigh_rotation = mesh.get_socket_rotation("thigh_r")
        previous = self.previous_pose_samples.get(mesh_path)
        delta_seconds = 0.0
        actor_delta = unreal.Vector()
        left_foot_delta = unreal.Vector()
        right_foot_delta = unreal.Vector()

        if previous is not None:
            delta_seconds = world_time - previous["world_time"]
            actor_delta = actor_location - previous["actor"]
            left_foot_delta = left_foot_location - previous["left_foot"]
            right_foot_delta = right_foot_location - previous["right_foot"]

        actual_displacement_speed = self.vector_size_2d(actor_delta, delta_seconds)
        left_foot_world_speed = self.vector_size_2d(
            left_foot_delta,
            delta_seconds,
        )
        right_foot_world_speed = self.vector_size_2d(
            right_foot_delta,
            delta_seconds,
        )
        left_foot_mesh_relative_speed = self.vector_size_2d(
            left_foot_delta - actor_delta,
            delta_seconds,
        )
        right_foot_mesh_relative_speed = self.vector_size_2d(
            right_foot_delta - actor_delta,
            delta_seconds,
        )
        self.previous_pose_samples[mesh_path] = {
            "world_time": world_time,
            "actor": actor_location,
            "left_foot": left_foot_location,
            "right_foot": right_foot_location,
        }

        curves = self.read_curves(anim_instance)
        displacement_speed = self.to_float(
            self.read_property(anim_instance, "displacementSpeed"),
        )
        use_foot_placement = self.read_property(
            anim_instance,
            "useFootPlacement",
        )
        velocity = movement.get_editor_property("velocity")

        if self.feet_writer is not None:
            self.feet_writer.writerow({
                "frame": self.frame_index,
                "probe_time": round(time.time() - self.start_time, 6),
                "world_time": world_time,
                "state": state_name,
                "velocity_2d": math.hypot(velocity.x, velocity.y),
                "actual_displacement_speed": actual_displacement_speed,
                "anim_displacement_speed": displacement_speed,
                "actor_x": actor_location.x,
                "actor_y": actor_location.y,
                "actor_z": actor_location.z,
                "pelvis_x": pelvis_location.x,
                "pelvis_y": pelvis_location.y,
                "pelvis_z": pelvis_location.z,
                "foot_l_x": left_foot_location.x,
                "foot_l_y": left_foot_location.y,
                "foot_l_z": left_foot_location.z,
                "foot_r_x": right_foot_location.x,
                "foot_r_y": right_foot_location.y,
                "foot_r_z": right_foot_location.z,
                "foot_l_world_speed": left_foot_world_speed,
                "foot_r_world_speed": right_foot_world_speed,
                "foot_l_mesh_relative_speed": left_foot_mesh_relative_speed,
                "foot_r_mesh_relative_speed": right_foot_mesh_relative_speed,
                "disable_leg_ik": curves["DisableLegIK"],
                "disable_foot_locking": curves["DisableFootLocking"],
                "use_foot_placement": use_foot_placement,
            })

        return {
            "world_time": world_time,
            "pelvis": self.vector_to_dict(pelvis_location),
            "pelvis_rotation": self.rotator_to_dict(pelvis_rotation),
            "left_thigh_rotation": self.rotator_to_dict(left_thigh_rotation),
            "right_thigh_rotation": self.rotator_to_dict(right_thigh_rotation),
            "left_foot": self.vector_to_dict(left_foot_location),
            "right_foot": self.vector_to_dict(right_foot_location),
            "left_foot_world_speed": left_foot_world_speed,
            "right_foot_world_speed": right_foot_world_speed,
            "left_foot_mesh_relative_speed": left_foot_mesh_relative_speed,
            "right_foot_mesh_relative_speed": right_foot_mesh_relative_speed,
            "actual_displacement_speed": actual_displacement_speed,
        }

    def sample_anim_instance(self, world, actor, mesh, anim_instance):
        anim_path = anim_instance.get_path_name()
        runtime = json.loads(
            unreal.BBBBlueprintEditorLibrary.probe_character_animation_runtime(actor),
        )
        if runtime.get("status") != "ok":
            raise RuntimeError(f"角色动画原生快照失败 {runtime}")

        state_owner = runtime["mainInstance"]
        state_owner_path = state_owner.get("path", anim_path)
        states = state_owner.get("states", [])
        state_name = ""
        if states:
            state_name = states[0].get("state", "")
        previous_state = self.last_states.get(state_owner_path)
        state_changed = previous_state != state_name
        self.last_states[state_owner_path] = state_name
        movement = actor.get_component_by_class(
            unreal.CharacterMovementComponent,
        )
        pose = self.sample_pose(
            world,
            actor,
            mesh,
            anim_instance,
            state_name,
            movement,
        )
        record = {
            "event": "runtime_sample",
            "actor": actor.get_path_name(),
            "mesh": mesh.get_path_name(),
            "anim_instance": anim_path,
            "anim_class": anim_instance.get_class().get_path_name(),
            "state_owner": state_owner_path,
            "state_owner_class": state_owner.get("class", ""),
            "state": state_name,
            "state_changed": state_changed,
            "previous_state": previous_state,
            "movement": self.read_movement(
                actor,
                movement,
                pose["actual_displacement_speed"],
            ),
            "native_runtime": runtime,
            "camera": {
                "location": self.vector_to_dict(
                    unreal.GameplayStatics.get_player_camera_manager(world, 0).get_camera_location(),
                ),
                "rotation": self.rotator_to_dict(
                    unreal.GameplayStatics.get_player_camera_manager(world, 0).get_camera_rotation(),
                ),
            },
            "blueprint_state": self.read_blueprint_state(anim_instance),
            "pose": pose,
            "curves": self.read_curves(anim_instance),
        }
        self.write_record(record)

        if state_changed:
            unreal.log_warning(
                f"[BBB Runtime Locomotion Probe] 状态切换："
                f"{previous_state} -> {state_name}"
            )

    def tick(self, delta_seconds):
        self.frame_index += 1

        try:
            for world in self.get_pie_worlds():
                self.enable_runtime_logs(world)

                for actor, mesh, anim_instance in self.find_local_anim_instances(world):
                    self.sample_anim_instance(
                        world,
                        actor,
                        mesh,
                        anim_instance,
                    )
        except Exception:
            self.write_record({
                "event": "probe_error",
                "traceback": traceback.format_exc(),
            })
            unreal.log_error("[BBB Runtime Locomotion Probe] 采样失败")
            unreal.log_error(traceback.format_exc())

    @staticmethod
    def vector_size_2d(vector, delta_seconds):
        if delta_seconds <= 0.000001:
            return 0.0

        return math.hypot(vector.x, vector.y) / delta_seconds

    @staticmethod
    def vector_to_dict(value):
        if value is None:
            return None

        try:
            return {
                "x": float(value.x),
                "y": float(value.y),
                "z": float(value.z),
            }
        except Exception:
            return None

    @staticmethod
    def rotator_to_dict(value):
        if value is None:
            return None

        try:
            return {
                "pitch": float(value.pitch),
                "yaw": float(value.yaw),
                "roll": float(value.roll),
            }
        except Exception:
            return None

    @staticmethod
    def to_float(value):
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def read_property(target, *names):
        for name in names:
            try:
                return target.get_editor_property(name)
            except Exception:
                pass

            try:
                return getattr(target, name)
            except Exception:
                pass

        return None


def stop_existing_probe():
    existing_probe = getattr(builtins, "BBB_LOCOMOTION_SYNC_PROBE", None)
    if existing_probe is not None:
        try:
            existing_probe.stop()
        except Exception:
            pass


stop_existing_probe()

PROBE = BBBLocomotionSyncRuntimeProbe()
builtins.BBB_LOCOMOTION_SYNC_PROBE = PROBE
builtins.BBB_LOCOMOTION_SYNC_PROBE_STOP = PROBE.stop
PROBE.start()
