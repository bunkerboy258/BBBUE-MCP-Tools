import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import Mock


class MonsterGoreProductionTests(unittest.TestCase):
    """/** 正式导入的写入前边界 不作为画面验收 */"""

    def setUp(self):
        """/** @return 当前导入入口与写入替身 */"""
        source = Path(__file__).resolve().parents[1] / 'Scripts/BBBMonsterGoreProduction.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        function = next(v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == 'import_gore')
        self.engine = Mock()
        self.access = Mock()
        self.metadata = Mock()
        scope = {'unreal': self.engine, 'require_asset_write': self.access, 're': re, 'Path': Path,
                 'json': json, '_json': self.metadata}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
        self.run_import = scope['import_gore']
        self.definition = '/Game/_Project/Mass/Monster/SpecialInfected/UrbanZombie3/DA_UrbanZombie3Presentation'

    def test_unowned_path_and_unknown_stage_rejected(self):
        """/** @return 源目录与不明确阶段不触发任何引擎写入 */"""
        for path, phase in (('/Game/_ThirdParty/Zombie', 'body'), (self.definition, 'all')):
            with self.assertRaises(RuntimeError):
                self.run_import(path, phase, [])
        self.access.assert_not_called()
        self.engine.load_asset.assert_not_called()

    def test_pie_waits_before_loading_sources(self):
        """/** @return 运行中的世界不能导入资源 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = object()
        with self.assertRaises(RuntimeError):
            self.run_import(self.definition, 'body', [])
        self.metadata.assert_not_called()
        self.access.assert_not_called()

    def test_unbaked_source_rejected_before_write(self):
        """/** @return 未完成制作的资源不能冒充正式交付 */"""
        self.engine.get_editor_subsystem.return_value.get_game_world.return_value = None
        self.engine.Paths.project_dir.return_value = 'E:/BBB_Evac'
        self.metadata.return_value = {'baked': False, 'optimized': False, 'stage': 'prepared'}
        with self.assertRaises(RuntimeError):
            self.run_import(self.definition, 'body', [])
        self.access.assert_not_called()
        self.engine.load_asset.assert_not_called()

    def test_existing_texture_binding_is_confirmed_by_readback(self):
        """/** @return 已有绑定没有产生更改时仍以实际参数回读确认结果 */"""
        source = Path(__file__).resolve().parents[1] / 'Scripts/BBBMonsterGoreProduction.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        function = next(v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name == '_set_texture')
        scope = {'unreal': self.engine}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
        library = self.engine.MaterialEditingLibrary
        texture = object()
        library.get_texture_parameter_names.return_value = ['DestructionColor']
        library.set_material_instance_texture_parameter_value.return_value = False
        library.get_material_instance_texture_parameter_value.return_value = texture
        scope['_set_texture'](object(), 'DestructionColor', texture)
        library.get_material_instance_texture_parameter_value.assert_called_once()


if __name__ == '__main__':
    unittest.main()
