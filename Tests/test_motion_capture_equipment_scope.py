import ast
import json
import math
from types import SimpleNamespace
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MotionCaptureEquipmentScopeTests(unittest.TestCase):
    """/** 验证运行轨迹采样覆盖全部装备并明确缺失弹匣骨骼 */"""

    def setUp(self):
        """/** @return 不加载 UE 的工具语法树 */"""
        self.tree = ast.parse((ROOT / "Scripts/BBBAnimationMotionTools.py").read_text(encoding="utf-8-sig"))

    def test_equipment_query_uses_common_actor_class(self):
        """/** @return 手枪 霰弹枪与近战不会被步枪类型过滤 */"""
        class_paths = [node.value for node in ast.walk(self.tree)
                       if isinstance(node, ast.Constant) and isinstance(node.value, str)
                       and node.value.startswith("/Script/ABBB_Evac.")]
        self.assertEqual(class_paths, ["/Script/ABBB_Evac.BBBEquipment"])

    def test_missing_magazine_is_not_reported_as_component_transform(self):
        """/** @return 没有弹匣骨骼时输出空值而不是伪造位置 */"""
        checks = [node for node in ast.walk(self.tree) if isinstance(node, ast.IfExp)
                  and isinstance(node.test, ast.Call)
                  and isinstance(node.test.func, ast.Attribute)
                  and node.test.func.attr == "does_socket_exist"
                  and node.test.args and isinstance(node.test.args[0], ast.Constant)
                  and node.test.args[0].value == "Magazine_joint"]
        self.assertEqual(len(checks), 1)
        self.assertIsInstance(checks[0].orelse, ast.Constant)
        self.assertIsNone(checks[0].orelse.value)

    def test_capture_keeps_raw_compressed_and_runtime_poses_separate(self):
        """/** @return 压缩数据与角色最终姿势不会混记为原始动画 */"""
        evaluations = [node.value.attr for node in ast.walk(self.tree)
                       if isinstance(node, ast.Assign)
                       and isinstance(node.value, ast.Attribute)
                       and isinstance(node.value.value, ast.Attribute)
                       and node.value.value.attr == "AnimDataEvalType"]
        self.assertEqual(sorted(evaluations), ["COMPRESSED", "RAW"])
        dictionaries = [node for node in ast.walk(self.tree) if isinstance(node, ast.Dict)]
        self.assertTrue(any({"bones", "rawBones", "compressedBones"}.issubset(
            {key.value for key in node.keys if isinstance(key, ast.Constant)}) for node in dictionaries))

    def test_compressed_bone_validation_matches_fname_case_semantics(self):
        """/** @return 骨骼名称大小写不造成假的缺失骨骼错误 */"""
        normalized_names = [node for node in ast.walk(self.tree)
                            if isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "casefold"]
        self.assertEqual(len(normalized_names), 2)

    def test_named_views_accept_independent_world_offsets(self):
        """/** @return 实际动作允许明确取景且不新增第二套截图实现 */"""
        function = next(node for node in self.tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "_capture_views")
        namespace = {"json": json, "math": math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "views", "exec"), namespace)
        views = [{"name": "reverse", "offset": [0, -130, -30]},
                 {"name": "under", "offset": [100, 60, -50]}]
        self.assertEqual(namespace["_capture_views"](json.dumps(views)), views)
        self.assertEqual(len(namespace["_capture_views"]("")), 2)

    def test_named_views_reject_paths_duplicates_and_invalid_offsets(self):
        """/** @return 无效视角在创建临时目录或访问 UE 之前失败 */"""
        function = next(node for node in self.tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "_capture_views")
        namespace = {"json": json, "math": math}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "views", "exec"), namespace)
        invalid = [[], {}, [{"name": "../side", "offset": [0, 100, 0]}],
                   [{"name": "side", "offset": [0, 100]}],
                   [{"name": "side", "offset": [0, 0, 0]}],
                   [{"name": "side", "offset": [0, float("nan"), 0]}],
                   [{"name": "side", "offset": [0, 100, 0]}] * 2,
                   [{"name": str(index), "offset": [0, 100, 0]} for index in range(9)]]
        for views in invalid:
            with self.subTest(views=views), self.assertRaises(RuntimeError):
                namespace["_capture_views"](json.dumps(views))


