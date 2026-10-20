import copy
import hashlib
import json
from pathlib import Path
import ast
from functools import lru_cache
from MCP.mcp_result import object_path


INPUT_SHAPES = {
    'Vector3': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
    'Names': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 0},
    'Properties': {'type': 'object', 'additionalProperties': True},
    'StringMap': {'type': 'object', 'additionalProperties': {'type': 'string'}},
    'TransformEuler': {
        'type': 'object',
        'properties': {
            'location': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
            'rotation': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
            'scale': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
        },
        'required': ['location', 'rotation'],
        'additionalProperties': False,
    },
    'TransformQuaternion': {
        'type': 'object',
        'properties': {
            'position': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
            'rotation': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 4, 'maxItems': 4},
            'scale': {'type': 'array', 'items': {'type': 'number'}, 'minItems': 3, 'maxItems': 3},
        },
        'required': [],
        'additionalProperties': False,
    },
}


TOOL_POLICIES = {
    'hit.rebuild_zombie_debug_gore_cuts': {'scope': {'fields': ['output_folder']}, 'world': 'editor', 'completion': 'verified_save'},
    'control_rig.sample_post_process_rig': {'access': 'read', 'world': 'editor', 'completion': 'observed'},
    'control_rig.create_twist_driver': {'access': 'write', 'world': 'editor', 'scope': {'fields': ['asset_path']}, 'completion': 'verified_save'},
    'control_rig.audit_twist_driver': {'access': 'read', 'world': 'editor', 'completion': 'observed'},
    'control_rig.insert_post_process_rig': {'access': 'write', 'world': 'editor', 'scope': {'fields': ['main_path']}, 'completion': 'verified_save'},
    'hit.build_zombie_debug_gore_surface': {'scope': {'fields': ['output_folder']}, 'world': 'editor', 'completion': 'verified_save'},
    'hit.inspect_zombie_debug_gore_surface': {'access': 'read'},
    'hit.repack_zombie_debug_wound_atlas': {'scope': {'fields': ['output_folder']}, 'world': 'editor', 'completion': 'verified_save'},
    'grip.author_weapon': {'scope': {'fields': ['weapon_root']}, 'world': 'editor'},
    'grip.apply_action_recipe': {'scope': {'fields': ['weapon_root']}, 'world': 'editor', 'completion': 'verified_save'},
    'grip.sample_static_attachment_surface': {'access': 'read'},
    'editor.sample_skeletal_mesh_surface': {'access': 'read'},
    'editor.audit_hand_pose_layer': {'access': 'read', 'world': 'editor'},
    'editor.configure_hand_pose_layer': {'scope': {'fields': ['main_path', 'base_path', 'interface_path', 'child_layer_paths']}, 'completion': 'verified_save'},
    'editor.create_particle_surface_material': {'scope': {'fields': ['material_path']}},
    'editor.configure_niagara_parameters': {'scope': {'fields': ['system_path']}},
    'editor.configure_niagara_particle_stage': {'scope': {'fields': ['system_path']}},
    'editor.configure_niagara_burst_layer': {'scope': {'fields': ['system_path']}},
    'editor.inspect_niagara_parameters': {'access': 'read'},
    'editor.get_pie_view_recording_status': {'access': 'read'},
    'editor.record_pie_player_view': {'access': 'pie', 'world': 'pie', 'scope': {'kind': 'session'}, 'completion': 'activity'},
    'editor.configure_asset_properties': {'scope': {'fields': ['asset_path']}},
    'traversal.configure_pie_traversal_network': {'world': 'any'},
    'assets.delete_unreferenced_project_assets': {'scope': {'fields': ['asset_paths']}},
    'editor.configure_action_montage': {'scope': {'fields': ['asset_path']}},
    'editor.configure_animation_montage_selector': {'scope': {'fields': ['blueprint_path']}},
    'editor.spawn_pie_niagara_instances': {'access': 'pie', 'world': 'pie', 'scope': {'kind': 'session'}, 'completion': 'observed'},
    'assets.restore_missing_animation_notify_classes': {'scope': {'fields': ['asset_paths']}},
    'editor.audit_animation_library_batch': {'access': 'read', 'world': 'any'},
    'editor.clone_retargeter_for_source_mesh': {'scope': {'fields': ['source_rig_path', 'retargeter_path']}},
    'editor.import_animation_library_batch': {'scope': {'rows': ['requests', 'asset_path']}},
    'editor.set_pie_player_view': {'world': 'pie'},
    'editor.configure_data_asset': {'scope': {'fields': ['asset_path']}, 'completion': 'verified_save'},
    'editor.refresh_montage_links': {'scope': {'fields': ['asset_path']}, 'completion': 'verified_save'},
    'editor.inspect_pie_character_runtime': {'access': 'read', 'world': 'pie'},
    'editor.repair_blueprint_function_references': {'scope': {'fields': ['asset_path']}, 'completion': 'verified_save'},
    'editor.configure_boolean_pose_overlay': {'scope': {'fields': ['blueprint_path']}, 'completion': 'verified_save'},
    'animation.add_animation_layer_boolean_input': {'scope': {'fields': ['blueprint_path']}},
    'animation.apply_try_weapon_animation_fallbacks': {'scope': {'fields': ['blueprint_paths']}},
    'animation.bind_backward_recoil_additive_inputs': {'scope': {'fields': ['blueprint_path']}},
    'animation.build_weapon_animation_graph': {'scope': {'fields': ['blueprint_path']}},
    'animation.capture_animation_pose': {'world': 'pie'},
    'animation.capture_backward_recoil_alpha_samples': {'world': 'pie'},
    'animation.configure_character_rifle_actions': {'scope': {'fields': ['character_blueprint_path']}},
    'animation.configure_continuous_bone_rotation': {'scope': {'fields': ['blueprint_path']}},
    'animation.configure_control_rig_anim_graph_node': {'scope': {'fields': ['blueprint_path']}},
    'animation.configure_weapon_handling_graphs': {'scope': {'fields': ['blueprint_path']}},
    'animation.configure_weapon_recoil_animation_source': {'scope': {'fields': ['blueprint_path']}},
    'animation.copy_animation_skeleton_metadata': {'scope': {'fields': ['target_skeleton_path']}},
    'animation.create_animation_slice': {'scope': {'fields': ['destination_path']}},
    'animation.create_backward_additive_animation': {'scope': {'fields': ['destination_path']}},
    'animation.create_control_rig_anim_graph_node': {'scope': {'fields': ['blueprint_path']}},
    'animation.create_equipment_action_montages': {'scope': {'fields': ['target_paths']}},
    'animation.create_lyra_rifle_character_montages': {'scope': {'fields': ['target_root']}},
    'animation.create_rifle_magazine_reload_animation': {'scope': {'fields': ['animation_path', 'montage_path', 'definition_path']}},
    'animation.export_animation_blueprint_graphs': {'access': 'read'},
    'animation.get_pie_character_motion_capture_status': {'access': 'read'},
    'animation.get_pie_input_sequence_status': {'access': 'read'},
    'animation.get_pie_montage_motion_capture_status': {'access': 'read'},
    'animation.hold_animation_bone_tracks': {'scope': {'fields': ['animation_path']}},
    'animation.replace_animation_bone_tracks': {'scope': {'fields': ['animation_path']}},
    'animation.inspect_animation_bone_track_keys': {'access': 'read'},
    'animation.inspect_backward_recoil_context': {'access': 'read'},
    'animation.inspect_pie_arm_pose': {'access': 'read'},
    'animation.limit_hand_swing_tracks': {'scope': {'fields': ['animation_paths']}},
    'animation.merge_recoil_into_full_body_additives': {'scope': {'fields': ['interface_path', 'base_path', 'main_path', 'dependent_paths']}},
    'animation.migrate_animation_data_accesses': {'scope': {'fields': ['blueprint_paths']}},
    'animation.probe_animation_assets': {'access': 'read'},
    'animation.probe_animation_blueprint': {'access': 'read'},
    'animation.probe_animation_bone_trajectories': {'access': 'read'},
    'animation.probe_animation_component_poses': {'access': 'read'},
    'animation.probe_animation_instance_runtime': {'access': 'read'},
    'animation.probe_animation_property_access_paths': {'access': 'read'},
    'animation.probe_pie_character_animation_runtime': {'access': 'read'},
    'animation.probe_python_api': {'access': 'read'},
    'animation.rebind_animation_blueprint_interface': {'scope': {'fields': ['blueprint_path']}},
    'animation.rebuild_arm_twist_tracks': {'scope': {'fields': ['animation_paths']}},
    'animation.rebuild_backward_recoil_animation': {'scope': {'fields': ['animation_path']}},
    'animation.rebuild_blend_space_skeleton': {'scope': {'fields': ['blend_space_path']}},
    'animation.rebuild_ik_foot_tracks': {'scope': {'fields': ['animation_paths']}},
    'animation.remap_animation_blueprint_blend_profiles': {'scope': {'fields': ['blueprint_path']}},
    'animation.remap_animation_blueprint_class_references': {'scope': {'fields': ['blueprint_path']}},
    'animation.remap_animation_sequence_notify_classes': {'scope': {'fields': ['animation_path']}},
    'animation.rename_animation_blueprint_variables': {'scope': {'fields': ['blueprint_path']}},
    'animation.repair_main_anim_instance_accesses': {'scope': {'fields': ['blueprint_path']}},
    'animation.repair_raise_weapon_after_firing_transition': {'scope': {'fields': ['blueprint_path']}},
    'animation.replace_montage_animation_references': {'scope': {'fields': ['montage_path']}},
    'animation.restore_animation_from_source': {'scope': {'fields': ['destination_path']}},
    'animation.restore_lyra_stop_pose': {'scope': {'fields': ['blueprint_path']}},
    'animation.retarget_missing_animations': {'scope': {'fields': ['target_path']}},
    'animation.rewrite_animation_node_binding_paths': {'scope': {'fields': ['blueprint_path']}},
    'animation.rewrite_animation_property_access_paths': {'scope': {'fields': ['blueprint_paths']}},
    'animation.sample_backward_recoil_runtime': {'world': 'pie', 'input_rules': {'properties': {'action': {'type': 'string', 'enum': ['start', 'status']}}}},
    'animation.sample_weapon_handling_runtime': {'world': 'pie', 'input_rules': {'properties': {'action': {'type': 'string', 'enum': ['start', 'status', 'equip']}, 'seconds': {'minimum': 0, 'maximum': 60}}, 'if': {'properties': {'action': {'const': 'equip'}}, 'required': ['action']}, 'then': {'required': ['equipment_class_path'], 'properties': {'equipment_class_path': {'minLength': 1}}}}},
    'animation.set_animation_blueprint_preview_mesh': {'scope': {'fields': ['blueprint_path']}},
    'animation.set_animation_blueprint_skeletons': {'scope': {'fields': ['blueprint_paths']}},
    'animation.set_animation_folder_preview_meshes': {'scope': {'fields': ['folder_path']}},
    'animation.set_animation_sequence_preview_meshes': {'scope': {'fields': ['animation_paths']}},
    'animation.simplify_animation_data_accesses': {'scope': {'fields': ['blueprint_paths']}},
    'animation.start_locomotion_runtime_probe': {'world': 'pie'},
    'animation.stop_locomotion_runtime_probe': {'world': 'pie'},
    'animation.submit_character_diagnostic_inputs': {'world': 'pie'},
    'animation_graph.capture_monster_stagger_samples': {'world': 'pie'},
    'animation_graph.restore_character_directional_cycle': {'scope': {'fields': ['base_layer_path', 'child_layer_paths']}},
    'animation_graph.configure_character_downed_state': {'scope': {'fields': ['asset_path', 'interface_path', 'base_layer_path', 'child_layer_paths']}},
    'animation_graph.configure_character_rescue_state': {'scope': {'fields': ['asset_path', 'interface_path', 'base_layer_path', 'child_layer_paths']}},
    'animation_graph.create_mass_presentation_variant': {'scope': {'fields': ['destination_root']}},
    'animation_graph.inspect_mass_scene_population': {'access': 'read'},
    'animation_graph.inspect_mass_variation_network': {'access': 'read'},
    'animation_graph.prepare_in_place_cycles': {'scope': {'fields': ['asset_paths']}},
    'app.CaptureAssetImage': {'scope': {'kind': 'session'}},
    'app.CaptureEditorImage': {'scope': {'kind': 'session'}},
    'app.CaptureViewport': {'scope': {'kind': 'session'}},
    'app.FocusOnActors': {'scope': {'kind': 'session'}},
    'app.GetCameraTransform': {'access': 'read'},
    'app.GetContentBrowserPath': {'access': 'read'},
    'app.GetOpenAssets': {'access': 'read'},
    'app.GetSelectedActors': {'access': 'read'},
    'app.GetSelectedAssets': {'access': 'read'},
    'app.IsPIERunning': {'access': 'read'},
    'app.OpenEditorForAsset': {'scope': {'kind': 'session'}},
    'app.SelectActors': {'scope': {'kind': 'session'}},
    'app.SelectAssets': {'scope': {'kind': 'session'}},
    'app.SetCameraTransform': {'scope': {'kind': 'session'}},
    'app.SetContentBrowserPath': {'scope': {'kind': 'session'}},
    'asset.can_edit_asset': {'access': 'read'},
    'asset.create_folder': {'scope': {'fields': ['path']}},
    'asset.delete': {'scope': {'fields': ['path']}},
    'asset.duplicate': {'scope': {'fields': ['new_path']}},
    'asset.exists': {'access': 'read'},
    'asset.find_assets': {'access': 'read'},
    'asset.get_asset_class': {'access': 'read'},
    'asset.get_asset_tags': {'access': 'read'},
    'asset.get_dependencies': {'access': 'read'},
    'asset.get_referencers': {'access': 'read'},
    'asset.is_checked_out': {'access': 'read'},
    'asset.is_dirty': {'access': 'read'},
    'asset.list_folders': {'access': 'read'},
    'asset.move': {'scope': {'fields': ['path', 'new_path']}},
    'asset.save_assets': {'scope': {'fields': ['asset_paths']}},
    'asset.update_metadata_tags': {'scope': {'fields': ['asset_path']}},
    'assets.configure_monster_blood_residue': {'scope': {'fields': ['settings_path']}},
    'assets.create_missing_path_recovery_redirector': {'scope': {'fields': ['source_package']}},
    'assets.delete_asset_redirectors': {'scope': {'fields': ['asset_paths']}},
    'assets.delete_metadata_only_package': {'scope': {'fields': ['package_path']}},
    'assets.fixup_redirector_references_batch': {'scope': {'fields': ['referencer_paths']}},
    'assets.inspect_animation_access_errors': {'access': 'read'},
    'assets.inspect_asset_packages': {'access': 'read'},
    'assets.inspect_content_dependency_integrity': {'access': 'read'},
    'assets.inspect_external_actor_package_metadata': {'access': 'read'},
    'assets.inspect_external_actor_packages': {'access': 'read'},
    'assets.inspect_external_object_package_metadata': {'access': 'read'},
    'assets.inspect_foliage_base_cache': {'access': 'read'},
    'assets.inspect_loaded_package_soft_paths': {'access': 'read'},
    'assets.inspect_native_dependency_packages': {'access': 'read'},
    'assets.inspect_native_package_referencers': {'access': 'read'},
    'assets.inspect_package_objects': {'access': 'read'},
    'assets.inspect_physics_asset_material_bindings': {'access': 'read'},
    'assets.inspect_pose_asset_source_guids': {'access': 'read'},
    'assets.modernize_deprecated_blueprint_nodes': {'scope': {'fields': ['asset_path']}},
    'assets.normalize_material_auxiliary_data': {'scope': {'fields': ['asset_paths']}},
    'assets.refresh_asset_registry_folders': {'scope': {'fields': ['folder_paths']}},
    'assets.refresh_blueprint_reflection_metadata': {'scope': {'fields': ['asset_path']}},
    'assets.remap_missing_soft_object_paths': {'scope': {'fields': ['referencer_paths']}},
    'assets.remap_package_metadata_owner_paths': {'scope': {'fields': ['package_path']}},
    'assets.remove_unreferenced_loaded_redirectors': {'scope': {'fields': ['asset_paths']}},
    'assets.repair_animation_property_queries': {'scope': {'rows': ['operations', 'asset']}},
    'assets.repair_foliage_base_cache': {'scope': {'fields': ['world_package']}},
    'assets.repair_missing_animation_skeleton': {'scope': {'fields': ['asset_path']}},
    'assets.repair_pose_asset_source_guids': {'scope': {'rows': ['expected_reports', 'asset']}},
    'assets.resave_assets': {'scope': {'fields': ['asset_paths']}},
    'assets.update_pose_assets_from_source': {'scope': {'rows': ['expected_reports', 'asset']}},
    'blueprint.add_blueprint_comment_node': {'scope': {'fields': ['graph_path']}},
    'blueprint.create_blueprint_graph_node': {'scope': {'fields': ['graph_path']}},
    'blueprint.annotate_blueprint_graph': {'scope': {'fields': ['graph_path']}},
    'blueprint.configure_blueprint_function_thread_safety': {'scope': {'fields': ['blueprint_path']}},
    'blueprint.configure_control_rig_curve_alpha': {'scope': {'fields': ['blueprint_path']}},
    'blueprint.edit_blueprint_graph_comments': {'scope': {'fields': ['graph_path']}},
    'blueprint.inspect_blueprint_graph': {'access': 'read', 'input_rules': {'properties': {'view': {'type': 'string', 'enum': ['overview', 'logic', 'geometry'], 'default': 'overview'}, 'node_guids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 128, 'default': []}, 'offset': {'type': 'integer', 'minimum': 0, 'default': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 128, 'default': 40}, 'expected_snapshot': {'type': 'string', 'default': ''}}, 'if': {'properties': {'offset': {'minimum': 1}}, 'required': ['offset']}, 'then': {'required': ['expected_snapshot'], 'properties': {'expected_snapshot': {'minLength': 1}}}}},
    'blueprint.inspect_owned_objects': {'access': 'read'},
    'blueprint.optimize_blueprint_node_layout': {'scope': {'fields': ['graph_path']}},
    'blueprint.remove_blueprint_comment_node': {'scope': {'fields': ['graph_path']}},
    'blueprint.set_blueprint_node_positions': {'scope': {'fields': ['graph_path']}},
    'blueprint.write_graph': {'scope': {'fields': ['graph_path']}},
    'control_rig.add_pose_controls': {'scope': {'fields': ['asset_path']}},
    'control_rig.apply_baked_bone_deltas': {'scope': {'fields': ['baked_path']}},
    'control_rig.bake_control_rig_animation': {'scope': {'fields': ['animation_path']}},
    'control_rig.build_hand_retarget_sequences': {'scope': {'fields': ['write_paths']}},
    'control_rig.bake_hand_retarget_sequences': {'scope': {'fields': ['write_paths']}},
    'control_rig.build_pose_control_keys': {'scope': {'fields': ['animation_path']}},
    'control_rig.capture_attachment_pose': {'access': 'pie', 'world': 'pie', 'scope': {'kind': 'session'}},
    'control_rig.configure_control_rig_graph': {'scope': {'fields': ['asset_path']}},
    'control_rig.configure_sequence_animation_source': {'scope': {'fields': ['sequence_path']}},
    'control_rig.configure_sequence_attachment_animation': {'scope': {'fields': ['sequence_path']}},
    'control_rig.restore_sequence_fk_reference': {'scope': {'fields': ['sequence_path']}, 'world': 'editor', 'completion': 'verified_save'},
    'control_rig.configure_sequence_rig': {'scope': {'fields': ['sequence_path']}},
    'control_rig.convert_component_mesh_grips': {'scope': {'fields': ['mesh_path']}},
    'control_rig.create_attachment_preview_animation': {'scope': {'fields': ['destination_path']}},
    'control_rig.create_control_rig': {'scope': {'fields': ['asset_path']}},
    'control_rig.create_control_rig_sequence': {'scope': {'fields': ['sequence_path']}},
    'control_rig.create_sequence_attachment': {'scope': {'fields': ['sequence_path']}},
    'control_rig.inspect_authoring_api': {'access': 'read'},
    'control_rig.inspect_control_rig_controls': {'access': 'read'},
    'control_rig.inspect_control_rig_graph': {'access': 'read'},
    'control_rig.inspect_control_rig_reference': {'access': 'read'},
    'control_rig.inspect_mesh_bounds': {'access': 'read'},
    'control_rig.inspect_sequence_bindings': {'access': 'read'},
    'control_rig.normalize_authoring_bindings': {'scope': {'fields': ['sequence_path']}},
    'control_rig.prepare_animation_sequence': {'scope': {'fields': ['sequence_path']}},
    'control_rig.remap_animation_bone_times': {'scope': {'fields': ['animation_path']}},
    'control_rig.set_sequence_attachment_transform': {'scope': {'fields': ['sequence_path']}},
    'control_rig.set_sequence_spawn_range': {'scope': {'fields': ['sequence_path']}},
    'editor.add_animation_notify_events': {'scope': {'fields': ['asset_path']}},
    'editor.bind_niagara_channel_reader': {'scope': {'fields': ['system_path']}},
    'editor.capture_niagara_preview': {'world': 'pie'},
    'editor.configure_persistent_projectile_tracer': {'scope': {'fields': ['channel_path', 'system_path']}},
    'editor.configure_projectile_impact_system': {'scope': {'fields': ['channel_path', 'system_path', 'material_path']}},
    'editor.configure_projectile_tracer_finish': {'scope': {'fields': ['channel_path', 'system_path']}},
    'editor.configure_static_mesh_surface_collision': {'scope': {'fields': ['mesh_path']}},
    'editor.create_animation_set_retargeter': {'scope': {'fields': ['source_rig_path', 'retargeter_path']}},
    'editor.create_asset_with_factory': {'scope': {'fields': ['asset_path']}},
    'editor.create_monster_director_assets': {'scope': {'fields': ['asset_paths']}},
    'editor.validate_monster_director_assets': {'access': 'read'},
    'editor.run_automation_tests': {'access': 'pie'},
    'editor.create_channel_sprite_system': {'scope': {'fields': ['channel_path', 'system_path']}},
    'editor.create_primitive_texture_blend_material': {'scope': {'fields': ['material_path']}},
    'editor.create_projectile_sprite_material': {'scope': {'fields': ['material_path']}},
    'editor.create_static_mesh_grid_graph': {'scope': {'fields': ['graph_path']}},
    'editor.create_static_mesh_points_graph': {'scope': {'fields': ['graph_path']}},
    'editor.frame_texture_thumbnails': {'scope': {'fields': ['asset_paths']}},
    'editor.get_niagara_capture_status': {'access': 'read'},
    'editor.import_animation_fbx': {'scope': {'fields': ['asset_path']}},
    'editor.import_files_from_directory': {'scope': {'fields': ['destination_path']}},
    'editor.import_skeletal_animation_set': {'scope': {'fields': ['destination_path']}},
    'editor.inspect_animation_float_curves': {'access': 'read'},
    'editor.inspect_animation_montage_segments': {'access': 'read'},
    'editor.inspect_animation_notifies': {'access': 'read'},
    'editor.inspect_animation_notify_properties': {'access': 'read'},
    'editor.inspect_asset_properties': {'access': 'read'},
    'editor.inspect_blueprint_class_defaults': {'access': 'read'},
    'editor.inspect_control_rig_graphs': {'access': 'read'},
    'editor.inspect_dirty_packages': {'access': 'read'},
    'editor.inspect_material_statistics': {'access': 'read'},
    'editor.inspect_niagara_graphs': {'access': 'read'},
    'editor.inspect_pie_actor_properties': {'access': 'read'},
    'editor.inspect_pie_actor_skeletal_bones': {'access': 'read'},
    'editor.inspect_pie_bone_alignment': {'access': 'read'},
    'editor.inspect_pie_characters': {'access': 'read'},
    'editor.inspect_pie_hand_attachments': {'access': 'read'},
    'editor.inspect_pie_niagara_system': {'access': 'read'},
    'editor.inspect_pie_player_control': {'access': 'read'},
    'editor.inspect_pie_static_mesh_instances': {'access': 'read'},
    'editor.inspect_skeletal_mesh_skinning': {'access': 'read'},
    'editor.inspect_sound_assets': {'access': 'read'},
    'editor.inspect_static_mesh_bounds': {'access': 'read'},
    'editor.invoke_pie_object_function': {'summary': '调用所属 PIE 世界对象的反射函数'},
    'editor.move_animation_notify_event': {'scope': {'fields': ['asset_path']}},
    'editor.probe_pie_character_ground_contacts': {'access': 'read'},
    'editor.refresh_material_instances': {'scope': {'fields': ['asset_paths']}},
    'editor.reimport_texture': {'scope': {'fields': ['asset_path']}},
    'editor.reload_assets_from_disk': {'scope': {'fields': ['asset_paths']}},
    'editor.remove_empty_animation_notify_track': {'scope': {'fields': ['asset_path']}},
    'editor.remove_input_action_mappings': {'scope': {'fields': ['mapping_context_path']}},
    'editor.replace_animation_float_curve': {'scope': {'fields': ['asset_path']}},
    'editor.replace_animation_notify_track': {'scope': {'fields': ['asset_path']}},
    'editor.resave_asset': {'scope': {'fields': ['asset_path']}},
    'editor.retime_single_action_montage': {'scope': {'fields': ['asset_path']}},
    'editor.set_asset_object_property': {'scope': {'fields': ['asset_path']}},
    'editor.set_asset_transform_property': {'scope': {'fields': ['asset_path']}},
    'editor.set_blueprint_class_defaults': {'scope': {'fields': ['asset_path']}},
    'editor.set_instanced_struct_array': {'scope': {'fields': ['asset_path']}},
    'editor.set_niagara_channel_reader_frame_mode': {'scope': {'fields': ['system_path']}},
    'editor.set_niagara_pin_default': {'scope': {'fields': ['system_path']}},
    'editor.set_niagara_spawn_update_mode': {'scope': {'fields': ['system_path']}},
    'editor.set_struct_array_object': {'scope': {'fields': ['object_path']}},
    'external.animation.find_socket': {'access': 'read'},
    'external.animation.get_anim_sequence_info': {'access': 'read'},
    'external.animation.get_skeletal_mesh_info': {'access': 'read'},
    'external.animation.get_skeleton_info': {'access': 'read'},
    'external.animation.list_curves': {'access': 'read'},
    'external.animation.list_notifies': {'access': 'read'},
    'external.animation.list_notify_tracks': {'access': 'read'},
    'external.animation.list_sockets': {'access': 'read'},
    'external.animation.list_sync_markers': {'access': 'read'},
    'external.control_rig.get_control_rig_info': {'access': 'read'},
    'external.data_table.does_row_exist': {'access': 'read'},
    'external.data_table.get_column_names': {'access': 'read'},
    'external.data_table.get_row_names': {'access': 'read'},
    'external.data_table.get_rows_as_json': {'access': 'read'},
    'external.data_table.replace_rows': {'scope': {'fields': ['asset_path']}},
    'external.editor.close_asset_editor': {'scope': {'kind': 'session'}},
    'external.editor.get_open_assets': {'access': 'read'},
    'external.editor.get_selected_assets': {'access': 'read'},
    'external.editor.open_editor_for_asset': {'scope': {'kind': 'session'}},
    'external.game.add_input_action': {'scope': {'fields': ['asset_path']}},
    'external.game.add_input_mapping': {'scope': {'fields': ['mapping_context_path']}},
    'external.layer.get_actors_in_layer': {'access': 'read'},
    'external.layer.list_layers': {'access': 'read'},
    'external.level.get_current_level_path': {'access': 'read'},
    'external.level.list_level_actors': {'access': 'read'},
    'external.level_sequence.close_sequencer': {'scope': {'kind': 'session'}},
    'external.level_sequence.get_sequence_info': {'access': 'read'},
    'external.level_sequence.open_in_sequencer': {'scope': {'kind': 'session'}},
    'external.retarget.get_ik_rig_info': {'access': 'read'},
    'external.util.get_cvar': {'access': 'read'},
    'external.util.get_output_log': {'access': 'read'},
    'external.util.get_project_info': {'access': 'read'},
    'external.util.get_viewport_camera': {'access': 'read'},
    'external.util.is_in_pie': {'access': 'read'},
    'external.util.list_class_properties': {'access': 'read'},
    'external.util.list_enum_values': {'access': 'read'},
    'external.util.print_message': {'scope': {'kind': 'session'}},
    'external.util.set_cvar': {'scope': {'kind': 'session'}},
    'external.util.set_log_verbosity': {'scope': {'kind': 'session'}},
    'hit.inspect_blood_residue': {'access': 'read'},
    'hit.inspect_physics_asset_constraints': {'access': 'read'},
    'hit.inspect_pie_audio_device': {'access': 'read'},
    'hit.inspect_player_weapon_hit_state': {'access': 'read'},
    'hit.inspect_skeletal_hit_reaction_capture': {'access': 'read'},
    'hit.inspect_skeletal_physics_state': {'access': 'read'},
    'hit.inspect_zombie_gib_presentation': {'access': 'read'},
    'hit.normalize_zombie_gib_material_bindings': {'scope': {'fields': ['mesh_paths']}},
    'hit.preview_blood_residue': {'world': 'pie'},
    'hit.spawn_inspection_projectile': {'world': 'pie'},
    'hit.spawn_mass_hit_acceptance_population': {'world': 'pie'},
    'hit.start_blood_residue_capture': {'world': 'pie'},
    'hit.start_player_weapon_hit_capture': {'world': 'pie'},
    'hit.start_skeletal_hit_reaction_capture': {'world': 'pie'},
    'hud.set_input_action_keys': {'scope': {'fields': ['mapping_context_path']}},
    'logs_toolset.SetVerbosity': {'scope': {'kind': 'session'}},
    'melee.inspect_melee_sources': {'access': 'read'},
    'melee.inspect_upper_body_mask': {'access': 'read'},
    'object.get_class': {'access': 'read'},
    'object.get_properties': {'access': 'read'},
    'object.list_properties': {'access': 'read', 'input_rules': {'properties': {'query': {'type': 'string', 'default': ''}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 128, 'default': 24}, 'offset': {'type': 'integer', 'minimum': 0, 'default': 0}, 'expected_version': {'type': 'string', 'default': ''}}, 'if': {'required': ['offset'], 'properties': {'offset': {'minimum': 1}}}, 'then': {'required': ['expected_version'], 'properties': {'expected_version': {'minLength': 1}}}}},
    'object.search_subclasses': {'access': 'read'},
    'preview.inspect_animation_transition_capture': {'access': 'read'},
    'preview.inspect_mass_population_benchmark': {'access': 'read'},
    'retarget.inspect_animation_poses': {'access': 'read'},
    'retarget.inspect_retargeter': {'access': 'read'},
    'rigid.inspect_reference_attachment': {'access': 'read'},
    'rigid.inspect_static_mesh_geometry': {'access': 'read'},
    'runtime.configure_mcp_resources': {'input_rules': {'properties': {'profile': {'enum': ['HighThroughput', 'Balanced', 'Economy', 'GamingBackground'], 'description': '宿主资源档位'}}}},
    'runtime.inspect_mcp_dependencies': {'access': 'read'},
    'runtime.inspect_mcp_resources': {'access': 'read'},
    'traversal.configure_character_movement_input': {'scope': {'fields': ['main_path']}},
    'traversal.configure_character_traversal_exits': {'scope': {'fields': ['main_path']}},
    'traversal.configure_character_traversal_state': {'scope': {'fields': ['main_path', 'interface_path', 'base_path', 'child_paths']}},
    'traversal.configure_traversal_contact_points': {'scope': {'rows': ['points', 'montage']}},
    'traversal.configure_traversal_montages': {'scope': {'fields': ['destination_paths']}},
    'traversal.get_pie_traversal_samples': {'access': 'read'},
    'traversal.inspect_pie_traversal_contact_points': {'access': 'read'},
    'traversal.inspect_pie_traversal_network': {'access': 'read'},
    'traversal.inspect_traversal_editing_schema': {'access': 'read'},
    'traversal.inspect_traversal_montage_windows': {'access': 'read'},
    'animation.set_animation_asset_preview_meshes': {'scope': {'fields': ['asset_root']}},
    'animation.replace_lyra_animation_references': {'scope': {'fields': ['source_root', 'target_root'], 'referencers': True}},
    'animation.clean_retargeted_animation_dependencies': {'scope': {'fields': ['root_path', 'compression_target_path']}},
    'animation.finalize_animation_runtime_assets': {'scope': {'fields': ['notify_source_paths', 'notify_target_paths', 'rebuild_animation_paths']}},
    'editor.migrate_actor_blueprint': {'scope': {'fields': ['source_path', 'destination_path', 'level_paths'], 'referencers': True}},
    'editor.spawn_static_mesh_batch': {'scope': {'fields': ['expected_level']}},
    'editor.remove_scene_mesh_actors': {'scope': {'fields': ['expected_level', 'actor_paths']}},
    'editor.set_scene_actor_collision': {'scope': {'fields': ['expected_level', 'actor_paths']}},
    'editor.generate_and_inspect_pcg': {'scope': {'fields': ['actor_path', 'expected_level']}},
    'editor.duplicate_loaded_actors_to_current_level': {'scope': {'fields': ['actor_paths']}},
    'editor.reimport_sound_waves': {'scope': {'fields': ['destination_path']}},
    'level.break_level_instance_to_current_level': {'scope': {'fields': ['level_instance_path']}},
    'scene.remove_from_scene': {'scope': {'fields': ['actor']}},
    'level.configure_mass_display_spawners': {'scope': {'fields': ['expected_level']}},
    'rigid.configure_rigid_blueprint_part': {'scope': {'fields': ['leader_node_path', 'slot_node_path']}},
    'assets.delete_unreferenced_asset_packages': {'scope': {'fields': ['asset_paths']}},
    'assets.rebuild_loaded_actor_construction': {'scope': {'fields': ['actor_paths']}},
    'assets.clean_unreferenced_redirectors_in_folder': {'scope': {'fields': ['folder_path']}},
    'assets.make_current_editor_level_explicit': {'scope': {'fields': ['expected_package']}},
    'assets.move_partitioned_world': {'scope': {'fields': ['source_package', 'destination_package']}},
    'assets.fixup_external_actor_redirector_references': {'scope': {'fields': ['asset_paths', 'referencer_paths']}},
    'assets.fixup_redirector_references': {'scope': {'fields': ['asset_paths'], 'referencers': True}},
    'assets.delete_ownerless_external_object_packages': {'scope': {'fields': ['package_paths']}},
    'assets.delete_ownerless_external_actor_packages': {'scope': {'fields': ['package_paths']}},
    'animation_graph.configure_actor_animation_blueprint': {'scope': {'fields': ['actor_blueprint_path']}},
    'hit.rebuild_zombie_wound_cut_geometry': {'scope': {'fields': ['mesh_paths']}},
    'hit.finalize_zombie_wound_material_masks': {'scope': {'fields': ['material_paths']}},
    'hit.bake_zombie_wound_presentation_set': {'scope': {'fields': ['body_mesh_path', 'definition_path', 'output_folder']}},
    'hit.create_zombie_sealed_part_meshes': {'scope': {'fields': ['output_folder']}},
    'hit.configure_monster_severing_parts': {'scope': {'fields': ['definition_path']}},
    'hit.create_blood_residue_material': {'scope': {'fields': ['material_path']}},
    'hit.rebuild_monster_blood_system': {'scope': {'fields': ['channel_path', 'system_path', 'spray_material_path', 'splash_material_path', 'mist_material_path']}},
    'melee.stage_upper_body_blend': {'scope': {'fields': ['blueprint_path']}},
    'melee.register_melee_equipment': {'scope': {'fields': ['catalog_path']}},
    'melee.create_melee_equipment': {'scope': {'fields': ['definition_path', 'blueprint_path', 'animation_blueprint_path', 'character_layer_path', 'catalog_path']}},
    'melee.create_melee_attack': {'scope': {'fields': ['sequence_path', 'montage_path']}},
    'melee.create_rigid_equipment_mesh': {'scope': {'fields': ['mesh_path']}},
    'melee.stage_character_aim_gate': {'scope': {'fields': ['blueprint_path', 'node_path']}},
    'retarget.retarget_sequences': {'scope': {'fields': ['target_folder']}},
    'external.retarget.add_retarget_chain': {'scope': {'fields': ['ik_rig_path']}},
    'external.retarget.auto_map_chains': {'scope': {'fields': ['retargeter_path']}},
    'retarget.open_new_assets_for_add': {'scope': {'fields': ['asset_paths']}},
    'hud.render_mesh_silhouettes': {'scope': {'kind': 'session'}},
    'editor.capture_niagara_asset': {'access': 'pie', 'world': 'pie', 'scope': {'kind': 'session'}},
    'editor.render_asset_thumbnails': {'scope': {'kind': 'session'}},
    'editor.capture_editor_screenshot': {'scope': {'kind': 'session'}},
    'editor.dispatch_slate_key': {'scope': {'kind': 'session'}},
    'editor.activate_slate_button': {'scope': {'kind': 'session'}},
    'control_rig.inspect_sequence_pose': {'scope': {'kind': 'session'}},
    'control_rig.compute_attachment_contacts': {'scope': {'kind': 'session'}},
    'control_rig.sample_animation_poses': {'scope': {'kind': 'session'}},
    'control_rig.set_background_budget': {'scope': {'kind': 'session'}},
    'control_rig.compute_palm_contact': {'scope': {'kind': 'session'}},
    'control_rig.sample_sequence_controls': {'scope': {'kind': 'session'}},
    'hit.run_monster_hit_reaction_regressions': {'scope': {'kind': 'session'}},
    'editor.rebind_asset_import_sources': {'scope': {'rows': ['requests', 'asset']}},
    'editor.import_font_faces': {'scope': {'rows': ['requests', 'destination']}},
    'assets.delete_unreferenced_uncontrolled_assets': {'scope': {'rows': ['expected_files', 'package']}},
    'assets.move_assets_preserving_external_actor_references': {'scope': {'rows': ['moves', ['source', 'destination']], 'referencers': True}},
    'assets.move_assets_batch': {'scope': {'rows': ['moves', ['source', 'destination']], 'referencers': True}},
    'assets.consolidate_verified_asset_copies': {'scope': {'rows': ['moves', ['source', 'destination']], 'referencers': True}},
    'hit.plan_zombie_wound_presentation_set': {'access': 'read'},
    'editor.configure_right_hand_grip_rotation': {'scope': {'fields': ['base_path', 'child_layer_paths', 'main_path']}, 'completion': 'verified_save'},
    'editor.sample_hand_handling_surface': {'access': 'read'},
    'editor.reparent_skeletal_mesh_socket': {'scope': {'fields': ['mesh_path']}, 'world': 'editor', 'completion': 'verified_save'},
    'control_rig.replace_sequence_animation_references': {'scope': {'fields': ['sequence_path']}},
}

@lru_cache(maxsize=None)
def source_inputs(definition):
    """/** @param definition\t领域模块 @return 同源结构化输入定义 */"""
    path = Path(__file__).resolve().parents[1] / (definition + ".py")
    if not path.is_file():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MCP_INPUTS" for target in node.targets):
            return ast.literal_eval(node.value)
    return {}


def expand_input_shape(schema):
    """/** @param schema\t同源输入结构 @return 内联当前参数需要的类型 */"""
    if isinstance(schema, dict):
        if "$ref" in schema:
            return expand_input_shape(INPUT_SHAPES[schema["$ref"].rsplit("/", 1)[-1]])
        return {key: expand_input_shape(value) for key, value in schema.items()}
    if isinstance(schema, list):
        return [expand_input_shape(value) for value in schema]
    return schema


def compile_contract(contract):
    """/** @param contract\t实际注册描述 @return 用于发现 校验 范围与调用的唯一契约 */"""
    item = copy.deepcopy(contract)
    policy = TOOL_POLICIES.get(item["id"], {})
    item.update(copy.deepcopy(policy))
    item.setdefault("scope", {})
    parameters = item["parameters"]
    properties = parameters.setdefault("properties", {})
    if not item["scope"]:
        roles = {
            "ObjectTools": ("instance",), "BlueprintTools": ("blueprint", "graph", "node", "nodes", "pin", "input_pin", "output_pin", "component"),
            "ControlRigTools": ("control_rig",), "SequencerTools": ("sequence",),
            "MaterialTools": ("material", "material_or_function", "expression", "to_expression", "from_expression"),
            "MaterialInstanceTools": ("instance",), "CurveTableTools": ("curve_table",), "DataTableTools": ("data_table",),
            "SkeletalMeshTools": ("mesh",), "StaticMeshTools": ("mesh",), "StringTableTools": ("string_table",),
        }
        fields = [field for field in roles.get(item["definition"], ()) if field in properties]
        if fields:
            item["scope"] = {"fields": fields}
        if item["definition"] in {"ActorTools", "LevelTools", "LandscapeTools", "FoliageTools"}:
            item["scope"] = {"kind": "world"}
            paths = [field for field in ("level_path", "map_path", "expected_level") if field in properties]
            if paths:
                item["scope"] = {"fields": paths}
        if item["id"].startswith(("external.actor.", "external.light.", "external.level.", "external.layer.")) and item["access"] != "read":
            item["scope"] = {"kind": "world"}
            if "level_path" in properties:
                item["scope"] = {"fields": ["level_path"]}
        if "folder_path" in properties and "asset_name" in properties and item["access"] != "read":
            item["scope"] = {"join": ["folder_path", "asset_name"]}
            if item["name"] == "import_file":
                item["scope"] = {"fields": ["folder_path"]}
        if item["definition"].startswith("BBB") and "asset_path" in properties and item["access"] != "read" and not item.get("action"):
            item["scope"] = {"fields": ["asset_path"]}
        if item.get("action") and "asset_path" in properties and item["access"] != "read":
            item["scope"] = {"fields": ["asset_path"]}
    required = parameters.setdefault("required", [])
    codecs = {}
    shapes = source_inputs(item["definition"]).get(item["name"], {})
    if item["id"] == "object.set_properties":
        shapes = {"values": {"type": "object", "additionalProperties": True}}
    if item["id"] == "data_table.set_rows":
        shapes = {"values": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": True}}}
    for name, original in list(properties.items()):
        if name.endswith("_json") or name in shapes:
            public = name.removesuffix("_json")
            if name not in shapes:
                raise ValueError("STRUCTURED_CONTRACT_REQUIRED: " + item["id"] + "/" + name)
            field = expand_input_shape(shapes[name])
            if "default" in original:
                default = original["default"]
                field["default"] = json.loads(default) if isinstance(default, str) and default else default
                if default == "":
                    field["default"] = [] if field.get("type") == "array" else {}
            properties.pop(name)
            properties[public] = field
            codecs[public] = {"field": name, "encoding": "json"}
            if original.get("default") == "":
                codecs[public]["empty"] = field["default"]
            required = [public if key == name else key for key in required]
            continue
        if original.get("properties", {}).get("refPath") is not None:
            properties[name] = {"type": "string", "minLength": 1}
            if "default" in original:
                properties[name] = {"anyOf": [properties[name], {"type": "null"}], "default": original["default"]}
            codecs[name] = {"field": name, "encoding": "reference"}
        if original.get("items", {}).get("properties", {}).get("refPath") is not None:
            properties[name] = {"type": "array", "items": {"type": "string", "minLength": 1}}
            if "default" in original:
                properties[name]["default"] = original["default"]
            codecs[name] = {"field": name, "encoding": "references"}
        if original.get("default", False) is None and original.get("type") is not None and original.get("type") != "null" and "anyOf" not in properties[name]:
            properties[name] = {"anyOf": [properties[name], {"type": "null"}], "default": None}
    parameters["required"] = [name for name in required if "default" not in properties[name]]
    rules = policy.get("input_rules", {})
    for name, field in rules.get("properties", {}).items():
        properties.setdefault(name, {}).update(copy.deepcopy(field))
    parameters.update({key: copy.deepcopy(value) for key, value in rules.items() if key != "properties"})
    item["codecs"] = codecs
    item["completion"] = {"read": "observed", "write": "verified_save", "pie": "activity"}[item["access"]]
    item["version"] = hashlib.sha256(json.dumps({key: item[key] for key in ("id", "parameters", "access", "world", "scope", "completion")}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    return item


def backend_arguments(contract, arguments):
    """/** @param contract\t唯一契约 @param arguments\t结构化参数 @return 原生传输参数 */"""
    result = copy.deepcopy(arguments)
    for public, codec in contract.get("codecs", {}).items():
        if public in result:
            value = result.pop(public)
            if codec["encoding"] == "reference":
                result[codec["field"]] = {"refPath": object_path(value)} if value is not None else None
            if codec["encoding"] == "references":
                result[codec["field"]] = [{"refPath": object_path(path)} for path in value]
            if codec["encoding"] == "json":
                result[codec["field"]] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            if "empty" in codec and value == codec["empty"]:
                result[codec["field"]] = ""
    return result


def default_arguments(contract, arguments):
    """/** @param contract\t唯一契约 @param arguments\t显式参数 @return 完整调用参数 */"""
    result = copy.deepcopy(arguments)
    for name, field in contract["parameters"].get("properties", {}).items():
        if name not in result and "default" in field:
            result[name] = copy.deepcopy(field["default"])
    return result
