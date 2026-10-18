import heapq
import math


def _add(a, b):
    return tuple(a[index] + b[index] for index in range(3))


def _sub(a, b):
    return tuple(a[index] - b[index] for index in range(3))


def _mul(a, scalar):
    return tuple(value * scalar for value in a)


def _dot(a, b):
    return sum(a[index] * b[index] for index in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _segment(point, start, end):
    delta = _sub(end, start)
    length_squared = _dot(delta, delta)
    if length_squared <= 1e-24:
        return tuple(start)

    alpha = max(0.0, min(1.0, _dot(_sub(point, start), delta) / length_squared))
    return _add(start, _mul(delta, alpha))


def closest_point_triangle(point, a, b, c):
    """
    /**
     * @param point	查询点
     * @param a		三角面首顶点
     * @param b		三角面第二顶点
     * @param c		三角面第三顶点
     * @return 最近点 支持退化为线段或点的三角面
     */
    """
    ab = _sub(b, a)
    ac = _sub(c, a)
    normal = _cross(ab, ac)
    if _dot(normal, normal) <= 1e-24:
        candidates = [_segment(point, a, b), _segment(point, b, c), _segment(point, c, a)]
        return min(candidates, key=lambda value: _dot(_sub(point, value), _sub(point, value)))

    ap = _sub(point, a)
    d1 = _dot(ab, ap)
    d2 = _dot(ac, ap)
    if d1 <= 0.0 and d2 <= 0.0:
        return tuple(a)

    bp = _sub(point, b)
    d3 = _dot(ab, bp)
    d4 = _dot(ac, bp)
    if d3 >= 0.0 and d4 <= d3:
        return tuple(b)

    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        return _add(a, _mul(ab, d1 / (d1 - d3)))

    cp = _sub(point, c)
    d5 = _dot(ab, cp)
    d6 = _dot(ac, cp)
    if d6 >= 0.0 and d5 <= d6:
        return tuple(c)

    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        return _add(a, _mul(ac, d2 / (d2 - d6)))

    va = d3 * d6 - d5 * d4
    if va <= 0.0 and d4 - d3 >= 0.0 and d5 - d6 >= 0.0:
        return _add(b, _mul(_sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6))))

    inverse = 1.0 / (va + vb + vc)
    return _add(a, _add(_mul(ab, vb * inverse), _mul(ac, vc * inverse)))


class TriangleSurface:
    """/** 按实际三角面建立离线最近点查询树 不使用碰撞形体 */"""

    def __init__(self, surface, triangle_ids=None):
        """/** @param surface 零级表面导出数据 @param triangle_ids 可选明确面片区域 @return 可复用的三角面查询树 */"""
        positions = {row["id"]: tuple(row["position"]) for row in surface["vertices"]}
        allowed = None
        if triangle_ids is not None:
            allowed = set(triangle_ids)

        self.triangles = []
        for row in surface["triangles"]:
            if allowed is not None and row["id"] not in allowed:
                continue

            vertices = [positions[vertex] for vertex in row["vertices"]]
            if any(len(value) != 3 or any(not math.isfinite(number) for number in value) for value in vertices):
                raise ValueError("三角面存在非有限坐标")

            self.triangles.append((row["id"], *vertices))

        if not self.triangles:
            raise ValueError("实际三角面区域不能为空")

        self.nodes = []
        self.root = self._build(list(range(len(self.triangles))))

    def _build(self, indices):
        bounds_minimum = tuple(min(self.triangles[index][corner][axis] for index in indices for corner in (1, 2, 3)) for axis in range(3))
        bounds_maximum = tuple(max(self.triangles[index][corner][axis] for index in indices for corner in (1, 2, 3)) for axis in range(3))
        node = len(self.nodes)
        self.nodes.append((bounds_minimum, bounds_maximum, None, None, None))
        if len(indices) <= 12:
            self.nodes[node] = (bounds_minimum, bounds_maximum, indices, None, None)
            return node

        axis = max(range(3), key=lambda value: bounds_maximum[value] - bounds_minimum[value])
        indices.sort(key=lambda index: sum(self.triangles[index][corner][axis] for corner in (1, 2, 3)))
        middle = len(indices) // 2
        left = self._build(indices[:middle])
        right = self._build(indices[middle:])
        self.nodes[node] = (bounds_minimum, bounds_maximum, None, left, right)
        return node

    def _bound_distance(self, point, node):
        minimum, maximum = self.nodes[node][:2]
        return sum(max(minimum[axis] - point[axis], 0.0, point[axis] - maximum[axis]) ** 2 for axis in range(3))

    def nearest(self, point):
        """/** @param point 同一空间的有限查询点 @return 距离 面片编号 最近点和局部法向间隙 后者不代表闭合体内外判定 */"""
        if len(point) != 3 or any(not math.isfinite(value) for value in point):
            raise ValueError("查询点必须包含三个有限坐标")

        queue = [(0.0, self.root)]
        best_squared = math.inf
        best = None
        while queue:
            lower_bound, node = heapq.heappop(queue)
            if lower_bound > best_squared:
                break

            minimum, maximum, indices, left, right = self.nodes[node]
            if indices is not None:
                for index in indices:
                    identifier, a, b, c = self.triangles[index]
                    closest = closest_point_triangle(point, a, b, c)
                    delta = _sub(point, closest)
                    squared = _dot(delta, delta)
                    if squared < best_squared:
                        best_squared = squared
                        normal = _cross(_sub(b, a), _sub(c, a))
                        length = math.sqrt(_dot(normal, normal))
                        unit = None
                        signed = None
                        if length > 1e-12:
                            unit = _mul(normal, 1.0 / length)
                            signed = _dot(delta, unit)

                        best = {"triangle": identifier, "point": closest, "normal": unit, "normalGapCm": signed}

                continue

            for child in (left, right):
                bound = self._bound_distance(point, child)
                if bound <= best_squared:
                    heapq.heappush(queue, (bound, child))

        best["distanceCm"] = math.sqrt(best_squared)
        return best


def audit_contacts(points, surface, triangle_ids=None):
    """
    /**
     * @param points		具有 id 和 position 的明确指腹或掌心点
     * @param surface		同一空间内的真实目标网格
     * @param triangle_ids	可选人工确认的接触面区域
     * @return 逐点三角面距离和范围统计 不把局部法向符号当体积穿透结论
     */
    """
    tree = TriangleSurface(surface, triangle_ids)
    rows = []
    for point in points:
        row = tree.nearest(point["position"])
        row["id"] = point["id"]
        rows.append(row)

    distances = sorted(row["distanceCm"] for row in rows)
    summary = {"count": len(rows), "normalSignIsVolumeClassification": False}
    if distances:
        summary["minimumCm"] = distances[0]
        summary["medianCm"] = distances[len(distances) // 2]
        summary["maximumCm"] = distances[-1]

    return {"summary": summary, "points": rows}
