import copy
import importlib.util
import math
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "Scripts/BBBMotionMatchingPoseQuality.py"
SPEC = importlib.util.spec_from_file_location("pose_quality", SOURCE)
QUALITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALITY)


def frames(count=30):
    positions = {"root": [0, 0, 0], "pelvis": [0, 0, 100]}
    for side, y in (("l", -10), ("r", 10)):
        positions.update({"thigh_" + side: [0, y, 100], "calf_" + side: [3, y, 55],
            "foot_" + side: [0, y, 10], "ball_" + side: [12, y, 1]})
    samples = []
    for index in range(count):
        bones = {name: {"referencePosition": position,
            "world": {"finite": True, "position": position[:], "rotation": [0, 0, 0, 1]}}
            for name, position in positions.items()}
        feet = [{"side": side, "groundHit": True, "soleHeight": 0, "ballHeight": 0,
            "soleWorld": [0, y, 0], "ballSoleWorld": [12, y, 0]}
            for side, y in (("l", -10), ("r", 10))]
        samples.append({"status": "ok", "frame": 100 + index, "worldTime": index / 60,
            "finalizedCallback": True, "position": [0, 0, 100], "rootMotionMode": 3,
            "grounded": True, "bones": bones, "feet": feet, "curves": {"contact_l": 0, "contact_r": 0},
            "activeCurveNames": ["contact_l", "contact_r"],
            "context": {"SourceLifePhase": "Alive"}, "slots": {},
            "slotWeightSemantic": "montage_global",
            "generatedTrajectory": {"sampleCount": 46}, "histories": [{"sampleCount": 46}],
            "footPlacements": [{"alpha": 1, "speedThreshold": 1, "lockType": 1,
                "legs": [{'bone': 'foot_l', 'plantType': 1}, {'bone': 'foot_r', 'plantType': 1}]}],
            "matches": [{"weight": 1, "animation": "idle"}]})
    return samples


def analyze(samples, **kwargs):
    summary = {"state": "completed", "missingPoseFrames": 0, "sampleCount": len(samples)}
    phases = [{"name": "idle", "start_frame": 100, "end_frame": 99 + len(samples), "motion": "idle"}]
    return QUALITY.analyze_frames(samples, phases=phases, summary=summary, **kwargs)


