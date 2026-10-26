"""/** 逐帧骨骼与接地数据的离线检查 不访问或修改运行时对象 */"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_LIMITS = {
    "expected_fps": 60.0,
    "max_frame_interval_ratio": 1.6,
    "plant_ground_window": 8.0,
    "slide_speed": 35.0,
    "slide_min_seconds": 0.12,
    "penetration_depth": 3.0,
    "hover_height": 8.0,
    "contact_min_seconds": 0.10,
    "limb_extension_ratio": 1.08,
    "pelvis_step_ratio": 0.25,
    "root_step_degrees": 75.0,
    "knee_plane_step_degrees": 120.0,
    "steady_direction_degrees": 35.0,
}


def _length(vector):
    return math.sqrt(sum(value * value for value in vector))


def _sub(first, second):
    return tuple(a - b for a, b in zip(first, second))


def _dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def _cross(first, second):
    return (first[1] * second[2] - first[2] * second[1],
            first[2] * second[0] - first[0] * second[2],
            first[0] * second[1] - first[1] * second[0])


def _angle(first, second):
    denominator = _length(first) * _length(second)
    if denominator < 1e-8:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(first, second) / denominator))))


def _rotation_angle(first, second):
    dot = abs(_dot(first, second)) / max(_length(first) * _length(second), 1e-8)
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, dot))))


def _percentile(values, percentile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)]


def _bone(sample, name, space="world"):
    return sample["bones"][name][space]["position"]


def _reference_leg_length(sample, side):
    bones = sample["bones"]
    hip = bones["thigh_" + side]["referencePosition"]
    knee = bones["calf_" + side]["referencePosition"]
    ankle = bones["foot_" + side]["referencePosition"]
    return _length(_sub(hip, knee)) + _length(_sub(knee, ankle))


def _finite(values):
    return isinstance(values, (list, tuple)) and all(isinstance(value, (float, int))
        and math.isfinite(value) for value in values)


def _events(rows, minimum_seconds):
    events = []
    current = None
    for row in rows:
        if current is None or row["sample_index"] != current["last_index"] + 1:
            if current and current["duration_seconds"] >= minimum_seconds:
                events.append(current)
            current = {"first_frame": row["frame"], "last_frame": row["frame"],
                "first_time": row["time"], "last_time": row["time"],
                "duration_seconds": row["dt"], "peak": row["value"], "last_index": row["sample_index"]}
            continue
        current["last_frame"] = row["frame"]
        current["last_time"] = row["time"]
        current["duration_seconds"] += row["dt"]
        current["peak"] = max(current["peak"], row["value"])
        current["last_index"] = row["sample_index"]
    if current and current["duration_seconds"] >= minimum_seconds:
        events.append(current)
    for event in events:
        event.pop("last_index")
    return events


def analyze_frames(samples, phases=(), limits=None, summary=None, baseline=None, contact_curve_mode="plant_speed"):
    """
    /**
     * @param samples 按求值完成顺序的逐帧快照
     * @param phases 输入驱动返回的用例帧区间
     * @param limits 在修复前固定的检测阈值
     * @param summary 原生采集完成摘要
     * @param baseline 同用例的独立 GASP 检查结果
     * @param contact_curve_mode 显式指定原始接触权重或 GASP 重映射后的植足速度
     * @return 异常区间 指标 覆盖与分离的通过条件
     */
    """
    thresholds = dict(DEFAULT_LIMITS)
    if contact_curve_mode not in {"plant_speed", "contact_alpha"}:
        raise ValueError("contact_curve_mode must be plant_speed or contact_alpha")
    thresholds.update(limits or {})
    if not samples:
        return {"qualityPassed": False, "acceptancePassed": False, "error": "no_frames"}
    metrics = defaultdict(list)
    phase_metrics = defaultdict(lambda: defaultdict(list))
    flags = defaultdict(list)
    failures = []
    phase_counts = Counter()
    animations = Counter()
    excluded_frames = 0
    previous = None
    contact_data_frames = Counter()
    grounded_contact_frames = 0
    required_bones = ("root", "pelvis", "thigh_l", "calf_l", "foot_l", "ball_l",
                      "thigh_r", "calf_r", "foot_r", "ball_r")

    def record(kind, value, sample, index, dt, threshold=None):
        metrics[kind].append(value)
        if phase:
            phase_metrics[phase["name"]][kind].append(value)
        if threshold is not None and value > threshold:
            flags[kind].append({"frame": sample["frame"], "time": sample["worldTime"],
                "sample_index": index, "dt": dt, "value": value})

    for index, sample in enumerate(samples):
        frame = sample.get("frame", -1)
        phase = next((item for item in phases if item["start_frame"] <= frame <= item["end_frame"]), None)
        if phase:
            phase_counts[phase["name"]] += 1
        bones = sample.get("bones", {})
        invalid = [name for name in required_bones if name not in bones
            or not bones[name].get("world", {}).get("finite")
            or not _finite(bones[name].get("world", {}).get("position"))]
        if (sample.get("status") != "ok" or invalid or sample.get("poseError")
                or not _finite(sample.get("position"))):
            failures.append({"kind": "invalid_pose", "frame": frame, "bones": invalid})
            previous = None
            continue
        if not sample.get("finalizedCallback"):
            failures.append({"kind": "not_finalized", "frame": frame})
        dt = sample["worldTime"] - previous["worldTime"] if previous else 1.0 / thresholds["expected_fps"]
        if dt <= 0.0 or (previous and frame <= previous["frame"]):
            failures.append({"kind": "duplicate_or_reordered_frame", "frame": frame})
            previous = sample
            continue
        record("frame_interval_seconds", dt, sample, index, dt,
            thresholds["max_frame_interval_ratio"] / thresholds["expected_fps"])
        for match in sample.get("matches", []):
            if match.get("weight", 0.0) > 0.001:
                animations[match.get("animation", "")] += 1
        slots = sample.get("slots", {})
        context = sample.get("context", {})
        if sample.get("slotWeightSemantic") != "montage_global":
            failures.append({"kind": "unverified_slot_weight_semantic", "frame": frame})
        excluded = (slots.get("Traversal", 0.0) > 0.001 or slots.get('FullBody', 0.0) > 0.001
            or context.get("SourceLifePhase", "Alive") not in {"", "Alive", "0", "EBBBCharacterLifePhase::Alive"})
        if excluded:
            excluded_frames += 1
            previous = sample
            continue
        if sample.get("rootMotionMode") != 3:
            failures.append({"kind": "ordinary_root_motion_mode", "frame": frame,
                "actual": sample.get("rootMotionMode")})
        if not any(match.get("weight", 0.0) > 0.001 for match in sample.get("matches", [])):
            failures.append({"kind": "no_active_motion_matching", "frame": frame})
        if sample.get("generatedTrajectory", {}).get("sampleCount", 0) < 2:
            failures.append({"kind": "no_generated_trajectory", "frame": frame})
        if not any(history.get("sampleCount", 0) >= 2 for history in sample.get("histories", [])):
            failures.append({"kind": "no_history_trajectory", "frame": frame})

        grounded = sample.get("grounded", False)
        plant_settings = [item for item in sample.get('footPlacements', []) if item.get('alpha', 0) > 0.001]
        plant_threshold = None
        if len(plant_settings) == 1:
            plant_threshold = plant_settings[0].get('speedThreshold')
        if grounded and contact_curve_mode == 'plant_speed' and (plant_threshold is None or plant_threshold <= 0):
            failures.append({'kind': 'unverified_plant_settings', 'frame': frame})
        if grounded:
            grounded_contact_frames += 1
        curves = sample.get("curves", {})
        for side in ("l", "r"):
            leg_state = next((leg for node in plant_settings for leg in node.get('legs', [])
                if leg.get('bone') == 'foot_' + side), None)
            if grounded and leg_state is None:
                failures.append({'kind': 'unverified_plant_state', 'frame': frame, 'side': side})
            hip = _bone(sample, "thigh_" + side)
            knee = _bone(sample, "calf_" + side)
            ankle = _bone(sample, "foot_" + side)
            reference_length = _reference_leg_length(sample, side)
            if reference_length < 1e-4:
                failures.append({"kind": "invalid_reference_leg", "frame": frame, "side": side})
                continue
            record("limb_extension_" + side, _length(_sub(hip, ankle)) / reference_length,
                sample, index, dt, thresholds["limb_extension_ratio"])
            if previous:
                old_hip = _bone(previous, "thigh_" + side)
                old_knee = _bone(previous, "calf_" + side)
                old_ankle = _bone(previous, "foot_" + side)
                normal = _cross(_sub(hip, knee), _sub(ankle, knee))
                old_normal = _cross(_sub(old_hip, old_knee), _sub(old_ankle, old_knee))
                bend = 180.0 - _angle(_sub(hip, knee), _sub(ankle, knee))
                old_bend = 180.0 - _angle(_sub(old_hip, old_knee), _sub(old_ankle, old_knee))
                if min(bend, old_bend) > 10.0:
                    record("knee_plane_step_" + side, _angle(normal, old_normal), sample,
                        index, dt, thresholds["knee_plane_step_degrees"])
            foot = next((item for item in sample.get("feet", []) if item["side"] == side), None)
            if grounded and curves.get("DisableLegIK", 0.0) <= 0.5:
                record("ground_missing_" + side, float(not foot or not foot.get("groundHit")),
                    sample, index, dt, 0.0)
            if not grounded or not foot or not foot.get("groundHit") or curves.get("DisableLegIK", 0.0) > 0.5:
                continue
            height = min(foot["soleHeight"], foot["ballHeight"])
            record("sole_height_" + side, height, sample, index, dt)
            record("penetration_" + side, max(0.0, -height), sample, index, dt, thresholds["penetration_depth"])
            curve_name = "contact_" + side
            curve_present = curve_name in sample.get("activeCurveNames", [])
            if curve_present:
                contact_data_frames[side] += 1
            planted = curve_present and curves.get(curve_name, 0.0) >= 0.5
            if contact_curve_mode == "plant_speed":
                planted = curve_present and plant_threshold is not None and curves.get(curve_name, float("inf")) < plant_threshold
            planted = planted and leg_state is not None and leg_state.get('plantType') in (1, 2)
            if planted:
                record("planted_hover_" + side, max(0.0, height), sample, index, dt, thresholds["hover_height"])
            old_foot = next((item for item in previous.get("feet", []) if item["side"] == side), None) if previous else None
            if planted and abs(height) <= thresholds["plant_ground_window"] and old_foot and old_foot.get("groundHit"):
                old_present = curve_name in previous.get("activeCurveNames", [])
                old_planted = old_present and previous.get("curves", {}).get(curve_name, 0.0) >= 0.5
                if contact_curve_mode == "plant_speed":
                    old_settings = [item for item in previous.get('footPlacements', []) if item.get('alpha', 0) > 0.001]
                    old_planted = old_present and len(old_settings) == 1 and previous.get("curves", {}).get(curve_name, float("inf")) < old_settings[0].get('speedThreshold', 0)
                old_leg_state = next((leg for node in previous.get('footPlacements', [])
                    if node.get('alpha', 0) > 0.001 for leg in node.get('legs', [])
                    if leg.get('bone') == 'foot_' + side), None)
                old_planted = old_planted and old_leg_state is not None and old_leg_state.get('plantType') in (1, 2)
                old_height = min(old_foot.get('soleHeight', float('inf')), old_foot.get('ballHeight', float('inf')))
                if old_planted and previous.get("grounded") and abs(old_height) <= thresholds['plant_ground_window']:
                    joint = ('ball_' if plant_settings and plant_settings[0].get('lockType') == 1 else 'foot_') + side
                    displacement = _sub(_bone(sample, joint), _bone(previous, joint))
                    speed = math.hypot(displacement[0], displacement[1]) / dt
                    record("planted_slide_" + side, speed, sample, index, dt, thresholds["slide_speed"])
                    record("planted_slide_ratio_" + side, speed / reference_length, sample, index, dt)

        if previous:
            actor_delta = _sub(sample.get('meshTransform', {}).get('position', sample['position']),
                previous.get('meshTransform', {}).get('position', previous['position']))
            pelvis_delta = _sub(_sub(_bone(sample, "pelvis"), _bone(previous, "pelvis")), actor_delta)
            leg_length = _reference_leg_length(sample, "l")
            record("pelvis_step_ratio", _length(pelvis_delta) / max(leg_length, 1e-4),
                sample, index, dt, thresholds["pelvis_step_ratio"])
            root_rotation = bones["root"]["world"].get("rotation")
            old_root_rotation = previous["bones"]["root"]["world"].get("rotation")
            if _finite(root_rotation) and _finite(old_root_rotation):
                record("root_step_degrees", _rotation_angle(root_rotation, old_root_rotation),
                    sample, index, dt, thresholds["root_step_degrees"])
        if phase and phase.get("motion") == "steady":
            for match in sample.get("matches", []):
                error = match.get("directionErrorDegrees")
                tags = context.get("CurrentDatabaseTags", "").casefold()
                if error is not None and match.get("weight", 0.0) > 0.001 and not any(
                        word in tags for word in ("pivot", "start", "stop", "turn", "land")):
                    record("unwarped_direction_degrees", error, sample, index, dt)
                pose_error = match.get("poseDirectionErrorDegrees")
                if pose_error is not None and match.get("weight", 0.0) > 0.9 and not any(
                        word in tags for word in ("pivot", "start", "stop", "turn", "land")):
                    record("steady_direction_degrees", pose_error, sample, index, dt, thresholds["steady_direction_degrees"])
        previous = sample

    findings = []
    for kind, rows in flags.items():
        minimum = 0.0
        if kind.startswith("planted_slide_"):
            minimum = thresholds["slide_min_seconds"]
        if kind.startswith(("penetration_", "planted_hover_", "ground_missing_")):
            minimum = thresholds["contact_min_seconds"]
        events = _events(rows, minimum)
        if events:
            findings.append({"kind": kind, "events": events})
    missing_phases = [phase["name"] for phase in phases if phase_counts[phase["name"]] == 0]
    incomplete_phases = []
    for phase in phases:
        count = phase_counts[phase["name"]]
        expected = phase["end_frame"] - phase["start_frame"] + 1
        if count < expected:
            incomplete_phases.append({"name": phase["name"], "expected_frames": expected, "captured_frames": count})
    coverage_valid = bool(phases) and not missing_phases and not incomplete_phases
    turn_requested = any(item.get('motion') == 'turn' for item in phases)
    if turn_requested and not any('turn' in name.casefold() and count > 0 for name, count in animations.items()):
        failures.append({'kind': 'turn_animation_not_selected'})
    air_requested = any(item.get('motion') == 'airborne' for item in phases)
    airborne = [item for item in samples if not item.get('grounded', True)]
    if air_requested and not airborne:
        failures.append({'kind': 'jump_input_did_not_leave_ground'})
    if air_requested and airborne and not any(
            any(word in match.get('animation', '').casefold() for word in ('jump', 'fall'))
            and match.get('weight', 0) > 0.1 for item in airborne for match in item.get('matches', [])):
        failures.append({'kind': 'airborne_animation_not_selected'})
    capture_valid = (summary is not None and summary.get("state") in {"completed", "stopped"}
        and summary.get("missingPoseFrames") == 0 and summary.get("sampleCount") == len(samples))
    contact_valid = grounded_contact_frames > 0 and all(
        contact_data_frames[side] == grounded_contact_frames for side in ("l", "r"))
    quality_passed = not failures and not findings and capture_valid and contact_valid
    baseline_valid = bool(baseline and baseline.get("referenceFactsVerified") and baseline.get("captureValid")
        and baseline.get("failureCount") == 0 and baseline.get("coverageValid")
        and baseline.get("contactCurveMode") == contact_curve_mode
        and set(baseline.get("phaseSamples", {})) == set(phase_counts))
    baseline_comparisons = []
    if baseline_valid:
        for phase_name, values_by_metric in phase_metrics.items():
            source_metrics = baseline.get("phaseMetrics", {}).get(phase_name, {})
            for name, values in values_by_metric.items():
                if name not in source_metrics or not name.startswith(("planted_slide_ratio_", "pelvis_step_ratio", "root_step_degrees")):
                    continue
                source_p99 = source_metrics[name]["p99"]
                allowance = 0.06 if name.startswith("planted_slide_ratio_") else 0.01
                if name == "root_step_degrees":
                    allowance = 2.0
                limit = source_p99 * 1.5 + allowance
                actual = _percentile(values, 0.99)
                baseline_comparisons.append({"phase": phase_name, "metric": name,
                    "sourceP99": source_p99, "actualP99": actual, "limit": limit,
                    "passed": actual <= limit})
    baseline_matched = baseline_valid and bool(baseline_comparisons) and all(item["passed"] for item in baseline_comparisons)
    return {"schemaVersion": 1, "sampleCount": len(samples), "limits": thresholds,
        "contactCurveMode": contact_curve_mode, "contactDataFrames": dict(contact_data_frames),
        "contactCoverageValid": contact_valid, "groundedContactFrames": grounded_contact_frames,
        "captureValid": capture_valid, "qualityPassed": quality_passed,
        "coverageValid": coverage_valid, "baselineValid": baseline_valid,
        "baselineQualityPassed": bool(baseline and baseline.get("qualityPassed")),
        "baselineMatched": baseline_matched, "baselineComparisons": baseline_comparisons,
        "acceptancePassed": quality_passed and coverage_valid and baseline_matched,
        "excludedActionFrames": excluded_frames, "missingPhases": missing_phases,
        "incompletePhases": incomplete_phases, "phaseSamples": dict(phase_counts),
        "failures": failures[:100], "failureCount": len(failures), "findings": findings,
        "phaseMetrics": {name: {metric: {"count": len(values), "max": max(values),
            "p95": _percentile(values, 0.95), "p99": _percentile(values, 0.99)}
            for metric, values in by_metric.items()} for name, by_metric in phase_metrics.items()},
        "animations": animations.most_common(), "metrics": {name: {"count": len(values),
            "min": min(values), "max": max(values), "p95": _percentile(values, 0.95),
            "p99": _percentile(values, 0.99)} for name, values in metrics.items()}}


def read_capture(file_path):
    """/** @param file_path 原生采集路径 @return 帧数组和完成摘要 */"""
    rows = [json.loads(line) for line in Path(file_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return ([row for row in rows if row.get("sampleType") == "frame"],
        next((row for row in reversed(rows) if row.get("sampleType") == "summary"), None))


def compare_reference_facts(reference_samples, fact_samples, world_offset=(0, 600, 0)):
    """/** @param reference_samples 来源求值帧 @param fact_samples 原始事实帧 @param world_offset 明确偏移 @return 逐帧事实一致性与覆盖 */"""
    mismatches = []
    seen = set()
    vectors = ("velocityWorld", "accelerationWorld", "inputWorld", "lastUpdateVelocity", "meshComponentVelocity", "capsuleComponentVelocity", "floorNormal")
    scalars = ("maxSpeed", "maxAcceleration", "brakingDeceleration", "groundFriction", "capsuleHalfHeight", "analogInputModifier",
        "gravityZ", "brakingFriction", "brakingFrictionFactor", "brakingSubStepTime", "rotationRateYaw", "floorDistance")
    for sample in reference_samples:
        index = sample.get("referenceReplayFrame", -1)
        if index < 0 or index >= len(fact_samples):
            mismatches.append({"kind": "invalid_replay_index", "index": index})
            continue
        if index in seen:
            if index != len(fact_samples) - 1:
                mismatches.append({"kind": "duplicate_replay_index", "index": index})
            continue
        seen.add(index)
        fact = fact_samples[index]
        for name in vectors:
            if name not in sample or name not in fact or _length(_sub(sample[name], fact[name])) > 0.01:
                mismatches.append({"kind": "vector_fact", "index": index, "field": name})
        expected_position = tuple(value + offset for value, offset in zip(fact["position"], world_offset))
        if _length(_sub(sample["position"], expected_position)) > 0.01:
            mismatches.append({"kind": "position_fact", "index": index})
        mesh = sample.get('meshTransform', {})
        fact_mesh = fact.get('meshTransform', {})
        if not mesh.get('finite') or not fact_mesh.get('finite'):
            mismatches.append({'kind': 'mesh_transform_missing', 'index': index})
        if mesh.get('finite') and fact_mesh.get('finite'):
            expected_mesh = tuple(value + offset for value, offset in zip(fact_mesh['position'], world_offset))
            if _length(_sub(mesh['position'], expected_mesh)) > 0.01:
                mismatches.append({'kind': 'mesh_position_fact', 'index': index})
            if _rotation_angle(mesh['rotation'], fact_mesh['rotation']) > 0.01:
                mismatches.append({'kind': 'mesh_rotation_fact', 'index': index})
        for name in scalars:
            if name not in sample or name not in fact or abs(sample[name] - fact[name]) > 0.01:
                mismatches.append({"kind": "scalar_fact", "index": index, "field": name})
        for name in ("grounded", "crouching", "movementMode", "separateBrakingFriction", "orientRotationToMovement",
                "useControllerDesiredRotation", "useControllerRotationYaw", "floorBlockingHit", "floorWalkable", "justTeleported"):
            if sample.get(name) != fact.get(name):
                mismatches.append({"kind": "state_fact", "index": index, "field": name})
        for name in ("actorYaw", "controlYaw"):
            if abs((sample[name] - fact[name] + 180) % 360 - 180) > 0.01:
                mismatches.append({"kind": "rotation_fact", "index": index, "field": name})
        expected_gait = "NewEnumerator1" if fact.get("gaitRunning") and not fact.get("crouching") else "NewEnumerator0"
        if sample.get("context", {}).get("Gait") != expected_gait:
            mismatches.append({"kind": "gait_fact", "index": index})
    missing = sorted(set(range(len(fact_samples))) - seen)
    return {"passed": not mismatches and not missing and bool(fact_samples), "comparedFrames": len(seen),
        "expectedFrames": len(fact_samples), "missingFrames": missing, "mismatchCount": len(mismatches),
        "mismatches": mismatches[:100], "worldOffset": list(world_offset)}


def analyze_capture(file_path, phases=(), limits=None, baseline=None, contact_curve_mode="plant_speed",
                    reference_facts_path="", reference_offset=(0, 600, 0)):
    """
    /**
     * @param file_path 原生采集的 JSONL 文件
     * @param phases 输入用例帧区间
     * @param limits 固定阈值
     * @param baseline 独立来源检查结果
     * @param contact_curve_mode 接触曲线的明确语义
     * @return 完整逐帧检查结果
     */
    """
    samples, summary = read_capture(file_path)
    report = analyze_frames(samples, phases, limits, summary, baseline, contact_curve_mode)
    report["capturePath"] = str(Path(file_path).resolve())
    report["referenceFactsVerified"] = False
    if reference_facts_path:
        facts, _ = read_capture(reference_facts_path)
        checked = compare_reference_facts(samples, facts, reference_offset)
        report["referenceFacts"] = checked
        report["referenceFactsVerified"] = checked["passed"]
        report["qualityPassed"] = report["qualityPassed"] and checked["passed"]
    return report
