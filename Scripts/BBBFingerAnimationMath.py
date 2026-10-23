import math


def unit(values):
    """/** @param values 有限非零向量 @return 单位向量 */"""
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('FINGER_NONFINITE')
    length = math.sqrt(sum(v * v for v in values))
    if length < 1e-9:
        raise ValueError('FINGER_DEGENERATE_AXIS')
    return [v / length for v in values]


def multiply(a, b):
    """/** @param a 左四元数 @param b 右四元数 @return XYZW乘积 */"""
    x, y, z, w = a
    i, j, k, s = b
    return [w*i+x*s+y*k-z*j, w*j-x*k+y*s+z*i, w*k+x*j-y*i+z*s, w*s-x*i-y*j-z*k]


def inverse(q):
    """/** @param q 单位四元数 @return 逆旋转 */"""
    return [-q[0], -q[1], -q[2], q[3]]


def axis_angle(axis, degrees):
    """/** @param axis 单位轴 @param degrees 有符号角度 @return 单位四元数 */"""
    half = math.radians(degrees) / 2
    return [v * math.sin(half) for v in axis] + [math.cos(half)]


def split(q, axis):
    """/** @param q 相对参考旋转 @param axis 校准轴 @return 保留其余旋转与有符号轴角 */"""
    amount = sum(q[i] * axis[i] for i in range(3))
    length = math.hypot(amount, q[3])
    if length < 1e-8:
        raise ValueError('FINGER_SINGULAR_ROTATION')
    angle = math.degrees(2 * math.atan2(amount / length, q[3] / length))
    angle = (angle + 180) % 360 - 180
    twist = axis_angle(axis, angle)
    return unit(multiply(q, inverse(twist))), angle


def distance(a, b):
    """/** @param a 第一旋转 @param b 第二旋转 @return 最短弧角度 */"""
    return math.degrees(2 * math.acos(min(1.0, abs(sum(x*y for x, y in zip(a, b))))))


def process(rotations, rule, excluded):
    """/** @param rotations 实际局部旋转序列 @param rule 显式关节约束 @param excluded 例外帧集合 @return 允许域内平滑候选及逐帧异常 */"""
    neutral = unit(rule['neutral'])
    axis = unit(rule['axis'])
    if len(neutral) != 4 or len(axis) != 3 or rule['kind'] not in ('hinge', 'spread'):
        raise ValueError('FINGER_RULE_INVALID')
    low, high = rule['limits_degrees']
    tolerance = rule['tolerance_degrees']
    if not all(math.isfinite(v) for v in (low, high, tolerance)) or not -179 < low <= high < 179 or not 0 <= tolerance <= 10:
        raise ValueError('FINGER_LIMIT_INVALID')
    angles, residuals, errors = [], [], []
    centers = rule.get('centers_degrees', [0.0] * len(rotations))
    if len(centers) != len(rotations) or not all(math.isfinite(v) for v in centers):
        raise ValueError('FINGER_CENTER_COUNT_INVALID')
    for frame, rotation in enumerate(rotations):
        q = unit(rotation)
        if frame in excluded:
            angles.append(0.0)
            residuals.append([0, 0, 0, 1])
            continue
        other, angle = split(unit(multiply(inverse(neutral), q)), axis)
        off_axis = distance(other, [0, 0, 0, 1]) if rule['kind'] == 'hinge' else 0.0
        lower, upper = low + centers[frame], high + centers[frame]
        excess = max(lower - angle, angle - upper, 0.0)
        angles.append(min(upper, max(lower, angle)))
        residuals.append(other)
        if frame not in excluded and max(off_axis, excess) > tolerance:
            errors.append({'frame': frame, 'offAxisDegrees': off_axis, 'limitExcessDegrees': excess})
    active = {e['frame'] for e in errors}
    output = [list(q) for q in rotations]
    if not active:
        return output, errors
    # 只在连续异常区间内平滑屈曲量 合格采样及例外帧不改
    for unused in range(4):
        previous = angles[:]
        for frame in active:
            if 0 < frame < len(angles) - 1 and frame - 1 not in excluded and frame + 1 not in excluded:
                angles[frame] = min(high + centers[frame], max(low + centers[frame], (previous[frame-1] + 2*previous[frame] + previous[frame+1]) / 4))
    for frame in active:
        relative = axis_angle(axis, angles[frame])
        if rule['kind'] == 'spread':
            relative = multiply(residuals[frame], relative)
        output[frame] = unit(multiply(neutral, relative))
    return output, errors
