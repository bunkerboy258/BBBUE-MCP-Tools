import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]


class ControlRigSequenceLifecycleTests(unittest.TestCase):
    """/** 验证 Sequencer 重建实例时的写键顺序与失败保护 */"""

    def setUp(self):
        """/** @return 隔离的官方序列与控制器 API */"""
        tree = ast.parse((ROOT / "Scripts/BBBControlRigAuthoringToolset.py").read_text(encoding="utf-8-sig"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == "configure_sequence_rig")
        method.decorator_list = []
        self.engine = Mock()
        self.sequence = Mock()
        self.asset = Mock()
        self.mesh = Mock()
        self.track = Mock()
        self.binding = Mock()
        self.binding.find_tracks_by_type.return_value = []
        self.track.get_sections.return_value = []
        self.rig = Mock()
        self.track.get_path_name.return_value = "Track"
        self.rig.get_path_name.return_value = "RigInstance"
        self.opened = False
        self.old_rig = Mock()
        self.engine.LevelSequenceEditorBlueprintLibrary.open_level_sequence.side_effect = self.open
        self.engine.ControlRigSequencerLibrary.find_or_create_control_rig_track.return_value = self.track
        self.engine.ControlRigSequencerLibrary.get_control_rigs.side_effect = self.proxies
        self.access = Mock()
        namespace = {"unreal": self.engine, "json": json, "require_write_access": self.access,
                     "_asset": lambda path, kind: {"Sequence": self.sequence, "Rig": self.asset, "Mesh": self.mesh}[path],
                     "_mesh_binding": lambda sequence, mesh: self.binding}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "sequence_lifecycle_test", "exec"), namespace)
        self.configure = namespace[method.name]

    def open(self, sequence):
        """/** @return 打开序列使旧预览实例失效 */"""
        self.opened = True

    def proxies(self, sequence):
        """/** @return 打开前后分别返回不同控制器实例 */"""
        proxy = Mock()
        proxy.track = self.track
        proxy.control_rig = self.rig if self.opened else self.old_rig
        return [proxy]

    def test_open_before_instance_lookup(self):
        """/** @return 写键使用打开后建立的当前实例 */"""
        channel = Mock()
        channel.get_keys.return_value = [object()]
        self.track.get_sections.return_value = [Mock(get_all_channels=Mock(return_value=[channel]))]
        self.configure("Sequence", "Rig", json.dumps([{"frame": 0, "control": "Weight", "value": 1.0}]), False, "Mesh")
        self.engine.ControlRigSequencerLibrary.set_local_control_rig_float.assert_called_once()
        self.assertIs(self.engine.ControlRigSequencerLibrary.set_local_control_rig_float.call_args.args[1], self.rig)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.sequence)

    def test_missing_keys_never_save(self):
        """/** @return 官方 API 静默漏写时阻止保存 */"""
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", json.dumps([{"frame": 0, "control": "Weight", "value": 1.0}]), False, "Mesh")
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_write_denied_before_sequencer_open(self):
        """/** @return 写入被拒绝时不打开或构造编辑轨道 */"""
        self.access.side_effect = RuntimeError("PIE")
        with self.assertRaises(RuntimeError):
            self.configure("Sequence", "Rig", "[]", False, "Mesh")
        self.engine.LevelSequenceEditorBlueprintLibrary.open_level_sequence.assert_not_called()
        self.engine.ControlRigSequencerLibrary.find_or_create_control_rig_track.assert_not_called()


if __name__ == "__main__":
    unittest.main()