class MontageTargetTests(unittest.TestCase):
    """/** 验证角色与武器动作的目标组件和源动画时间 */"""

    def setUp(self):
        self.tree = ast.parse((ROOT / "Scripts/BBBAnimationMotionTools.py").read_text(encoding="utf-8-sig"))

    def _function(self, name, namespace):
        function = next(node for node in self.tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
        exec(compile(ast.Module(body=[function], type_ignores=[]), name, "exec"), namespace)
        return namespace[name]

    def test_segment_play_rate_is_applied(self):
        values = {"anim_start_time": 0.1, "anim_end_time": 0.5, "anim_play_rate": 4.0, "start_pos": 0.2}
        segment = SimpleNamespace(get_editor_property=values.__getitem__)
        function = self._function("_segment_time", {})
        self.assertAlmostEqual(function(segment, 0.25), 0.3)
        self.assertEqual(function(segment, 0.1), 0.1)
        self.assertEqual(function(segment, 1.0), 0.5)
        values["anim_play_rate"] = 0.0
        with self.assertRaises(RuntimeError):
            function(segment, 0.25)

    def test_weapon_target_excludes_foreign_and_hidden_actors(self):
        character = SimpleNamespace(get_skinned_asset=lambda: SimpleNamespace(get_editor_property=lambda name: "character"))
        weapon = SimpleNamespace(get_skinned_asset=lambda: SimpleNamespace(get_editor_property=lambda name: "weapon"))
        pawn = SimpleNamespace(get_editor_property=lambda name: character)
        actor = lambda owner, hidden: SimpleNamespace(get_owner=lambda: owner, get_editor_property=lambda name: hidden,
            get_components_by_class=lambda cls: [weapon])
        actors = [actor(object(), False), actor(pawn, True), actor(pawn, False)]
        unreal_fake = SimpleNamespace(SkeletalMeshComponent=object,
            GameplayStatics=SimpleNamespace(get_all_actors_of_class=lambda world, cls: actors))
        function = self._function("_montage_mesh", {"unreal": unreal_fake})
        montage = SimpleNamespace(get_editor_property=lambda name: "weapon")
        self.assertIs(function(object(), pawn, montage, object()), weapon)
        actors.append(actor(pawn, False))
        with self.assertRaises(RuntimeError):
            function(object(), pawn, montage, object())

    def test_character_montage_keeps_character_component(self):
        character = SimpleNamespace(get_skinned_asset=lambda: SimpleNamespace(get_editor_property=lambda name: "character"))
        pawn = SimpleNamespace(get_editor_property=lambda name: character)
        montage = SimpleNamespace(get_editor_property=lambda name: "character")
        function = self._function("_montage_mesh", {})
        self.assertIs(function(object(), pawn, montage, object()), character)


class WeaponHandlingScopeTests(unittest.TestCase):
    """/** 验证持枪采样使用正式公共层与装备动画基类 */"""

    def test_camera_retention_uses_posture_without_airborne_scaling(self):
        """/** @return 保留比例直接按腰射与瞄准选择 不与空中倍率相乘 */"""
        tree = ast.parse((ROOT / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "configure_camera_recoil")
        assignment = next(node for node in ast.walk(function) if isinstance(node, ast.Assign)
                          and isinstance(node.targets[0], ast.Subscript)
                          and isinstance(node.targets[0].slice, ast.Constant)
                          and node.targets[0].slice.value == "PitchRetention")
        self.assertEqual(assignment.value.func.attr, "select")
        self.assertEqual([argument.args[0].id for argument in assignment.value.args[:2]], ["ads", "hip"])
        self.assertEqual([argument.args[1].value for argument in assignment.value.args[:2]], ["PitchRetention", "PitchRetention"])
        self.assertEqual(assignment.value.args[2].id, "aiming")

    def test_handling_probe_includes_equipment_and_layer_subclasses(self):
        """/** @return 不依赖步枪专属类型或旧动画层路径 */"""
        tree = ast.parse((ROOT / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sample_runtime")
        constants = [node.value for node in ast.walk(function) if isinstance(node, ast.Constant)]
        self.assertIn("/Game/_Project/Characters/BBBC_UA/AnimationSystem/Layers/ABP_BBB_LocomotionLayer_Base.ABP_BBB_LocomotionLayer_Base_C", constants)
        layer_call = next(node for node in ast.walk(function) if isinstance(node, ast.Call)
                          and isinstance(node.func, ast.Attribute)
                          and node.func.attr == "get_linked_anim_layer_instance_by_class")
        self.assertTrue(layer_call.args[1].value)
        self.assertTrue(any(isinstance(node, ast.Attribute) and node.attr == "BBBEquipmentAnimInstance"
                            for node in ast.walk(function)))
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == "BBBRifleAnimInstance"
                             for node in ast.walk(function)))

    def _probe_status(self, samples):
        """/** @param samples 合成逐帧事实 @return 不依赖 UE 的真实状态汇总 */"""
        tree = ast.parse((ROOT / "Scripts/BBBWeaponHandlingTools.py").read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "sample_runtime")
        state = {"state": "finished", "errors": [], "samples": samples}
        namespace = {"builtins": SimpleNamespace(BBB_WEAPON_HANDLING_PROBE=state)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "probe", "exec"), namespace)
        return namespace["sample_runtime"]("status", 8, "")

    def _sample(self, time, ammo, reloading, actor="Shotgun"):
        """/** @param time 游戏秒 @param ammo 当前弹量 @param reloading 换弹事实 @param actor 实例身份 @return 合成单帧事实 */"""
        return {"time": time, "aiming": False, "mode": "walking", "camera": [0, 0, 0],
            "characterOffset": [0, 0], "equipmentActor": actor, "ammo": ammo,
            "ammoCapacity": 8, "reloading": reloading, "actualAim": [640, 360], "viewport": [1280, 720],
            "viewRotation": [1, 2, 3], "viewFOV": 90, "muzzleRotation": [4, 5], "targetRotation": [6, 7],
            "aimOffset": [8, 9], "healthFraction": 1, "sourceAimAlpha": 1,
            "poseState": [0.5, 0.1, True, 0.8, False, 2],
            "presentation": {"heldObjects": [], "physicsObjects": [], "niagaraComponents": [],
                "magazineHidden": None, "mechanismPose": []}}

    def test_ammo_trace_records_each_load_and_reload_transition(self):
        """/** @return 重复帧不生成事件 每发装入与收束均保留实际时刻 */"""
        samples = [self._sample(0, 5, False), self._sample(0.1, 5, True),
            self._sample(0.2, 5, True), self._sample(1.2, 6, True),
            self._sample(3.4, 7, True), self._sample(5.6, 8, True), self._sample(6.6, 8, False)]
        result = self._probe_status(samples)
        self.assertEqual([event["ammo"] for event in result["ammoEvents"]], [5, 5, 6, 7, 8, 8])
        self.assertEqual([event["time"] for event in result["ammoEvents"]], [0, 0.1, 1.2, 3.4, 5.6, 6.6])
        self.assertEqual(len(result["sampleColumns"]), 35)
        self.assertTrue(all(len(row) == 35 for row in result["samples"]))
        self.assertEqual(result["samples"][0][10:14], [640, 360, 1280, 720])
        self.assertEqual(result["samples"][0][14:28], [0, 0, 0, 1, 2, 3, 90, 4, 5, 6, 7, 8, 9, 1])
        self.assertEqual(result["samples"][0][28:], [1, 0.5, 0.1, True, 0.8, False, 2])

    def test_missing_muzzle_is_recorded_as_unknown(self):
        """/** @return 不具备枪口的装备不伪造零角度 */"""
        sample = self._sample(0, None, None, "Bat")
        sample["muzzleRotation"] = [None, None]
        sample["targetRotation"] = [None, None]
        result = self._probe_status([sample])
        self.assertEqual(result["samples"][0][21:25], [None, None, None, None])

    def test_ammo_trace_keeps_actor_identity_on_switch(self):
        """/** @return 相同弹量的换枪仍生成新实例事件 */"""
        result = self._probe_status([self._sample(0, 5, False, "Shotgun01"),
            self._sample(1, 5, False, "Shotgun02")])
        self.assertEqual([event["actor"] for event in result["ammoEvents"]], ["Shotgun01", "Shotgun02"])

    def test_melee_does_not_fabricate_ammo_facts(self):
        """/** @return 无弹量接口的装备保留空值 不伪造零发 */"""
        result = self._probe_status([self._sample(0, None, None, "Bat")])
        self.assertEqual(result["ammoEvents"], [])
        self.assertIsNone(result["samples"][0][7])


if __name__ == "__main__":
    unittest.main()
