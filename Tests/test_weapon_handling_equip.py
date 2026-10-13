import ast
import builtins
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class WeaponHandlingEquipTests(unittest.TestCase):
    """/** 只通过当前物品调试入口入包 不恢复已删除的装备注入入口 */"""

    def setUp(self):
        """/** @return 隔离 UE 访问并加载唯一装备入口 */"""
        tree = ast.parse((Path(__file__).resolve().parents[1] / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sample_runtime")
        self.world = object()
        self.actor = Mock()
        self.actor.get_path_name.return_value = "temporary_item_debug"
        self.definition_type = type("EquipmentDefinition", (), {})
        self.definition = self.definition_type()
        self.definition.get_editor_property = Mock(return_value="Weapon")
        self.controller = SimpleNamespace(get_active_item=Mock(return_value=None),
            get_item_slot_count=Mock(return_value=0), get_item_definition=Mock(),
            get_quick_access_slot_count=Mock(return_value=5), get_item_instance_id=Mock(return_value="stable_identity"),
            submit_item_move=Mock(return_value=True), submit_item_select=Mock(return_value=True))
        self.defaults = Mock()
        self.defaults.get_editor_property.return_value = self.definition
        self.engine = SimpleNamespace(
            UnrealEditorSubsystem=object(), BBBEquipmentDefinition=self.definition_type,
            get_editor_subsystem=Mock(return_value=SimpleNamespace(get_game_world=lambda: self.world)),
            load_class=Mock(side_effect=["equipment_class", "item_debug_class"]),
            get_default_object=Mock(return_value=self.defaults), Transform=Mock(return_value="transform"),
            GameplayStatics=SimpleNamespace(get_player_controller=Mock(return_value=self.controller)), log=Mock(),
            BBBBlueprintEditorLibrary=SimpleNamespace(
                begin_transient_pie_actor=Mock(return_value=self.actor),
                finish_transient_pie_actor=Mock(return_value=self.actor)))
        scope = {"unreal": self.engine, "builtins": builtins}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "weapon_equip", "exec"), scope)
        self.call = scope["sample_runtime"]

    def test_configures_formal_definition_before_begin_play(self):
        """/** @return 延迟构造先配置当前物品定义 再完成 BeginPlay */"""
        def finish(actor, transform):
            self.actor.set_editor_property.assert_any_call("item_definitions", [self.definition])
            self.actor.set_editor_property.assert_any_call("player_index", 0)
            return actor
        self.engine.BBBBlueprintEditorLibrary.finish_transient_pie_actor.side_effect = finish
        result = self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.assertEqual(result["actor"], "temporary_item_debug")
        self.assertEqual(result["state"], "injected")
        self.engine.load_class.assert_any_call(None, "/Game/_Project/Characters/BBBC_UA/Debug/Item/BP_ItemDebug.BP_ItemDebug_C")
        self.defaults.get_editor_property.assert_called_once_with("Definition")
        self.actor.destroy_actor.assert_not_called()

    def test_missing_definition_is_rejected_before_spawn(self):
        """/** @return 只接受装备正式定义 不直接写入角色或背包状态 */"""
        self.defaults.get_editor_property.return_value = None
        with self.assertRaises(RuntimeError):
            self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.engine.BBBBlueprintEditorLibrary.begin_transient_pie_actor.assert_not_called()

    def test_finish_failure_releases_own_actor(self):
        """/** @return 未完成生成时仅销毁本次临时演员 */"""
        self.engine.BBBBlueprintEditorLibrary.finish_transient_pie_actor.return_value = None
        with self.assertRaises(RuntimeError):
            self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.actor.destroy_actor.assert_called_once_with()

    def test_existing_item_is_moved_by_public_api_then_selected(self):
        """/** @return 已入包装备使用稳定身份移动到快捷格 再提交选择 不直接修改背包 */"""
        self.controller.get_item_slot_count.return_value = 12
        self.controller.get_item_definition.side_effect = [None] * 11 + [self.definition]
        result = self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.assertEqual(result["state"], "move_submitted")
        self.controller.submit_item_move.assert_called_once_with(11, 0, "stable_identity")
        self.controller.submit_item_select.assert_not_called()
        self.engine.BBBBlueprintEditorLibrary.begin_transient_pie_actor.assert_not_called()

    def test_select_waits_for_target_definition_in_quick_slot(self):
        """/** @return 快捷格已出现目标定义后才选择 不依赖同帧包处理顺序 */"""
        self.controller.get_item_slot_count.return_value = 1
        self.controller.get_item_definition.return_value = self.definition
        result = self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.assertEqual(result["state"], "select_submitted")
        self.controller.submit_item_move.assert_not_called()
        self.controller.submit_item_select.assert_called_once_with(0)

    def test_already_held_item_is_confirmed_without_new_input(self):
        """/** @return 实际主手已经是目标类型时只返回事实 不重复注入或切换 */"""
        active = Mock()
        active.get_class.return_value = "equipment_class"
        active.get_path_name.return_value = "held_weapon"
        self.controller.get_active_item.return_value = active
        result = self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.assertEqual(result["state"], "equipped")
        self.controller.submit_item_move.assert_not_called()
        self.controller.submit_item_select.assert_not_called()

    def test_rejected_move_does_not_select_wrong_item(self):
        """/** @return 移动输入拒绝时明确失败 不误选快捷格原有装备 */"""
        self.controller.get_item_slot_count.return_value = 2
        self.controller.get_item_definition.side_effect = [None, self.definition]
        self.controller.submit_item_move.return_value = False
        with self.assertRaisesRegex(RuntimeError, "移动输入未接受"):
            self.call("equip", 8, "/Game/Weapon.Weapon_C")
        self.controller.submit_item_select.assert_not_called()

    def test_rejected_select_does_not_report_equipped(self):
        """/** @return 选择输入拒绝时不将已提交移动冒充实际装备成功 */"""
        self.controller.get_item_slot_count.return_value = 1
        self.controller.get_item_definition.return_value = self.definition
        self.controller.submit_item_select.return_value = False
        with self.assertRaisesRegex(RuntimeError, "选择输入未接受"):
            self.call("equip", 8, "/Game/Weapon.Weapon_C")
