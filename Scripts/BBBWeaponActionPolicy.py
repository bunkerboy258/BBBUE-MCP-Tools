"""Explicit action input validation shared by offline NumPy worker and Unreal Python."""
import math
from numbers import Real


def validate_action_phase_window(window, frame_count=None):
    """/** @param window 明确阶段和可选边界保持 @param frame_count 源帧数 @return 通过验证的四阶段帧 不计算或搜索姿态 */"""
    boundary = window.get('boundary_hold', False)
    if type(boundary) != bool:
        raise ValueError('边界保持标记必须为布尔值')
    phases = window.get('phase_frames')
    if not isinstance(phases, list) or len(phases) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in phases):
        raise ValueError('动作阶段必须为四个有限帧号')
    first, full, leave, end = phases
    if not first < full <= leave < end:
        raise ValueError('动作修正阶段必须按时间顺序明确')
    if boundary:
        if type(frame_count) != int or frame_count < 1:
            raise ValueError('边界保持必须给出真实源帧数')
        if first < -1 or end > frame_count or not 0 <= full <= leave <= frame_count - 1:
            raise ValueError('边界保持只允许前后各一帧 且满权阶段必须在实际动作内')
    elif first < 0 or frame_count is not None and end >= frame_count:
        raise ValueError('未声明边界保持的阶段必须位于源帧范围')
    return phases


def validate_finger_pose_windows(windows, bone_names, frame_count):
    """/** @param windows 完整指骨旋转窗口 @param bone_names 实际骨名 @param frame_count 源帧数 @return 显式可写指骨集合 只依赖标准库 */"""
    if not isinstance(windows, list) or not windows:
        raise ValueError('固定手指姿态窗口必须为非空数组')
    previous_end = -1
    names = set()
    for window in windows:
        if not isinstance(window, dict) or window.get('hand') not in ('hand_l', 'hand_r'):
            raise ValueError('固定手指姿态必须声明实际左右手')
        phases = validate_action_phase_window(window, frame_count)
        if phases[0] < previous_end:
            raise ValueError('固定手指姿态窗口必须有序不重叠且位于源帧范围')
        previous_end = phases[-1]
        suffix = window['hand'][-2:]
        expected = {f'{finger}_{joint:02d}{suffix}' for finger in ('thumb', 'index', 'middle', 'ring', 'pinky') for joint in (1, 2, 3)}
        rotations = window.get('local_rotations')
        if not isinstance(rotations, dict) or set(rotations) != expected or not expected <= set(bone_names):
            raise ValueError('固定手指姿态必须显式给出实际一只手完整十五指骨')
        for quaternion in rotations.values():
            if not isinstance(quaternion, (list, tuple)) or len(quaternion) != 4 or any(not isinstance(v, Real) or isinstance(v, bool) or not math.isfinite(v) for v in quaternion) or abs(math.sqrt(sum(v * v for v in quaternion)) - 1) > .0001:
                raise ValueError('固定手指姿态必须使用有限单位四元数')
        names.update(expected)
    return names
