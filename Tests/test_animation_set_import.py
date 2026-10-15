import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class AnimationSetImportTests(unittest.TestCase):
    """/** 独立网格与动作导入的共享骨架回归 */"""

    def setUp(self):
        """/** @return 隔离引擎和源文件替身 */"""
        class Mesh:
            def get_path_name(self):
                return "/Game/Fight/Meshes/SK_Male.SK_Male"

            def get_editor_property(self, name):
                return skeleton

        class Sequence:
            def get_path_name(self):
                return self.path

            def get_editor_property(self, name):
                return skeleton

            def get_play_length(self):
                return 1.0

            def set_preview_skeletal_mesh(self, value):
                self.preview = value

        skeleton = Mock()
        skeleton.get_path_name.return_value = "/Game/Fight/Meshes/Skeleton.Skeleton"
        self.mesh = Mesh()
        self.sequence_type = Sequence
        self.tasks = []
        self.embedded = False
        self.engine = Mock()
        self.engine.SkeletalMesh = Mesh
        self.engine.AnimSequence = Sequence
        self.engine.FbxImportUI.side_effect = lambda: types.SimpleNamespace(anim_sequence_import_data=Mock())
        self.engine.AssetImportTask.side_effect = Mock
        self.engine.EditorAssetLibrary.does_directory_exist.return_value = False
        self.engine.EditorAssetLibrary.list_assets.return_value = []
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True

        def imported(tasks):
            for task in tasks:
                self.tasks.append(task)
                objects = [self.mesh, skeleton]
                if task.options.import_mesh and self.embedded:
                    sequence = Sequence()
                    sequence.path = "/Game/Fight/Meshes/SK_Male_Anim.SK_Male_Anim"
                    objects.append(sequence)
                if not task.options.import_mesh:
                    sequence = Sequence()
                    sequence.path = task.destination_path + "/" + task.destination_name
                    objects = [sequence]
                task.get_objects.return_value = objects

        self.engine.AssetToolsHelpers.get_asset_tools.return_value.import_asset_tasks.side_effect = imported
        namespace = {}
        source = Path(__file__).resolve().parents[1] / "Scripts/BBBAnimationSetImport.py"
        with patch.dict(sys.modules, {"unreal": self.engine}):
            exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), namespace)
        self.run_import = namespace["import_skeletal_animation_set"]
        self.root = str(source.parent.resolve())

    def import_files(self, names):
        """/** @return 明确源数组的导入结果 */"""
        files = [str(Path(self.root) / name) for name in names]
        with patch("os.path.isfile", return_value=True), patch("os.path.islink", return_value=False):
            return json.loads(self.run_import(json.dumps(files), "/Game/Fight", "SK_Male"))

    def test_mesh_only_first_file_and_numeric_animation_names(self):
        """/** @return 独立源网格不尝试当作动画重复导入 */"""
        result = self.import_files(["Male.fbx", "05 attack.fbx", "06 dodge.fbx"])
        self.assertEqual(len(self.tasks), 3)
        self.assertEqual(len(result["animations"]), 2)
        self.assertEqual(self.tasks[1].destination_name, "AN_05_attack")
        for task in self.tasks[1:]:
            self.assertIs(task.options.skeleton, self.mesh.get_editor_property("skeleton"))

    def test_embedded_first_animation_is_imported_once(self):
        """/** @return 含动画的首个网格文件只执行一次导入 */"""
        self.embedded = True
        result = self.import_files(["Embedded.fbx", "Attack.fbx"])
        self.assertEqual(len(self.tasks), 2)
        self.assertEqual(len(result["animations"]), 2)

    def test_normalized_duplicate_names_rejected_before_import(self):
        """/** @return 文件名归一化冲突在任何写入前拒绝 */"""
        with self.assertRaisesRegex(RuntimeError, "重复"):
            self.import_files(["Male.fbx", "05 attack.fbx", "AN_05_attack.fbx"])
        self.assertEqual(self.tasks, [])

    def test_factory_side_animation_is_reported(self):
        """/** @return 工厂附带创建但任务未直接返回的动画仍被保存和报告 */"""
        sequence = self.sequence_type()
        sequence.path = "/Game/Fight/Meshes/SK_Male_Anim.SK_Male_Anim"
        self.engine.EditorAssetLibrary.list_assets.return_value = [sequence.path]
        self.engine.EditorAssetLibrary.load_asset.return_value = sequence
        result = self.import_files(["Male.fbx", "Attack.fbx"])
        self.assertEqual(len(result["animations"]), 2)
        self.assertEqual(result["animations"][0]["asset"], sequence.path)


if __name__ == "__main__":
    unittest.main()
