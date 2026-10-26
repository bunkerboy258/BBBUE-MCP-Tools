import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


class CharacterMontageGraphTests(unittest.TestCase):
    """/** 检查生命动作构图的明确写入范围与失败时禁止保存 */"""

    def setUp(self):
        tree = ast.parse((ROOT / 'Scripts/BBBMotionMatchingToolset.py').read_text(encoding='utf-8-sig'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                      and node.name == 'configure_character_montage_graph')
        method.decorator_list = []
        method.body = [node for node in method.body if not isinstance(node, (ast.ImportFrom, ast.Import))]
        self.engine = Mock()
        self.engine.AnimBlueprint = Mock
        self.engine.BlueprintStatus.BS_UP_TO_DATE = 'Ready'
        self.path = '/Game/_Project/Main'
        self.asset = Mock()
        self.asset.get_path_name.return_value = self.path
        self.asset.get_outermost.return_value.get_path_name.return_value = self.path
        self.asset.get_editor_property.return_value = 'Ready'
        self.engine.load_asset.return_value = self.asset
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = []
        self.native = self.engine.BBBAnimationGraphEditorLibrary.configure_character_montage_graph
        self.native.return_value = '{"configured": true}'
        self.engine.EditorAssetLibrary.save_loaded_asset.return_value = True
        self.access = Mock()
        namespace = {'unreal': self.engine, 'json': json, 'require_asset_write': self.access,
                     'BBBMotionMatchingCleanup': Mock(), 'importlib': SimpleNamespace(reload=lambda value: value)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'montage_graph_test', 'exec'), namespace)
        self.configure = namespace[method.name]

    def test_dry_run_has_no_compile_or_save(self):
        self.configure(self.path)
        self.native.assert_called_once_with(self.asset, False)
        self.access.assert_not_called()
        self.engine.BlueprintEditorLibrary.compile_blueprint.assert_not_called()
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()

    def test_only_explicit_main_is_saved_after_strict_compile(self):
        result = json.loads(self.configure(self.path, dry_run=False))
        self.access.assert_called_once_with([self.asset])
        self.native.assert_called_once_with(self.asset, True)
        self.engine.BlueprintEditorLibrary.compile_blueprint.assert_called_once_with(self.asset)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_called_once_with(self.asset, False)
        self.assertEqual(result['saved'], [self.path])

    def test_dirty_or_denied_target_never_reaches_native_mutation(self):
        self.access.side_effect = RuntimeError('占用')
        with self.assertRaises(RuntimeError):
            self.configure(self.path, dry_run=False)
        self.access.side_effect = None
        self.engine.EditorLoadingAndSavingUtils.get_dirty_content_packages.return_value = [self.asset.get_outermost()]
        with self.assertRaises(RuntimeError):
            self.configure(self.path, dry_run=False)
        self.native.assert_not_called()

    def test_external_asset_is_rejected_before_native_call(self):
        with self.assertRaises(RuntimeError):
            self.configure('/Game/ThirdParty/Main', dry_run=False)
        self.native.assert_not_called()

    def test_native_failure_or_compile_warning_prevents_save(self):
        self.native.return_value = '{"error": "构图失败"}'
        with self.assertRaises(RuntimeError):
            self.configure(self.path, dry_run=False)
        self.native.return_value = '{"configured": true}'
        self.asset.get_editor_property.return_value = 'Warning'
        with self.assertRaises(RuntimeError):
            self.configure(self.path, dry_run=False)
        self.engine.EditorAssetLibrary.save_loaded_asset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