class PoseQualityTests(unittest.TestCase):
    """/** 用独立异常序列验证动态判定 不把单个平均值作为通过条件 */"""

    def test_valid_stationary_contact_needs_independent_baseline_for_acceptance(self):
        result = analyze(frames())
        self.assertTrue(result["qualityPassed"])
        self.assertTrue(result["coverageValid"])
        self.assertFalse(result["acceptancePassed"])
        result["referenceFactsVerified"] = True
        compared = analyze(frames(), baseline=result)
        self.assertTrue(compared["acceptancePassed"])

    def test_continuous_planted_slide_is_detected(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample["feet"][0]["soleWorld"][0] = index * 2
            sample["feet"][0]["ballSoleWorld"][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        result = analyze(samples)
        self.assertIn("planted_slide_l", {item["kind"] for item in result["findings"]})
        self.assertFalse(result["qualityPassed"])

    def test_turn_reference_cannot_pass_by_remain_in_idle(self):
        samples = frames()
        result = QUALITY.analyze_frames(samples,
            phases=[{'name': 'turn', 'start_frame': 100, 'end_frame': 129, 'motion': 'turn'}],
            summary={'state': 'completed', 'missingPoseFrames': 0, 'sampleCount': len(samples)})
        self.assertIn('turn_animation_not_selected', {item['kind'] for item in result['failures']})
        self.assertFalse(result['qualityPassed'])

    def test_desired_contact_does_not_imply_an_actual_foot_lock(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample['footPlacements'][0]['legs'][0]['plantType'] = 0
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        self.assertTrue(analyze(samples)['qualityPassed'])
        for sample in samples:
            sample['footPlacements'][0]['legs'][0]['plantType'] = 1
        self.assertFalse(analyze(samples)['qualityPassed'])

    def test_missing_native_plant_state_cannot_approve_a_capture(self):
        samples = frames()
        for sample in samples:
            sample['footPlacements'][0].pop('legs')
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])
        self.assertIn('unverified_plant_state', {row['kind'] for row in result['failures']})

    def test_post_fullbody_action_is_separate_from_basic_motion(self):
        samples = frames()
        for sample in samples[:10]:
            sample['slots']['FullBody'] = 1
            sample['footPlacements'][0]['alpha'] = 0
        result = analyze(samples)
        self.assertEqual(result['excludedActionFrames'], 10)
        self.assertTrue(result['qualityPassed'])

    def test_ball_pivot_does_not_misclassify_heel_rotation_as_slide(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample['bones']['foot_l']['world']['position'][:2] = [12 - 20 * math.cos(index / 29 * math.pi / 2), -10 + 20 * math.sin(index / 29 * math.pi / 2)]
            sample['feet'][0]['soleWorld'][:2] = sample['bones']['foot_l']['world']['position'][:2]
        result = analyze(samples)
        self.assertTrue(result['qualityPassed'])
        for sample in samples:
            sample['footPlacements'][0]['lockType'] = 2
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])

    def test_grounded_jump_fixture_does_not_approve_airborne_coverage(self):
        samples = frames()
        result = QUALITY.analyze_frames(samples,
            phases=[{'name': 'jump', 'start_frame': 100, 'end_frame': 129, 'motion': 'airborne'}],
            summary={'state': 'completed', 'missingPoseFrames': 0, 'sampleCount': len(samples)})
        self.assertIn('jump_input_did_not_leave_ground', {item['kind'] for item in result['failures']})

    def test_swing_foot_is_not_classified_as_planted_slide_or_hover(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample["curves"]["contact_l"] = 200
            sample["feet"][0].update(soleHeight=25, ballHeight=25, soleWorld=[index * 5, -10, 25])
        result = analyze(samples)
        self.assertFalse(result["findings"])

    def test_sustained_penetration_and_hover_are_separate(self):
        samples = frames()
        for sample in samples:
            sample["feet"][0].update(soleHeight=-8, ballHeight=-8)
            sample["feet"][1].update(soleHeight=15, ballHeight=15)
        kinds = {item["kind"] for item in analyze(samples)["findings"]}
        self.assertTrue({"penetration_l", "planted_hover_r"}.issubset(kinds))

    def test_missing_ground_does_not_silently_skip_detection(self):
        samples = frames()
        for sample in samples:
            sample["feet"][0]["groundHit"] = False
        self.assertIn("ground_missing_l", {item["kind"] for item in analyze(samples)["findings"]})

    def test_duplicate_sample_is_invalid(self):
        samples = frames()
        samples[5] = copy.deepcopy(samples[4])
        result = analyze(samples)
        self.assertFalse(result["qualityPassed"])
        self.assertIn("duplicate_or_reordered_frame", {item["kind"] for item in result["failures"]})

    def test_one_frame_bone_pop_cannot_be_hidden_by_low_mean(self):
        samples = frames(120)
        samples[60]["bones"]["pelvis"]["world"]["position"][2] += 40
        result = analyze(samples)
        self.assertIn("pelvis_step_ratio", {item["kind"] for item in result["findings"]})

    def test_crouch_capsule_center_shift_is_not_a_world_pose_pop(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample['meshTransform'] = {'position': [0, 0, 0]}
            sample['position'][2] = 74 if index >= 10 else 100
        result = analyze(samples)
        self.assertTrue(result['qualityPassed'])

    def test_incomplete_capture_and_missing_phase_do_not_pass(self):
        samples = frames()
        result = QUALITY.analyze_frames(samples,
            phases=[{"name": "missing", "start_frame": 500, "end_frame": 600}], summary=None)
        self.assertFalse(result["captureValid"])
        self.assertFalse(result["coverageValid"])
        self.assertFalse(result["acceptancePassed"])

    def test_unrelated_reference_case_cannot_approve_current_case(self):
        baseline = analyze(frames())
        baseline["phaseSamples"] = {"other": 30}
        result = analyze(frames(), baseline=baseline)
        self.assertFalse(result["baselineValid"])

    def test_reference_findings_do_not_relax_project_quality_requirements(self):
        baseline = analyze(frames())
        baseline.update(referenceFactsVerified=True, qualityPassed=False,
            findings=[{'kind': 'planted_slide_l', 'events': []}])
        clean = analyze(frames(), baseline=baseline)
        self.assertTrue(clean['baselineValid'])
        self.assertFalse(clean['baselineQualityPassed'])
        self.assertTrue(clean['acceptancePassed'])
        samples = frames()
        for index, sample in enumerate(samples):
            sample['feet'][0]['soleWorld'][0] = index * 2
            sample['feet'][0]['ballSoleWorld'][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        checked = analyze(samples, baseline=baseline)
        self.assertFalse(checked['qualityPassed'])
        self.assertFalse(checked['acceptancePassed'])

    def test_missing_contact_curve_is_not_treated_as_planted_zero_speed(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample["activeCurveNames"] = []
            sample["feet"][0]["soleWorld"][0] = index * 2
            sample["feet"][0]["ballSoleWorld"][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        result = analyze(samples)
        self.assertNotIn("planted_slide_l", {item["kind"] for item in result["findings"]})
        self.assertEqual(result["contactDataFrames"], {})
        self.assertFalse(result["qualityPassed"])
        self.assertFalse(result["contactCoverageValid"])

    def test_unwarped_root_direction_is_only_a_diagnostic(self):
        samples = frames()
        for sample in samples:
            sample['matches'][0]['directionErrorDegrees'] = 90
            sample['matches'][0]['poseDirectionErrorDegrees'] = 0
        phases = [{'name': 'walk', 'start_frame': 100, 'end_frame': 129, 'motion': 'steady'}]
        summary = {'state': 'completed', 'missingPoseFrames': 0, 'sampleCount': len(samples)}
        result = QUALITY.analyze_frames(samples, phases, summary=summary)
        self.assertTrue(result['qualityPassed'])
        samples[15]['matches'][0]['poseDirectionErrorDegrees'] = 90
        result = QUALITY.analyze_frames(samples, phases, summary=summary)
        self.assertFalse(result['qualityPassed'])

    def test_all_action_frames_cannot_satisfy_ordinary_motion_acceptance(self):
        samples = frames()
        for sample in samples:
            sample['slots'] = {'Traversal': 1.0}
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])
        self.assertFalse(result['contactCoverageValid'])
        self.assertEqual(result['excludedActionFrames'], len(samples))

    def test_empty_trajectory_cannot_pass_even_with_an_active_animation(self):
        samples = frames()
        samples[10]['generatedTrajectory']['sampleCount'] = 0
        samples[10]['histories'] = []
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])
        self.assertEqual({item['kind'] for item in result['failures']},
            {'no_generated_trajectory', 'no_history_trajectory'})

    def test_rolling_foot_uses_actual_bound_plant_threshold(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample['curves']['contact_l'] = 15
            sample['feet'][0]['soleWorld'][0] = index * 2
            sample['feet'][0]['ballSoleWorld'][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        result = analyze(samples)
        self.assertTrue(result['qualityPassed'])
        for sample in samples:
            sample['footPlacements'][0]['speedThreshold'] = 60
        self.assertFalse(analyze(samples)['qualityPassed'])

    def test_missing_bound_plant_settings_cannot_pass(self):
        samples = frames()
        samples[10].pop('footPlacements')
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])
        self.assertIn('unverified_plant_settings', {item['kind'] for item in result['failures']})

    def test_legacy_slot_node_weight_has_no_acceptance_authority(self):
        samples = frames()
        for sample in samples:
            sample.pop('slotWeightSemantic')
        result = analyze(samples)
        self.assertFalse(result['qualityPassed'])
        self.assertIn('unverified_slot_weight_semantic', {item['kind'] for item in result['failures']})

    def test_reference_requires_same_cmc_facts_on_every_replayed_frame(self):
        raw = frames(3)
        for item in raw:
            item.update(velocityWorld=[100, 0, 0], accelerationWorld=[1200, 0, 0], inputWorld=[1, 0, 0],
                maxSpeed=200, maxAcceleration=1200, brakingDeceleration=1400, groundFriction=8,
                deltaSeconds=0.02, capsuleHalfHeight=86, analogInputModifier=1, gravityZ=-980, brakingFriction=0,
                brakingFrictionFactor=2, brakingSubStepTime=0.016, rotationRateYaw=360,
                movementMode=1, crouching=False, actorYaw=0, controlYaw=0, gaitRunning=False,
                separateBrakingFriction=False, orientRotationToMovement=False,
                useControllerDesiredRotation=False, useControllerRotationYaw=False,
                lastUpdateVelocity=[100, 0, 0], meshComponentVelocity=[100, 0, 0], capsuleComponentVelocity=[100, 0, 0],
                floorNormal=[0, 0, 1], floorDistance=2.15, floorBlockingHit=True, floorWalkable=True, justTeleported=False)
            item['meshTransform'] = {'finite': True, 'position': [0, 0, 2.15], 'rotation': [0, 0, 0, 1]}
        source = copy.deepcopy(raw)
        for index, item in enumerate(source):
            item['referenceReplayFrame'] = index
            item['position'][1] += 600
            item['meshTransform']['position'][1] += 600
            item['context']['Gait'] = 'NewEnumerator0'
        self.assertTrue(QUALITY.compare_reference_facts(source, raw)['passed'])
        source[1]['deltaSeconds'] = 1 / 60
        checked = QUALITY.compare_reference_facts(source, raw)
        self.assertFalse(checked['passed'])
        self.assertEqual(checked['mismatches'][0]['field'], 'deltaSeconds')
        source[1]['deltaSeconds'] = 0.02
        source[1]['analogInputModifier'] = 0
        checked = QUALITY.compare_reference_facts(source, raw)
        self.assertFalse(checked['passed'])
        self.assertEqual(checked['mismatches'][0]['field'], 'analogInputModifier')
        source[1]['analogInputModifier'] = 1
        source[1]['meshTransform']['position'][2] += 12.4
        checked = QUALITY.compare_reference_facts(source, raw)
        self.assertFalse(checked['passed'])
        self.assertEqual(checked['mismatches'][0]['kind'], 'mesh_position_fact')

    def test_raw_contact_alpha_is_distinct_from_remapped_speed(self):
        samples = frames()
        for index, sample in enumerate(samples):
            sample["curves"].update(contact_l=1, contact_r=0)
            sample["feet"][0]["soleWorld"][0] = index * 2
            sample["feet"][0]["ballSoleWorld"][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
            sample["feet"][1]["soleWorld"][0] = index * 2
            sample["feet"][1]["ballSoleWorld"][0] = index * 2
            sample['bones']['ball_l']['world']['position'][0] = index * 2 + 12
        result = analyze(samples, contact_curve_mode="contact_alpha")
        kinds = {item["kind"] for item in result["findings"]}
        self.assertIn("planted_slide_l", kinds)
        self.assertNotIn("planted_slide_r", kinds)


if __name__ == "__main__":
    unittest.main()
