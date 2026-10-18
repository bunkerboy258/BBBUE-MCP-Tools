import ast
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid


class SequenceAuditTests(unittest.TestCase):
    """/** 验证审计只使用瞬态副本且失败时清理自身对象 */"""

    def fixture(self, folder):
        source_path = Path(__file__).resolve().parents[1] / "Scripts/BBBControlRigAuthoringToolset.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
        names = {"export_sequence_pose_audit", "_sequence_audit_report_path", "_validate_sequence_audit_spawn"}
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
        for function in functions:
            function.decorator_list = []

        state = SimpleNamespace(registry={}, copied=[], exported=[], purged=[], collected=0, fail_export=False, fail_pose=False, retain=False)
        skeleton = object()

        class Asset:
            def __init__(self, name):
                self.name = name
                self.sequence_length = 1.0
                self.controller = SimpleNamespace(remove_all_bone_tracks=Mock())

            def get_path_name(self):
                return self.name

            def get_outermost(self):
                return SimpleNamespace(get_path_name=lambda: "/Engine/Transient")

            def get_editor_property(self, key):
                return skeleton

            def get_playback_start(self):
                return 0

            def get_playback_end(self):
                return 30

        class Sequence(Asset):
            pass

        class Animation(Asset):
            pass

        class Mesh(Asset):
            pass

        source = Animation("/Game/Source")
        sequence = Sequence("/Game/Sequence")
        mesh = Mesh("/Game/Mesh")
        channel = SimpleNamespace(get_default=lambda: True, get_keys=lambda: [])
        section = SimpleNamespace(is_active=lambda: True, get_start_frame=lambda: 0,
                                  get_end_frame=lambda: 30, get_all_channels=lambda: [channel])
        track = SimpleNamespace(get_sections=lambda: [section])
        binding = SimpleNamespace(find_tracks_by_type=Mock(return_value=[track]))
        assets = {source.name: source, sequence.name: sequence, mesh.name: mesh}

        def new_object(kind, name):
            if kind is Asset:
                raise RuntimeError("Class Object is abstract")

            self.assertIs(kind, Sequence)
            scope = kind("/Engine/Transient." + name)
            state.registry[scope.name] = scope
            return scope

        def duplicate(asset, scope, name):
            copy = type(asset)(scope.name + ":" + name)
            state.copied.append((asset, copy))
            state.registry[copy.name] = copy
            return copy

        def export(world, seq, animation, options, actual_binding, link):
            state.exported.append((seq, animation, link))
            return not state.fail_export

        def collect():
            state.collected += 1
            if not state.retain:
                state.registry.clear()

        def pose(animation, mesh, time):
            if state.fail_pose:
                raise RuntimeError("pose failed")

            return animation

        transform = SimpleNamespace(translation=SimpleNamespace(__sub__=None),
                                    rotation=SimpleNamespace(x=0, y=0, z=0, w=1))

        class Position:
            def __sub__(self, other):
                return self

            def length(self):
                return 0.0

        transform.translation = Position()
        engine = SimpleNamespace(
            Object=Asset, LevelSequence=Sequence, AnimSequence=Animation, SkeletalMesh=Mesh,
            MovieSceneSpawnTrack=object, UnrealEditorSubsystem=object,
            Paths=SimpleNamespace(project_saved_dir=lambda: folder),
            SystemLibrary=SimpleNamespace(duplicate_object=duplicate), new_object=new_object,
            get_editor_subsystem=lambda kind: SimpleNamespace(get_editor_world=lambda: object()),
            AnimSeqExportOption=SimpleNamespace,
            SequencerTools=SimpleNamespace(export_anim_sequence=export),
            AnimPoseSpaces=SimpleNamespace(LOCAL=object()),
            AnimPoseExtensions=SimpleNamespace(get_bone_names=lambda pose: ["hand_l"],
                                               get_bone_pose=lambda *args: transform),
            purge_object_references=lambda obj, inners: state.purged.append((obj.name, inners)),
            collect_garbage=collect, find_object=lambda outer, name: state.registry.get(name), log=Mock(), log_warning=Mock(),
        )
        namespace = {"unreal": engine, "json": json, "os": os, "math": math, "uuid": uuid,
                     "_asset": lambda path, kind: assets[path], "_pose": pose,
                     "_mesh_binding": lambda seq, actual_mesh: binding}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source_path), "exec"), namespace)
        state.engine = engine
        state.binding = binding
        state.sequence = sequence
        state.source = source
        state.channel = channel
        return lambda times=[0.0, 1.0], name="Audit.json": namespace["export_sequence_pose_audit"](
            sequence.name, source.name, mesh.name, times, name), state

    def test_success_exports_only_copies_and_releases_them(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            result = json.loads(audit())
            self.assertTrue(result["transientObjectsReleased"])
            self.assertEqual(state.registry, {})
            self.assertEqual(len(state.purged), 1)
            self.assertIsNot(state.exported[0][0], state.sequence)
            self.assertIsNot(state.exported[0][1], state.source)
            self.assertFalse(state.exported[0][2])
            state.source.controller.remove_all_bone_tracks.assert_not_called()
            self.assertEqual(Path(result["report"]), Path(folder) / "temp/Audit/Audit.json")
            self.assertEqual(json.loads(Path(result["report"]).read_text())["storage"], "transient_only")

    def test_missing_spawn_track_fails_before_duplication(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            state.binding.find_tracks_by_type.return_value = []
            with self.assertRaisesRegex(RuntimeError, "已有唯一生成轨"):
                audit()
            self.assertEqual(state.copied, [])
            self.assertEqual(state.exported, [])

    def test_export_failure_still_releases_every_temporary_object(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            state.fail_export = True
            with self.assertRaisesRegex(RuntimeError, "瞬态烘焙失败"):
                audit()
            self.assertEqual(state.registry, {})
            self.assertFalse((Path(folder) / "temp").exists())

    def test_pose_failure_still_releases_and_does_not_write_report(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            state.fail_pose = True
            with self.assertRaisesRegex(RuntimeError, "pose failed"):
                audit()
            self.assertEqual(state.registry, {})
            self.assertFalse((Path(folder) / "temp").exists())

    def test_engine_retained_transients_are_reported_pending_host_shutdown(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            state.retain = True
            result = json.loads(audit())
            report = json.loads(Path(result["report"]).read_text())
            self.assertFalse(result["transientObjectsReleased"])
            self.assertEqual(result["cleanup"]["state"], "pending_host_shutdown")
            self.assertEqual(set(result["cleanup"]["retained"]), set(state.registry))
            self.assertEqual(report["cleanup"], result["cleanup"])
            self.assertEqual(report["storage"], "transient_only")
            state.engine.log_warning.assert_called_once()

    def test_existing_report_is_preserved(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            report = Path(folder) / "temp/Audit/Audit.json"
            report.parent.mkdir(parents=True)
            report.write_text("existing")
            with self.assertRaisesRegex(RuntimeError, "禁止覆盖"):
                audit()
            self.assertEqual(report.read_text(), "existing")
            self.assertEqual(state.copied, [])

    def test_invalid_names_and_times_fail_before_duplication(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            for name in ["../Audit.json", "a/b.json", "x:Audit.json", ".json", "Audit.txt"]:
                with self.subTest(name=name), self.assertRaises(RuntimeError):
                    audit(name=name)
            for times in [[], [-1.0], [float("nan")], [float("inf")], [2.0]]:
                with self.subTest(times=times), self.assertRaises(RuntimeError):
                    audit(times=times)
            self.assertEqual(state.copied, [])

    def test_duplicate_failure_releases_scope_without_fallback(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            state.engine.SystemLibrary.duplicate_object = lambda *args: None
            with self.assertRaisesRegex(RuntimeError, "序列瞬态副本"):
                audit()
            self.assertEqual(state.registry, {})
            self.assertEqual(state.exported, [])

    def test_false_spawn_key_in_middle_fails_without_repair(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            key = SimpleNamespace(get_time=lambda: SimpleNamespace(frame_number=SimpleNamespace(value=15), sub_frame=0.0),
                                  get_value=lambda: False)
            state.channel.get_keys = lambda: [key]
            with self.assertRaisesRegex(RuntimeError, "播放中途关闭"):
                audit()
            self.assertEqual(state.copied, [])

    def test_directory_link_fails_before_copying(self):
        with TemporaryDirectory() as folder:
            audit, state = self.fixture(folder)
            with patch("os.path.lexists", return_value=True), patch("os.path.islink", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "目录链接"):
                    audit()
            self.assertEqual(state.copied, [])


if __name__ == "__main__":
    unittest.main()
